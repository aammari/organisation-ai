from fastapi import APIRouter, HTTPException
from models.decision import DecisionCreate
from core.decision_service import DecisionService

router = APIRouter(prefix="/decisions", tags=["decisions"])
service = DecisionService()

@router.post("/")
def create(body: DecisionCreate):
    return service.create(
        title=body.title,
        decision_level=body.decision_level,
        actor=body.actor,
        rationale=body.rationale,
    )

@router.post("/{dec_id}/decide")
def decide(dec_id: str):
    return service.decide(dec_id)

@router.get("/{dec_id}")
def get(dec_id: str):
    data = service.get(dec_id)
    if not data:
        raise HTTPException(404, "Décision non trouvée")
    return data

@router.get("/")
def list_all():
    return service.list()
