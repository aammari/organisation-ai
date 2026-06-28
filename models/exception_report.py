from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime

class ExceptionReportCreate(BaseModel):
    severity: str
    actor: str
    workflow: str
    state: str
    violated_rules: List[str]
    affected_objects: List[str]
    context: Optional[dict] = None

class ExceptionReport(BaseModel):
    id: str
    severity: str
    status: str
    actor: Optional[str] = None
    workflow: Optional[str] = None
    state: Optional[str] = None
    violated_rules: List[str]
    affected_objects: List[str]
    context: Optional[dict] = None
    created_at: datetime
    closed_at: Optional[datetime] = None
