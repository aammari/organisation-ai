from pydantic import BaseModel
from typing import Optional
from datetime import datetime

class DecisionCreate(BaseModel):
    title: str
    decision_level: str
    actor: str
    rationale: Optional[str] = None

class Decision(BaseModel):
    id: str
    title: str
    decision_level: str
    status: str
    actor: str
    rationale: Optional[str] = None
    created_at: datetime
    decided_at: Optional[datetime] = None
