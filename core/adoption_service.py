"""WP-M02 — Policy Adoption Service.

VALIDATED = document correct.
ADOPTED  = document officiellement applicable par l'organisation.

No LLM calls — purely deterministic (Budget Protection).
"""

import logging
import uuid
from datetime import datetime, timezone

from app.database import get_supabase
from core.doc_source import fetch_doc

logger = logging.getLogger(__name__)

# Docs that require CEO-level approval (D3) for adoption
_D3_DOCS: set[str] = {"P-01", "P-02", "P-03", "F-01", "F-02"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _doc_decision_level(doc_id: str) -> str:
    return "D3" if doc_id in _D3_DOCS else "D2"


class AdoptionService:
    def __init__(self):
        self.db = get_supabase()

    def _latest_validation(self, doc_id: str) -> dict | None:
        try:
            rows = (
                self.db.table("doc_validations")
                .select("document_id,status,doc_sha,version,commit_sha,validated_at")
                .eq("document_id", doc_id)
                .order("validated_at", desc=True)
                .limit(1)
                .execute()
            )
            return rows.data[0] if rows.data else None
        except Exception as e:
            logger.error(f"latest_validation {doc_id}: {e}")
            return None

    def _existing_adoption(self, doc_id: str) -> dict | None:
        try:
            rows = (
                self.db.table("adoption_registry")
                .select("*")
                .eq("doc_id", doc_id)
                .in_("status", ["ADOPTED", "ADOPTION_REQUESTED", "WAITING_CEO"])
                .order("created_at", desc=True)
                .limit(1)
                .execute()
            )
            return rows.data[0] if rows.data else None
        except Exception as e:
            logger.error(f"existing_adoption {doc_id}: {e}")
            return None

    async def request_adoption(
        self,
        doc_id: str,
        decision_level: str | None = None,
        requested_by: str = "ceo",
    ) -> dict:
        """
        Full adoption flow:
        1. Check doc exists on GitHub
        2. Check latest validation is RESOLVED
        3. Check SHA matches
        4. Create adoption record
        5. D3 → WAITING_CEO, else → ADOPTED
        """
        # ── 1. GitHub preflight ────────────────────────────────────────────
        fetched = await fetch_doc(doc_id)
        if fetched["status"] != "OK":
            return {
                "status": "REFUSED",
                "reason": "DOCUMENT_NOT_FOUND",
                "doc_id": doc_id,
                "detail": fetched.get("error", fetched["status"]),
            }

        current_sha = fetched["doc_sha"]
        current_version = fetched["version"]
        current_commit = fetched["commit_sha"]

        # ── 2. Validation check ────────────────────────────────────────────
        val = self._latest_validation(doc_id)
        if not val:
            return {
                "status": "REFUSED",
                "reason": "NO_VALIDATION",
                "doc_id": doc_id,
                "detail": "Document must be validated (RESOLVED) before adoption.",
            }
        if val["status"] != "RESOLVED":
            return {
                "status": "REFUSED",
                "reason": "NOT_RESOLVED",
                "doc_id": doc_id,
                "detail": f"Last validation status is {val['status']} — only RESOLVED documents can be adopted.",
            }

        # ── 3. SHA integrity check ─────────────────────────────────────────
        if val.get("doc_sha") and val["doc_sha"] != current_sha:
            return {
                "status": "REFUSED",
                "reason": "SHA_MISMATCH",
                "doc_id": doc_id,
                "detail": f"Document has changed since last validation (sha_val={val['doc_sha'][:12]}… sha_now={current_sha[:12]}…). Re-validate before adopting.",
            }

        # ── 4. Decision level ──────────────────────────────────────────────
        level = decision_level or _doc_decision_level(doc_id)

        # ── 5. Insert or update adoption record ───────────────────────────
        adoption_id = f"ADO-{doc_id}-{uuid.uuid4().hex[:8]}"
        adopted_status = "WAITING_CEO" if level == "D3" else "ADOPTED"
        adopted_at = _now() if adopted_status == "ADOPTED" else None

        # Deprecate any previous ADOPTED record for this doc
        try:
            self.db.table("adoption_registry").update(
                {"status": "DEPRECATED", "updated_at": _now()}
            ).eq("doc_id", doc_id).eq("status", "ADOPTED").execute()
        except Exception:
            pass

        record = {
            "id": adoption_id,
            "doc_id": doc_id,
            "version": current_version,
            "commit_sha": current_commit,
            "doc_sha": current_sha,
            "status": adopted_status,
            "adopted_at": adopted_at,
            "adopted_by": requested_by,
            "decision_level": level,
            "created_at": _now(),
            "updated_at": _now(),
        }
        try:
            self.db.table("adoption_registry").insert(record).execute()
        except Exception as e:
            logger.error(f"adoption insert {adoption_id}: {e}")
            return {"status": "ERROR", "doc_id": doc_id, "detail": str(e)}

        return {
            "status": adopted_status,
            "doc_id": doc_id,
            "adoption_id": adoption_id,
            "version": current_version,
            "doc_sha": current_sha[:16] + "…",
            "decision_level": level,
            "detail": (
                "En attente approbation CEO (D3)." if adopted_status == "WAITING_CEO"
                else f"{doc_id} v{current_version} officiellement adopté."
            ),
        }

    def list_adopted(self) -> list[dict]:
        try:
            rows = (
                self.db.table("adoption_registry")
                .select("doc_id,version,doc_sha,decision_level,adopted_at")
                .eq("status", "ADOPTED")
                .order("adopted_at", desc=True)
                .execute()
            )
            return rows.data or []
        except Exception as e:
            logger.error(f"list_adopted: {e}")
            return []

    def get_adoption(self, doc_id: str) -> dict | None:
        try:
            rows = (
                self.db.table("adoption_registry")
                .select("*")
                .eq("doc_id", doc_id)
                .not_.eq("status", "DEPRECATED")
                .order("created_at", desc=True)
                .limit(1)
                .execute()
            )
            return rows.data[0] if rows.data else None
        except Exception as e:
            logger.error(f"get_adoption {doc_id}: {e}")
            return None


adoption_svc = AdoptionService()
