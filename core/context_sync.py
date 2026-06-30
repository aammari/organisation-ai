from app.database import get_supabase
from datetime import datetime
import httpx
import base64
import os
import logging

logger = logging.getLogger(__name__)
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
GITHUB_REPO = "aammari/organisation-ai"


class OrgContextSync:
    def __init__(self):
        self.db = get_supabase()
        self._cache = None
        self._cache_time = None

    async def _fetch_github(self, path: str) -> str:
        try:
            async with httpx.AsyncClient() as c:
                r = await c.get(
                    f"https://api.github.com/repos/{GITHUB_REPO}/contents/{path}",
                    headers={"Authorization": f"token {GITHUB_TOKEN}"},
                )
                if r.status_code == 200:
                    return base64.b64decode(r.json()["content"]).decode("utf-8")[:800]
        except Exception:
            pass
        return ""

    async def refresh(self) -> dict:
        db = self.db
        try:
            project = (
                db.table("project_states")
                .select("*")
                .eq("id", "org-mvp-001")
                .single()
                .execute()
            )
            project_data = project.data or {}
        except Exception:
            project_data = {}

        try:
            backlog = (
                db.table("backlog_items")
                .select("id,title,priority,status")
                .in_("status", ["PENDING", "IN_PROGRESS"])
                .order("priority")
                .limit(10)
                .execute()
            )
            backlog_data = backlog.data or []
        except Exception:
            backlog_data = []

        try:
            decisions = (
                db.table("decisions")
                .select("id,title,decision_level")
                .order("created_at", desc=True)
                .limit(5)
                .execute()
            )
            decisions_data = decisions.data or []
        except Exception:
            decisions_data = []

        try:
            validations = (
                db.table("doc_validations")
                .select("document_id,status,remarks")
                .execute()
            )
            validations_data = {
                v["document_id"]: {
                    "status": v["status"],
                    "remarks_count": len(v["remarks"] or []),
                }
                for v in (validations.data or [])
            }
        except Exception:
            validations_data = {}

        ctx = {
            "id": "current",
            "version": "1.0",
            "project": project_data,
            "backlog": backlog_data,
            "decisions": decisions_data,
            "validations": validations_data,
            "agents": {
                "chief_architect": "claude-sonnet-4-6",
                "chief_analyst": "claude-haiku-4-5-20251001",
                "chief_of_staff": "claude-haiku-4-5-20251001",
            },
            "last_updated": datetime.now().isoformat(),
        }
        try:
            db.table("org_context").upsert(ctx).execute()
        except Exception:
            pass
        self._cache = None
        return ctx

    def get_formatted(self) -> str:
        now = datetime.now()
        if (
            self._cache
            and self._cache_time
            and (now - self._cache_time).seconds < 300
        ):
            return self._cache

        try:
            result = (
                self.db.table("org_context")
                .select("*")
                .eq("id", "current")
                .single()
                .execute()
            )
            ctx = result.data if result.data else {}
        except Exception:
            ctx = {}

        if not ctx:
            return ""

        backlog = "\n".join(
            [
                f"- {i['id']} [{i['priority']}] {i['title']}"
                for i in ctx.get("backlog", [])[:5]
            ]
        )
        agents = ctx.get("agents", {})
        validations = ctx.get("validations", {})
        val_lines = "\n".join(
            f"- {doc_id} : {v['status']} ({v['remarks_count']} remarques)"
            for doc_id, v in sorted(validations.items())
        )
        formatted = f"""
# CONTEXTE ORGANISATIONNEL
## Agents
- Chief of Staff : {agents.get('chief_of_staff')}
- Chief Architect : {agents.get('chief_architect')}
- Chief Analyst : {agents.get('chief_analyst')}

## Backlog actif
{backlog or 'Vide'}

## Validations documents
{val_lines or 'Aucune validation enregistrée'}

## Règles G-11
- Signer chaque message
- Traitement autonome
- Délai de retour obligatoire
- Autonomie maximale avant de solliciter CEO
"""
        self._cache = formatted
        self._cache_time = now
        return formatted


# Backward-compat shim used by langgraph_app before full migration
def load_backlog_context() -> str:
    return OrgContextSync().get_formatted()
