from fastapi import APIRouter
from core.audit_service import AuditService

router = APIRouter(prefix="/audit", tags=["audit"])
service = AuditService()

@router.get("/{object_id}")
def get_history(object_id: str):
    return service.get_history(object_id)
