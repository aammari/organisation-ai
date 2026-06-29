from app.database import get_supabase
from core.identifiers import IdentifierService
import hashlib
import json

class EvidenceService:
    def __init__(self):
        self.db = get_supabase()
        self.ids = IdentifierService()

    def create(self, title: str, description: str, source: str, author: str, content: dict) -> dict:
        evid_id = self.ids.generate("EVID")
        checksum = hashlib.sha256(json.dumps(content, sort_keys=True).encode()).hexdigest()
        self.db.table("evidence").insert({
            "id": evid_id,
            "title": title,
            "description": description,
            "source": source,
            "author": author,
            "current_version": 1,
            "status": "ACTIVE",
            "checksum": checksum,
        }).execute()
        self.db.table("evidence_versions").insert({
            "evidence_id": evid_id,
            "version": 1,
            "content": content,
            "checksum": checksum,
            "created_by": author,
        }).execute()
        return {"id": evid_id, "version": 1}

    def get(self, evid_id: str) -> dict:
        result = self.db.table("evidence").select("*").eq("id", evid_id).single().execute()
        return result.data

    def list(self) -> list:
        result = self.db.table("evidence").select("*").execute()
        return result.data
