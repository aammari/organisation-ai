from pydantic import BaseModel
from typing import Optional
from datetime import datetime

class WorkPackageCreate(BaseModel):
    er_id: Optional[str] = None
    title: str
    owner_agent_id: Optional[str] = None
    context_snapshot: Optional[dict] = None

class WorkPackage(BaseModel):
    id: str
    er_id: Optional[str] = None
    title: str
    status: str
    owner_agent_id: Optional[str] = None
    context_snapshot: Optional[dict] = None
    created_at: datetime
    updated_at: Optional[datetime] = None
