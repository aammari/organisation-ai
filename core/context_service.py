"""WP-M03 — Organizational Context Service.

All context is built from live sources only:
  GitHub documents, adoption_registry, doc_validations,
  work_packages, decisions, action_ledger, capabilities.

No local memory. No unverified cache. No prior conversation as canonical source.
No LLM calls (Budget Protection).
"""

import logging
import uuid
from datetime import datetime, timezone

from app.database import get_supabase
from core.adoption_service import adoption_svc

logger = logging.getLogger(__name__)

ROLE_TOKEN_LIMITS = {
    "chief_architect": 8000,
    "chief_analyst": 4000,
    "chief_of_staff": 2000,
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


class ContextService:
    def __init__(self):
        self.db = get_supabase()

    def load_adopted_documents(self) -> list[dict]:
        return adoption_svc.list_adopted()

    def load_active_work_package(self) -> dict | None:
        try:
            rows = (
                self.db.table("work_packages")
                .select("id,title,status,priority,scheduled_at")
                .in_("status", ["PENDING", "RUNNING", "CLAIMED"])
                .eq("approved", True)
                .order("priority")
                .limit(1)
                .execute()
            )
            return rows.data[0] if rows.data else None
        except Exception as e:
            logger.error(f"load_active_wp: {e}")
            return None

    def load_recent_decisions(self, limit: int = 5) -> list[dict]:
        try:
            rows = (
                self.db.table("decisions")
                .select("id,title,decision_level,status,decided_at")
                .order("created_at", desc=True)
                .limit(limit)
                .execute()
            )
            return rows.data or []
        except Exception as e:
            logger.error(f"load_recent_decisions: {e}")
            return []

    def load_capabilities(self) -> list[dict]:
        try:
            rows = (
                self.db.table("capabilities")
                .select("id,name,status")
                .eq("status", "ACTIVE")
                .execute()
            )
            return rows.data or []
        except Exception as e:
            logger.error(f"load_capabilities: {e}")
            return []

    def load_pending_escalations(self) -> list[dict]:
        try:
            rows = (
                self.db.table("pending_escalations")
                .select("doc_id,objections,created_at")
                .eq("status", "WAITING_CEO")
                .limit(5)
                .execute()
            )
            return rows.data or []
        except Exception as e:
            logger.error(f"load_pending_esc: {e}")
            return []

    def summarize_context(
        self,
        adopted: list[dict],
        active_wp: dict | None,
        decisions: list[dict],
        capabilities: list[dict],
        escalations: list[dict],
        missing_docs: list[str],
    ) -> str:
        lines = ["## CONTEXTE ORGANISATIONNEL\n"]

        lines.append("### Documents adoptés")
        if adopted:
            for d in adopted:
                lines.append(f"- {d['doc_id']} v{d.get('version','?')} ({d.get('decision_level','?')})")
        else:
            lines.append("- Aucun document adopté")

        if missing_docs:
            lines.append("\n### Documents requis manquants")
            for d in missing_docs:
                lines.append(f"- {d} MANQUANT")

        if active_wp:
            lines.append(f"\n### Work Package actif\n- {active_wp['id']}: {active_wp['title']} [{active_wp['status']}]")

        if decisions:
            lines.append("\n### Décisions récentes")
            for d in decisions[:3]:
                lines.append(f"- [{d.get('decision_level','?')}] {d['title']}")

        if capabilities:
            lines.append("\n### Capacités actives")
            for c in capabilities[:5]:
                lines.append(f"- {c['name']}")

        if escalations:
            lines.append("\n### Escalades CEO en attente")
            for e in escalations:
                lines.append(f"- {e['doc_id']}: {e.get('objections','?')[:80]}…")

        return "\n".join(lines)

    async def build_context_for_mission(
        self,
        message: str,
        role: str = "chief_architect",
        include_validated: bool = False,
    ) -> dict:
        context_id = f"CTX-{uuid.uuid4().hex[:8].upper()}"

        adopted = self.load_adopted_documents()
        active_wp = self.load_active_work_package()
        decisions = self.load_recent_decisions()
        capabilities = self.load_capabilities()
        escalations = self.load_pending_escalations()

        adopted_ids = [d["doc_id"] for d in adopted]

        # Identify missing docs if message references known families
        missing_docs: list[str] = []
        message_upper = message.upper()
        from core.doc_source import DOC_PATHS
        if "FOOTBALLIQ" in message_upper or "PRODUCT" in message_upper:
            product_docs = [k for k in DOC_PATHS if k.startswith("P-") or k.startswith("A-")]
            missing_docs = [d for d in product_docs if d not in adopted_ids][:5]

        summary = self.summarize_context(
            adopted, active_wp, decisions, capabilities, escalations, missing_docs
        )

        tokens_estimate = _estimate_tokens(summary)
        token_limit = ROLE_TOKEN_LIMITS.get(role, 4000)
        if tokens_estimate > token_limit:
            summary = summary[:token_limit * 4] + "\n[résumé tronqué — limite rôle atteinte]"

        return {
            "context_id": context_id,
            "role": role,
            "documents": adopted_ids,
            "missing_documents": missing_docs,
            "active_work_package": active_wp["id"] if active_wp else None,
            "summary": summary,
            "tokens_estimate": tokens_estimate,
            "token_limit": token_limit,
            "generated_at": _now(),
        }


context_svc = ContextService()
