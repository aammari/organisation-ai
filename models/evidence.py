from pydantic import BaseModel
from typing import Optional
from datetime import datetime

class EvidenceCreate(BaseModel):
    title: str
    description: Optional[str] = None
    source: Optional[str] = None
    author: str
    content: dict

class Evidence(BaseModel):
    id: str
    title: str
    description: Optional[str] = None
    source: Optional[str] = None
    author: str
    current_version: int
    status: str
    checksum: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None
