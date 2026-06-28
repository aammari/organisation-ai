from fastapi import APIRouter, HTTPException
from core.identifiers import IdentifierService, VALID_PREFIXES

router = APIRouter(prefix="/identifiers", tags=["identifiers"])
service = IdentifierService()

@router.post("/generate/{prefix}")
def generate(prefix: str):
    if prefix not in VALID_PREFIXES:
        raise HTTPException(400, f"Prefix invalide. Valides: {VALID_PREFIXES}")
    return {"id": service.generate(prefix)}

@router.get("/validate/{identifier}")
def validate(identifier: str):
    return {"identifier": identifier, "valid": service.validate(identifier)}
