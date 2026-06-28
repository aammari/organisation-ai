from pydantic import BaseModel
from typing import Optional
from datetime import datetime

class AuditEvent(BaseModel):
    id: int
    timestamp: datetime
    actor: str
    operation: str
    object_id: str
    previous_value: Optional[dict] = None
    new_value: Optional[dict] = None
    metadata: Optional[dict] = None
