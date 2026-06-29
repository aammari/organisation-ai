from fastapi import APIRouter, Header, HTTPException
from app.config import API_SECRET
from app.services.supabase import get_supabase

router = APIRouter()

def verify_secret(x_api_secret: str):
    if x_api_secret != API_SECRET:
        raise HTTPException(status_code=401, detail="Unauthorized")

@router.get("/dashboard")
def dashboard(x_api_secret: str = Header(...)):
    verify_secret(x_api_secret)
    db = get_supabase()

    requests = db.table("executive_requests").select("id, title, status, priority, created_at").order("created_at", desc=True).limit(10).execute()
    pending = db.table("pending_ceo").select("*").eq("status", "pending").execute()
    agents = db.table("agents").select("name, role, status").execute()

    return {
        "recent_requests": requests.data,
        "pending_decisions": pending.data,
        "agents": agents.data
    }
