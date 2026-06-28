from pydantic import BaseModel
from typing import Optional
from datetime import datetime

class ExecutiveRequestCreate(BaseModel):
    raw_input: str
    qualified_intent: Optional[str] = None
    type: Optional[str] = None
    priority: str = "P2"

class ExecutiveRequest(BaseModel):
    id: str
    raw_input: str
    qualified_intent: Optional[str] = None
    type: Optional[str] = None
    priority: str
    status: str
    created_at: datetime
    updated_at: Optional[datetime] = None
