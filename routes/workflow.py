from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from core.workflow_engine import WorkflowEngine, WorkflowDeviationError

router = APIRouter(prefix="/workflow", tags=["workflow"])
engine = WorkflowEngine()

class TransitionRequest(BaseModel):
    project_id: str
    target: str
    reason: str

@router.post("/transition")
def transition(req: TransitionRequest):
    try:
        engine.transition_project(req.project_id, req.target, req.reason)
        return {"project_id": req.project_id, "new_state": req.target}
    except WorkflowDeviationError as e:
        raise HTTPException(422, str(e))
