from app.database import get_supabase
from core.identifiers import IdentifierService

class DeviationService:
    def __init__(self):
        self.db = get_supabase()
        self.ids = IdentifierService()

    def report(
        self,
        severity: str,
        actor: str,
        workflow: str,
        state: str,
        violated_rules: list,
        affected_objects: list,
        context: dict = None,
    ) -> dict:
        er_id = self.ids.generate("ER")
        self.db.table("exception_reports").insert({
            "id": er_id,
            "severity": severity,
            "status": "OPEN",
            "actor": actor,
            "workflow": workflow,
            "state": state,
            "violated_rules": violated_rules,
            "affected_objects": affected_objects,
            "context": context or {},
        }).execute()
        return {"id": er_id, "severity": severity, "status": "OPEN"}

    def close(self, er_id: str) -> dict:
        self.db.table("exception_reports").update({
            "status": "CLOSED",
            "closed_at": "now()"
        }).eq("id", er_id).execute()
        return {"id": er_id, "status": "CLOSED"}

    def list_open(self) -> list:
        result = self.db.table("exception_reports").select("*").eq("status", "OPEN").execute()
        return result.data
