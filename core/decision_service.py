from app.database import get_supabase
from core.identifiers import IdentifierService

class DecisionService:
    def __init__(self):
        self.db = get_supabase()
        self.ids = IdentifierService()

    def create(self, title: str, decision_level: str, actor: str, rationale: str) -> dict:
        dec_id = self.ids.generate("DEC")
        self.db.table("decisions").insert({
            "id": dec_id,
            "title": title,
            "decision_level": decision_level,
            "status": "PENDING",
            "actor": actor,
            "rationale": rationale,
        }).execute()
        return {"id": dec_id, "status": "PENDING"}

    def decide(self, dec_id: str) -> dict:
        self.db.table("decisions").update({
            "status": "DECIDED",
            "decided_at": "now()"
        }).eq("id", dec_id).execute()
        return {"id": dec_id, "status": "DECIDED"}

    def get(self, dec_id: str) -> dict:
        result = self.db.table("decisions").select("*").eq("id", dec_id).single().execute()
        return result.data

    def list(self) -> list:
        result = self.db.table("decisions").select("*").execute()
        return result.data
