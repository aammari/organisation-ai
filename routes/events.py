from fastapi import APIRouter
from app.database import get_supabase

router = APIRouter(prefix="/events", tags=["events"])

@router.get("/")
def list_events(status: str = "PUBLISHED", limit: int = 50):
    db = get_supabase()
    result = db.table("events")\
        .select("*")\
        .eq("status", status)\
        .order("timestamp", desc=True)\
        .limit(limit)\
        .execute()
    return result.data

@router.post("/{event_id}/consume")
def consume(event_id: str):
    db = get_supabase()
    db.table("events").update({
        "status": "CONSUMED",
        "consumed_at": "now()"
    }).eq("id", event_id).execute()
    return {"id": event_id, "status": "CONSUMED"}
