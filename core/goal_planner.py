"""WP-M04 — Goal Planner.

Transforms a CEO objective into a structured plan.
Haiku used only when goal is ambiguous — no Sonnet (Budget Protection).
No automatic execution: all proposed WPs require authorization.
"""

import json
import logging
import os
import uuid

from anthropic import Anthropic

from app.database import get_supabase
from core.adoption_service import adoption_svc
from core.compliance_engine import compliance_engine
from core.doc_source import DOC_PATHS

logger = logging.getLogger(__name__)

# ── Goal pattern matchers ──────────────────────────────────────────────────
_GOAL_PATTERNS: dict[str, dict] = {
    "footballiq": {
        "keywords": ["footballiq", "football", "produit", "product"],
        "required_docs": ["G-01", "G-02", "G-03", "G-05", "G-09", "G-11",
                          "A-01", "A-02", "A-03", "A-04", "A-05",
                          "P-01", "P-02", "P-03"],
        "required_capabilities": ["api_layer", "data_pipeline", "ai_scoring"],
        "requires_ceo_approval": True,
        "decision_level": "D3",
        "description": "Lancement produit FootballIQ",
    },
    "conformite": {
        "keywords": ["conformit", "compli", "audit", "certif"],
        "required_docs": ["G-05", "G-11"],
        "required_capabilities": [],
        "requires_ceo_approval": False,
        "decision_level": "D2",
        "description": "Audit de conformité organisationnelle",
    },
    "onboarding": {
        "keywords": ["onboard", "agent", "intégr", "nouveau"],
        "required_docs": ["G-03", "G-06"],
        "required_capabilities": [],
        "requires_ceo_approval": False,
        "decision_level": "D2",
        "description": "Onboarding d'un nouvel agent",
    },
    "securite": {
        "keywords": ["sécurité", "security", "access", "permission"],
        "required_docs": ["G-05", "G-08"],
        "required_capabilities": [],
        "requires_ceo_approval": False,
        "decision_level": "D2",
        "description": "Renforcement de la sécurité",
    },
}


def _match_pattern(goal: str) -> dict | None:
    goal_lower = goal.lower()
    for name, pattern in _GOAL_PATTERNS.items():
        if any(kw in goal_lower for kw in pattern["keywords"]):
            return pattern
    return None


def _compute_readiness(
    required_docs: list[str],
    adopted_ids: list[str],
    compliance_score: int,
) -> int:
    if not required_docs:
        return compliance_score
    doc_score = round(100 * len([d for d in required_docs if d in adopted_ids]) / len(required_docs))
    return round((doc_score * 0.6) + (compliance_score * 0.4))


async def _classify_with_haiku(goal: str) -> dict:
    """Fallback: Haiku classifies unrecognized goals into structured intent."""
    try:
        client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY", ""))
        prompt = (
            "Analyse cet objectif CEO et retourne UNIQUEMENT un JSON valide:\n"
            '{"type":"<onboarding|securite|conformite|autre>","required_docs":[],'
            '"description":"<courte>","requires_ceo_approval":false}\n\n'
            f"Objectif: {goal}"
        )
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=200,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = resp.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        return json.loads(raw.strip())
    except Exception as e:
        logger.warning(f"haiku classify: {e}")
        return {"type": "autre", "required_docs": [], "description": goal[:80], "requires_ceo_approval": True}


class GoalPlanner:
    def __init__(self):
        self.db = get_supabase()

    def identify_required_documents(self, goal: str) -> list[str]:
        pattern = _match_pattern(goal)
        if pattern:
            return pattern["required_docs"]
        return ["G-01", "G-11"]

    def identify_required_capabilities(self, goal: str) -> list[str]:
        pattern = _match_pattern(goal)
        return pattern["required_capabilities"] if pattern else []

    def identify_blockers(self, goal: str, adopted_ids: list[str]) -> list[str]:
        required = self.identify_required_documents(goal)
        missing = [d for d in required if d not in adopted_ids]
        # Also check if the doc exists on GitHub at all
        unknown = [d for d in required if d not in DOC_PATHS]
        blockers = []
        if missing:
            blockers.append(f"{len(missing)} document(s) requis non adoptés: {', '.join(missing[:4])}")
        if unknown:
            blockers.append(f"{len(unknown)} document(s) non créés dans GitHub: {', '.join(unknown[:3])}")
        pattern = _match_pattern(goal)
        if pattern and pattern.get("requires_ceo_approval"):
            blockers.append("Approbation CEO requise (D3)")
        return blockers

    def propose_work_packages(
        self,
        goal: str,
        missing_docs: list[str],
        blockers: list[str],
    ) -> list[dict]:
        wps = []
        # WP for each missing document
        for i, doc_id in enumerate(missing_docs[:5], 1):
            wps.append({
                "order": i,
                "title": f"Créer et valider {doc_id}",
                "type": "DOCUMENT_CREATION",
                "required_decision_level": "D2",
                "estimated_effort": "MEDIUM",
                "blocked_by": None,
            })
        # WP for compliance if gaps exist
        compliance = compliance_engine.compute_compliance_score()
        if compliance["overall_score"] < 80:
            wps.append({
                "order": len(wps) + 1,
                "title": f"Résoudre {len(compliance['gaps'])} gap(s) de conformité",
                "type": "COMPLIANCE_FIX",
                "required_decision_level": "D2",
                "estimated_effort": "LOW",
                "blocked_by": None,
            })
        return wps

    async def produce_plan(self, goal: str) -> dict:
        adopted = adoption_svc.list_adopted()
        adopted_ids = [d["doc_id"] for d in adopted]

        # Match deterministically first
        pattern = _match_pattern(goal)
        if not pattern:
            classified = await _classify_with_haiku(goal)
            pattern = {
                "required_docs": classified.get("required_docs", ["G-01", "G-11"]),
                "required_capabilities": [],
                "requires_ceo_approval": classified.get("requires_ceo_approval", True),
                "decision_level": "D3" if classified.get("requires_ceo_approval") else "D2",
                "description": classified.get("description", goal[:80]),
            }

        required_docs = pattern["required_docs"]
        missing_docs = [d for d in required_docs if d not in adopted_ids]
        not_in_github = [d for d in required_docs if d not in DOC_PATHS]
        blockers = self.identify_blockers(goal, adopted_ids)

        compliance = compliance_engine.compute_compliance_score()
        readiness = _compute_readiness(required_docs, adopted_ids, compliance["overall_score"])

        wps = self.propose_work_packages(goal, missing_docs, blockers)

        return {
            "plan_id": f"PLN-{uuid.uuid4().hex[:8].upper()}",
            "goal": goal,
            "description": pattern["description"],
            "readiness": readiness,
            "required_documents": required_docs,
            "adopted_documents": [d for d in required_docs if d in adopted_ids],
            "missing_documents": missing_docs,
            "documents_not_in_github": not_in_github,
            "required_capabilities": pattern.get("required_capabilities", []),
            "blockers": blockers,
            "proposed_work_packages": wps,
            "requires_ceo_approval": pattern.get("requires_ceo_approval", True),
            "decision_level": pattern.get("decision_level", "D3"),
            "compliance_score": compliance["overall_score"],
            "note": "Aucun WP n'est exécuté automatiquement. Autorisation CEO requise.",
        }

    async def analyze_goal(self, goal: str) -> dict:
        return await self.produce_plan(goal)


goal_planner = GoalPlanner()
