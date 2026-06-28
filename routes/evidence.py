from fastapi import APIRouter, HTTPException
from models.evidence import EvidenceCreate
from core.evidence_service import EvidenceService

router = APIRouter(prefix="/evidence", tags=["evidence"])
service = EvidenceService()

@router.post("/")
def create(body: EvidenceCreate):
    return service.create(
        title=body.title,
        description=body.description,
        source=body.source,
        author=body.author,
        content=body.content,
    )

@router.get("/{evid_id}")
def get(evid_id: str):
    data = service.get(evid_id)
    if not data:
        raise HTTPException(404, "Evidence non trouvée")
    return data

@router.get("/")
def list_all():
    return service.list()
