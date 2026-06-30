"""WP-M06 — Document Improvement Engine.

State machine:
  SUBMITTED → PRECHECK → VALIDATION → REMARK_ANALYSIS → DECISION
  → IMPLEMENTATION → REVALIDATION → COMPLIANCE → ADOPTION_PROPOSAL → ADOPTED

Guardrails:
  - Max 3 iterations per document
  - Never modify an ADOPTED document
  - Never modify without a Work Package
  - Never adopt without validation + compliance
  - Never modify Kernel document without D3 decision
  - No infinite loops

Budget Protection: 0 LLM calls for classification (deterministic keywords).
"""

import logging
import os
import uuid
from datetime import datetime, timezone

import httpx

from app.database import get_supabase
from core.adoption_service import adoption_svc
from core.compliance_engine import compliance_engine

_BACKEND_URL = os.getenv("BACKEND_URL", "https://organisation-ai.onrender.com")

logger = logging.getLogger(__name__)

MAX_ITERATIONS = 3
COMPLIANCE_THRESHOLD = 70

# Kernel documents — require D3 for modification
KERNEL_DOCS = {"G-01", "G-02", "G-03", "G-05", "G-09", "G-11"}

# Remark classification rules — deterministic, no LLM
_CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "AUTO_FIX": [
        "typo", "référence", "section", "tableau", "lien", "manquant",
        "incomplet", "format", "orthograph", "tronqu", "complét",
        "liste", "exhaustif", "référen", "acronyme", "sigle",
    ],
    "ARCHITECTURAL": [
        "politique", "règle", "workflow", "process", "architecture",
        "modification", "système", "composant", "interface", "api",
        "protocole", "intégr",
    ],
    "GOVERNANCE": [
        "d3", "kernel", "decision model", "gouvernance", "charte",
        "fondateur", "délégation", "autorisation", "approbation ceo",
        "changement majeur",
    ],
    "DOCUMENT_DEBT": [
        "futur", "optimis", "clarif", "amélior", "v2", "phase 2",
        "backlog", "v1.1", "phase suivante", "prochaine version",
    ],
}

DECISION_LEVEL_FOR_CATEGORY = {
    "AUTO_FIX": "D1",
    "ARCHITECTURAL": "D2",
    "GOVERNANCE": "D3",
    "DOCUMENT_DEBT": "D1",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _classify_remark(content: str) -> str:
    content_lower = content.lower()
    # Score each category
    scores: dict[str, int] = {cat: 0 for cat in _CATEGORY_KEYWORDS}
    for cat, keywords in _CATEGORY_KEYWORDS.items():
        scores[cat] = sum(1 for kw in keywords if kw in content_lower)
    best = max(scores, key=lambda c: scores[c])
    return best if scores[best] > 0 else "AUTO_FIX"


class DocumentImprovementEngine:
    def __init__(self):
        self.db = get_supabase()

    # ── Public API ─────────────────────────────────────────────────────────

    def create_run(self, doc_id: str) -> dict:
        """Create a new improvement run record and return it."""
        run_id = f"IMP-{doc_id}-{uuid.uuid4().hex[:8].upper()}"
        run = {
            "id": run_id,
            "doc_id": doc_id,
            "status": "SUBMITTED",
            "iteration": 0,
            "work_packages_created": [],
            "adoption_proposed": False,
            "created_at": _now(),
            "updated_at": _now(),
        }
        self.db.table("improvement_runs").insert(run).execute()
        return run

    def get_run(self, run_id: str) -> dict | None:
        try:
            rows = self.db.table("improvement_runs").select("*").eq("id", run_id).limit(1).execute()
            return rows.data[0] if rows.data else None
        except Exception as e:
            logger.error(f"get_run {run_id}: {e}")
            return None

    def get_latest_run(self, doc_id: str) -> dict | None:
        try:
            rows = (
                self.db.table("improvement_runs")
                .select("*")
                .eq("doc_id", doc_id)
                .order("created_at", desc=True)
                .limit(1)
                .execute()
            )
            return rows.data[0] if rows.data else None
        except Exception as e:
            logger.error(f"get_latest_run {doc_id}: {e}")
            return None

    def list_runs_by_status(self, status: str) -> list[dict]:
        try:
            return (
                self.db.table("improvement_runs")
                .select("id,doc_id,status,iteration,compliance_score,adoption_proposed,updated_at")
                .eq("status", status)
                .order("updated_at", desc=True)
                .limit(20)
                .execute()
            ).data or []
        except Exception as e:
            logger.error(f"list_runs_by_status {status}: {e}")
            return []

    # ── Main cycle ─────────────────────────────────────────────────────────

    async def run_cycle(self, run_id: str, tg_notify) -> None:
        """Full improvement cycle. Called as BackgroundTask."""
        run = self.get_run(run_id)
        if not run:
            logger.error(f"run_cycle: run {run_id} not found")
            return
        doc_id = run["doc_id"]
        try:
            await self._cycle(run, doc_id, tg_notify)
        except Exception as e:
            logger.error(f"run_cycle {run_id}: {e}")
            self._update_run(run_id, {"status": "BLOCKED", "escalation_reason": str(e)[:300]})
            await tg_notify(f"DIE — {doc_id}\nErreur interne : {str(e)[:200]}\nRun: {run_id}")

    async def _cycle(self, run: dict, doc_id: str, tg_notify) -> None:
        run_id = run["id"]

        # ── PRECHECK ──────────────────────────────────────────────────────
        self._update_run(run_id, {"status": "PRECHECK"})

        # Guard: ADOPTED document → no modification allowed
        adoption = adoption_svc.get_adoption(doc_id)
        if adoption and adoption.get("status") == "ADOPTED":
            self._update_run(run_id, {
                "status": "BLOCKED",
                "escalation_reason": f"{doc_id} est ADOPTED — aucune modification autorisée.",
            })
            await tg_notify(f"DIE — {doc_id}\nBLOQUÉ : document ADOPTED, aucune modification autorisée.")
            return

        # Guard: iteration limit
        iteration = run.get("iteration", 0)
        if iteration >= MAX_ITERATIONS:
            self._update_run(run_id, {
                "status": "ESCALATED",
                "escalation_reason": f"Limite {MAX_ITERATIONS} itérations atteinte sans résolution.",
            })
            await tg_notify(
                f"DIE — {doc_id}\nESCALATED après {MAX_ITERATIONS} itérations.\nIntervention CEO requise."
            )
            return

        # ── VALIDATION via /validate/doc (self-HTTP) ─────────────────────
        # Delegates to the existing endpoint which handles:
        # - GitHub fetch (with GITHUB_TOKEN from env)
        # - SHA dedup (ALREADY_VALIDATED if unchanged)
        # - Agent debate (Chief Architect + Chief Analyst)
        self._update_run(run_id, {"status": "VALIDATION"})

        try:
            async with httpx.AsyncClient(timeout=300) as c:
                r = await c.post(
                    f"{_BACKEND_URL}/validate/doc",
                    json={"doc_id": doc_id},
                )
                r.raise_for_status()
                val_api = r.json()
        except Exception as e:
            self._update_run(run_id, {"status": "BLOCKED", "escalation_reason": f"validate/doc error: {str(e)[:200]}"})
            await tg_notify(f"DIE — {doc_id}\nBLOQUÉ : erreur validation ({str(e)[:100]})")
            return

        api_status = val_api.get("status", "ERROR")

        if api_status in ("MISSING_DOCUMENTS", "UPLOAD_FAILED", "UNKNOWN_DOC", "ERROR"):
            self._update_run(run_id, {"status": "BLOCKED", "escalation_reason": f"{api_status}: {val_api.get('detail', val_api.get('error', ''))}"})
            await tg_notify(f"DIE — {doc_id}\nBLOQUÉ : {api_status}")
            return

        current_doc_sha = val_api.get("doc_sha")
        current_commit_sha = val_api.get("commit_sha")
        self._update_run(run_id, {
            "last_commit_sha": current_commit_sha,
            "last_doc_sha": current_doc_sha,
        })

        if api_status == "ALREADY_VALIDATED":
            # M06-H6: SHA unchanged → reuse existing validation
            last_val = self._latest_validation(doc_id)
            val_result = {
                "status": last_val["status"] if last_val else "RESOLVED",
                "remarks": (last_val.get("remarks") or []) if last_val else [],
                "doc_sha": current_doc_sha,
                "commit_sha": current_commit_sha,
                "reused": True,
            }
            await tg_notify(f"DIE — {doc_id}\nSHA inchangé — validation réutilisée (0 appel agent).")
        else:
            # Full validation ran
            val_result = {
                "status": api_status,
                "remarks": val_api.get("remarks") or [],
                "doc_sha": current_doc_sha,
                "commit_sha": current_commit_sha,
                "thread_id": val_api.get("thread_id", ""),
                "reused": False,
            }
            self._update_run(run_id, {
                "last_validation_id": f"VAL-{doc_id}-{val_api.get('thread_id','')}",
                "iteration": iteration + 1,
            })

        # ── REMARK_ANALYSIS ───────────────────────────────────────────────
        self._update_run(run_id, {"status": "REMARK_ANALYSIS"})

        remarks = val_result.get("remarks") or []
        classified = self._classify_remarks(remarks, doc_id)
        self._update_run(run_id, {"remarks_classified": classified})

        # ── DECISION ─────────────────────────────────────────────────────
        self._update_run(run_id, {"status": "DECISION"})

        # GOVERNANCE remarks on Kernel docs → escalate immediately
        gov_remarks = [r for r in classified if r["category"] == "GOVERNANCE"]
        if gov_remarks and doc_id in KERNEL_DOCS:
            self._update_run(run_id, {
                "status": "ESCALATED",
                "escalation_reason": "Changement gouvernance Kernel détecté — décision D3 CEO requise.",
            })
            await tg_notify(
                f"DIE — {doc_id}\nESCALATED — changement Kernel (D3 requis)\n"
                + "\n".join(f"• {r['content'][:100]}" for r in gov_remarks[:2])
            )
            return

        auto_fix = [r for r in classified if r["category"] == "AUTO_FIX"]
        arch = [r for r in classified if r["category"] == "ARCHITECTURAL"]

        # ── IMPLEMENTATION — Create WPs ───────────────────────────────────
        if auto_fix or arch:
            self._update_run(run_id, {"status": "IMPLEMENTATION"})
            wp_ids = []
            for r in auto_fix + arch:
                wp_id = self._create_wp(doc_id, r, run_id)
                if wp_id:
                    wp_ids.append(wp_id)

            existing_wps = run.get("work_packages_created") or []
            if isinstance(existing_wps, str):
                import json
                existing_wps = json.loads(existing_wps)
            self._update_run(run_id, {"work_packages_created": existing_wps + wp_ids})

            if wp_ids:
                await tg_notify(
                    f"DIE — {doc_id}\n"
                    f"{len(wp_ids)} WP(s) créé(s) pour amélioration :\n"
                    + "\n".join(f"• {w}" for w in wp_ids[:5])
                    + "\nImplémentation requise avant revalidation."
                )

        # ── COMPLIANCE ───────────────────────────────────────────────────
        if val_result["status"] == "RESOLVED":
            self._update_run(run_id, {"status": "COMPLIANCE"})
            comp = compliance_engine.check_document_compliance(doc_id)
            score = comp.get("score", 0)
            self._update_run(run_id, {"compliance_score": score})

            if score < COMPLIANCE_THRESHOLD:
                # Create compliance WP
                comp_wp_id = self._create_compliance_wp(doc_id, comp, run_id)
                existing_wps = run.get("work_packages_created") or []
                if isinstance(existing_wps, str):
                    import json
                    existing_wps = json.loads(existing_wps)
                self._update_run(run_id, {"work_packages_created": existing_wps + ([comp_wp_id] if comp_wp_id else [])})
                self._update_run(run_id, {"status": "IMPLEMENTATION"})
                await tg_notify(
                    f"DIE — {doc_id}\nConformité {score}% (seuil {COMPLIANCE_THRESHOLD}%)\n"
                    f"{len(comp.get('gaps',[]))} gap(s) — WP créé : {comp_wp_id}"
                )
                return

            # ── ADOPTION_PROPOSAL ─────────────────────────────────────────
            self._update_run(run_id, {"status": "ADOPTION_PROPOSAL", "adoption_proposed": True})
            await tg_notify(
                f"DIE — {doc_id}\n\n"
                f"Validation : OK\n"
                f"Compliance : {score}%\n"
                f"Aucun blocage.\n\n"
                f"Proposition : ADOPTER {doc_id}\n\n"
                f"Répondez A ou Adopte pour confirmer."
            )
        else:
            # ESCALATED from agents
            if iteration + 1 >= MAX_ITERATIONS:
                self._update_run(run_id, {
                    "status": "ESCALATED",
                    "escalation_reason": f"{MAX_ITERATIONS} itérations — agents n'ont pas atteint consensus.",
                })
                await tg_notify(
                    f"DIE — {doc_id}\nESCALATED après {iteration + 1} itérations.\nIntervention CEO requise."
                )
            else:
                self._update_run(run_id, {"status": "IMPLEMENTATION"})
                await tg_notify(
                    f"DIE — {doc_id}\nValidation {val_result['status']} — itération {iteration + 1}/{MAX_ITERATIONS}\n"
                    f"WPs créés, en attente de correction GitHub."
                )

    # ── Helpers ────────────────────────────────────────────────────────────

    def _update_run(self, run_id: str, fields: dict) -> None:
        try:
            fields["updated_at"] = _now()
            self.db.table("improvement_runs").update(fields).eq("id", run_id).execute()
        except Exception as e:
            logger.error(f"_update_run {run_id}: {e}")

    def _latest_validation(self, doc_id: str) -> dict | None:
        try:
            rows = (
                self.db.table("doc_validations")
                .select("document_id,status,doc_sha,commit_sha,thread_id,remarks,validated_at")
                .eq("document_id", doc_id)
                .order("validated_at", desc=True)
                .limit(1)
                .execute()
            )
            return rows.data[0] if rows.data else None
        except Exception as e:
            logger.error(f"_latest_validation {doc_id}: {e}")
            return None

    def _classify_remarks(self, remarks: list, doc_id: str) -> list[dict]:
        classified = []
        for r in remarks:
            content = r.get("content", "")
            category = _classify_remark(content)
            # Kernel doc + GOVERNANCE category override
            if doc_id in KERNEL_DOCS and category == "ARCHITECTURAL":
                category = "GOVERNANCE"
            classified.append({
                "tour": r.get("tour"),
                "decision": r.get("decision"),
                "category": category,
                "content": content[:200],
            })
        return classified

    def _create_wp(self, doc_id: str, remark: dict, run_id: str) -> str | None:
        category = remark["category"]
        level = DECISION_LEVEL_FOR_CATEGORY.get(category, "D2")
        wp_id = f"WP-IMP-{doc_id}-{uuid.uuid4().hex[:6].upper()}"
        title = f"[DIE/{category}] {doc_id} — {remark['content'][:80]}"
        try:
            self.db.table("work_packages").insert({
                "id": wp_id,
                "title": title,
                "status": "PENDING",
                "approved": False,  # CEO approval required before execution
                "blocked": False,
                "required_decision_level": level,
                "priority": "P2" if category == "AUTO_FIX" else "P1",
                "context_snapshot": {
                    "doc_id": doc_id,
                    "run_id": run_id,
                    "category": category,
                    "remark": remark["content"][:300],
                },
                "created_at": _now(),
                "updated_at": _now(),
            }).execute()
            return wp_id
        except Exception as e:
            logger.error(f"_create_wp {wp_id}: {e}")
            return None

    def _create_compliance_wp(self, doc_id: str, comp: dict, run_id: str) -> str | None:
        gaps = comp.get("gaps", [])
        if not gaps:
            return None
        wp_id = f"WP-COMP-{doc_id}-{uuid.uuid4().hex[:6].upper()}"
        title = f"[DIE/COMPLIANCE] {doc_id} — {len(gaps)} gap(s) ({comp.get('score', 0)}%)"
        try:
            self.db.table("work_packages").insert({
                "id": wp_id,
                "title": title,
                "status": "PENDING",
                "approved": False,
                "blocked": False,
                "required_decision_level": "D2",
                "priority": "P1" if comp.get("score", 100) < 50 else "P2",
                "context_snapshot": {
                    "doc_id": doc_id,
                    "run_id": run_id,
                    "gaps": gaps[:5],
                    "score": comp.get("score"),
                },
                "created_at": _now(),
                "updated_at": _now(),
            }).execute()
            return wp_id
        except Exception as e:
            logger.error(f"_create_compliance_wp {wp_id}: {e}")
            return None

    async def check_github_change(self, doc_id: str) -> dict:
        """Check if GitHub commit_sha changed since last run — trigger revalidation if so."""
        from core.doc_source import fetch_doc
        try:
            fetched = await fetch_doc(doc_id)
        except Exception as e:
            return {"changed": False, "status": "ERROR", "error": str(e)}
        if fetched["status"] != "OK":
            return {"changed": False, "status": fetched["status"]}

        last_run = self.get_latest_run(doc_id)
        last_sha = last_run.get("last_commit_sha") if last_run else None
        current_sha = fetched["commit_sha"]

        return {
            "doc_id": doc_id,
            "changed": current_sha != last_sha,
            "current_commit_sha": current_sha,
            "last_commit_sha": last_sha,
            "doc_sha": fetched["doc_sha"],
        }

    def accept_adoption_proposal(self, doc_id: str, run_id: str) -> dict:
        """CEO confirmed adoption — trigger adoption_svc."""
        self._update_run(run_id, {"status": "ADOPTED"})
        return {"doc_id": doc_id, "run_id": run_id, "action": "adoption_svc.request_adoption"}


die = DocumentImprovementEngine()
