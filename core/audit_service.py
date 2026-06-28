from app.database import get_supabase
from config import AUDIT_LOG_ENABLED

class AuditService:
    def __init__(self):
        self.db = get_supabase()

    def log(
        self,
        actor: str,
        operation: str,
        object_id: str,
        previous_value: dict = None,
        new_value: dict = None,
        metadata: dict = None,
    ) -> None:
        if not AUDIT_LOG_ENABLED:
            return
        self.db.table("audit_log").insert({
            "actor": actor,
            "operation": operation,
            "object_id": object_id,
            "previous_value": previous_value,
            "new_value": new_value,
            "metadata": metadata or {},
        }).execute()

    def get_history(self, object_id: str) -> list:
        result = self.db.table("audit_log")\
            .select("*")\
            .eq("object_id", object_id)\
            .order("timestamp", desc=True)\
            .execute()
        return result.data
