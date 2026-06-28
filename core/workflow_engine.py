from app.database import get_supabase
import logging

logger = logging.getLogger(__name__)

PROJECT_TRANSITIONS = {
    "INITIATED": ["QUALIFYING"],
    "QUALIFYING": ["STUDYING", "DECIDING", "IMPLEMENTING"],
    "STUDYING": ["DECIDING"],
    "DECIDING": ["ARCHITECTING", "SUSPENDED"],
    "ARCHITECTING": ["IMPLEMENTING"],
    "IMPLEMENTING": ["VALIDATING"],
    "VALIDATING": ["DELIVERING", "STUDYING"],
    "DELIVERING": ["CLOSED"],
    "ANY": ["PENDING_CEO", "SUSPENDED"]
}

WP_TRANSITIONS = {
    "PROPOSED": ["ACTIVE"],
    "ACTIVE": ["IN_PROGRESS"],
    "IN_PROGRESS": ["REVIEW"],
    "REVIEW": ["DONE", "IN_PROGRESS", "PENDING_CEO"],
    "PENDING_CEO": ["RESUMED"],
    "RESUMED": ["REVIEW"],
    "ANY": ["CANCELLED"]
}

class WorkflowDeviationError(Exception):
    pass

class WorkflowEngine:
    def __init__(self):
        self.db = get_supabase()

    def can_transition(self, current: str, target: str, transitions: dict) -> bool:
        allowed = transitions.get(current, []) + transitions.get("ANY", [])
        return target in allowed

    def transition_project(self, project_id: str, target: str, reason: str) -> bool:
        result = self.db.table("project_states")\
            .select("current_state")\
            .eq("id", project_id)\
            .single()\
            .execute()
        current = result.data["current_state"]
        if not self.can_transition(current, target, PROJECT_TRANSITIONS):
            raise WorkflowDeviationError(
                f"Transition {current}→{target} non autorisée. "
                f"Dernier état valide : {current}"
            )
        self.db.table("project_states")\
            .update({
                "previous_state": current,
                "current_state": target,
                "transition_reason": reason,
                "updated_at": "now()"
            })\
            .eq("id", project_id)\
            .execute()
        logger.info(f"Project {project_id}: {current} → {target}")
        return True
