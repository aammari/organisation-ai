from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel
from typing import Optional
from app.config import API_SECRET
from app.services.supabase import get_supabase
from app.services.claude import orchestrate

router = APIRouter()

class ExecutiveRequest(BaseModel):
    title: str
    intention: str
    priority: Optional[str] = "medium"
    context: Optional[dict] = {}

def verify_secret(x_api_secret: str = Header(...)):
    if x_api_secret != API_SECRET:
        raise HTTPException(status_code=401, detail="Unauthorized")

@router.post("/request")
def create_executive_request(payload: ExecutiveRequest, x_api_secret: str = Header(...)):
    verify_secret(x_api_secret)
    db = get_supabase()

    er = db.table("executive_requests").insert({
        "title": payload.title,
        "intention": payload.intention,
        "priority": payload.priority,
        "status": "analyzing",
        "context": payload.context
    }).execute()

    er_id = er.data[0]["id"]

    plan = orchestrate(payload.intention, payload.context)

    wp_ids = []
    for wp in plan.get("work_packages", []):
        agent_name = wp.get("assigned_to", "claude")
        agent = db.table("agents").select("id").eq("name", agent_name).execute()
        agent_id = agent.data[0]["id"] if agent.data else None

        inserted = db.table("work_packages").insert({
            "executive_request_id": er_id,
            "title": wp["title"],
            "description": wp.get("description"),
            "assigned_to": agent_id,
            "priority": wp.get("priority", "medium"),
            "deliverable": wp.get("deliverable"),
            "status": "pending"
        }).execute()
        wp_ids.append(inserted.data[0]["id"])

    pending_id = None
    if plan.get("requires_ceo_decision") and plan.get("ceo_decision"):
        d = plan["ceo_decision"]
        agent = db.table("agents").select("id").eq("name", "claude").execute()
        claude_id = agent.data[0]["id"]

        pending = db.table("pending_ceo").insert({
            "executive_request_id": er_id,
            "raised_by": claude_id,
            "decision_level": d["level"],
            "question": d["question"],
            "options": d.get("options"),
            "recommendation": d.get("recommendation"),
            "urgency": "high",
            "status": "pending"
        }).execute()
        pending_id = pending.data[0]["id"]

        db.table("executive_requests").update({"status": "pending_ceo"}).eq("id", er_id).execute()
    else:
        db.table("executive_requests").update({"status": "in_progress"}).eq("id", er_id).execute()

    db.table("project_states").insert({
        "executive_request_id": er_id,
        "state_key": "pending_ceo" if pending_id else "in_progress",
        "state_data": plan,
        "is_current": True
    }).execute()

    return {
        "executive_request_id": er_id,
        "status": "pending_ceo" if pending_id else "in_progress",
        "analysis": plan.get("analysis"),
        "work_packages_created": len(wp_ids),
        "requires_ceo_decision": plan.get("requires_ceo_decision", False),
        "pending_ceo_id": pending_id
    }


@router.get("/request/{er_id}")
def get_executive_request(er_id: str, x_api_secret: str = Header(...)):
    verify_secret(x_api_secret)
    db = get_supabase()

    er = db.table("executive_requests").select("*").eq("id", er_id).execute()
    if not er.data:
        raise HTTPException(status_code=404, detail="Executive Request not found")

    wps = db.table("work_packages").select("*").eq("executive_request_id", er_id).execute()
    pending = db.table("pending_ceo").select("*").eq("executive_request_id", er_id).eq("status", "pending").execute()

    return {
        "executive_request": er.data[0],
        "work_packages": wps.data,
        "pending_decisions": pending.data
    }


@router.post("/decide/{pending_id}")
def ceo_decision(pending_id: str, body: dict, x_api_secret: str = Header(...)):
    verify_secret(x_api_secret)
    db = get_supabase()

    from datetime import datetime, timezone
    db.table("pending_ceo").update({
        "status": "responded",
        "ceo_response": body.get("response"),
        "ceo_choice": body.get("choice"),
        "responded_at": datetime.now(timezone.utc).isoformat()
    }).eq("id", pending_id).execute()

    pending = db.table("pending_ceo").select("executive_request_id").eq("id", pending_id).execute()
    er_id = pending.data[0]["executive_request_id"]
    db.table("executive_requests").update({"status": "in_progress"}).eq("id", er_id).execute()

    return {"status": "decision_recorded", "executive_request_id": er_id}
