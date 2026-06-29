import asyncio
import json
import logging
import os
import subprocess
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, date, timezone

import anthropic
import httpx
from fastapi import FastAPI, HTTPException, Header
from pydantic import BaseModel
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from supabase import create_client

from config import (
    ANTHROPIC_API_KEY, CLAUDE_MODEL, GROQ_MODEL,
    SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY,
)
from core.langgraph_app import workflow_app
from core.cost_tracker import CostTracker
from core.context_sync import OrgContextSync

logger = logging.getLogger(__name__)

_last_cycle: dict | None = None

EXECUTE_SYSTEM = """Tu es un agent d'exécution technique.
Tu reçois une tâche et tu produis :
1. Le code Python ou bash à exécuter
2. Les fichiers à créer ou modifier
3. Les commandes Git si nécessaire

Réponds UNIQUEMENT en JSON valide :
{
  "files": [{"path": "...", "content": "..."}],
  "commands": ["..."],
  "explanation": "..."
}"""


def get_db():
    return create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)


def check_supabase() -> str:
    try:
        get_db().table("identifier_counters").select("prefix").limit(1).execute()
        return "online"
    except Exception as e:
        logger.warning(f"Supabase check failed: {e}")
        return "offline"


async def keepalive_loop():
    port = os.getenv("PORT", "10000")
    url = f"http://localhost:{port}/health"
    await asyncio.sleep(60)
    while True:
        try:
            import httpx
            async with httpx.AsyncClient() as client:
                await client.get(url, timeout=10)
            logger.info("Keep-alive ping OK")
        except Exception as e:
            logger.warning(f"Keep-alive ping failed: {e}")
        await asyncio.sleep(540)


@asynccontextmanager
async def lifespan(app: FastAPI):
    asyncio.create_task(keepalive_loop())
    yield


app = FastAPI(title="Organisation AI", version="1.0.0", lifespan=lifespan)


@app.get("/health")
def health():
    return {"status": "ok", "organization": "Organisation AI MVP"}


@app.get("/status")
def status():
    db = get_db()
    today = date.today().isoformat()
    month = today[:7]
    budget = 5.0

    try:
        last_er = (
            db.table("executive_requests")
            .select("*")
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        total = db.table("executive_requests").select("id", count="exact").execute()
        last_cycle_data = last_er.data[0] if last_er.data else _last_cycle
        cycles_total = total.count or 0
    except Exception:
        last_cycle_data = _last_cycle
        cycles_total = 0

    tracker = CostTracker()
    breakdown = tracker.get_daily_breakdown(today)
    daily_cost = sum(v["cost_usd"] for v in breakdown.values())
    monthly_cost = tracker.get_monthly_cost(month)

    budget_pct = (monthly_cost / budget) * 100
    cost_status = "OK" if budget_pct < 80 else "WARNING" if budget_pct < 100 else "CRITICAL"

    try:
        open_er = (
            db.table("exception_reports")
            .select("id", count="exact")
            .eq("status", "OPEN")
            .execute()
        )
        open_er_count = open_er.count or 0
    except Exception:
        open_er_count = 0

    return {
        "organization": "Organisation AI MVP",
        "phase": "IMPLEMENTING",
        "backend": "online",
        "supabase": check_supabase(),
        "cycles_total": cycles_total,
        "last_cycle": last_cycle_data,
        "agents": {
            "chief_architect": CLAUDE_MODEL,
            "chief_analyst": GROQ_MODEL,
        },
        "cost": {
            "today_usd": round(daily_cost, 4),
            "month_usd": round(monthly_cost, 4),
            "budget_usd": budget,
            "budget_pct": round(budget_pct, 1),
            "status": cost_status,
            "by_agent": {
                model: {
                    "cost_usd": round(data["cost_usd"], 4),
                    "input_tokens": data["input_tokens"],
                    "output_tokens": data["output_tokens"],
                    "cycles": data["cycles"],
                }
                for model, data in breakdown.items()
            },
        },
        "governance": {
            "open_exception_reports": open_er_count,
        },
    }


@app.post("/execute")
async def execute_task(request: dict):
    task = request.get("task", "")
    ai_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    response = ai_client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=4096,
        system=EXECUTE_SYSTEM,
        messages=[{"role": "user", "content": task}],
    )

    plan_text = response.content[0].text

    try:
        plan = json.loads(plan_text)
        executed = []

        for f in plan.get("files", []):
            dir_name = os.path.dirname(f["path"])
            if dir_name:
                os.makedirs(dir_name, exist_ok=True)
            with open(f["path"], "w") as fp:
                fp.write(f["content"])
            executed.append(f"Created: {f['path']}")

        for cmd in plan.get("commands", []):
            proc = subprocess.run(cmd, shell=True, capture_output=True, text=True)
            output = proc.stdout.strip() or proc.stderr.strip()
            executed.append(f"Ran: {cmd} → {output[:200]}")

        return {
            "status": "executed",
            "explanation": plan.get("explanation"),
            "actions": executed,
        }
    except json.JSONDecodeError:
        return {"status": "error", "error": "JSON parse failed", "raw": plan_text[:500]}
    except Exception as e:
        return {"status": "error", "error": str(e)}


@app.post("/cycle")
def run_cycle(request: dict):
    global _last_cycle
    result = workflow_app.invoke({
        "ceo_request": request.get("message", ""),
        "intent": None,
        "priority": None,
        "workflow_state": "IMPLEMENTING",
        "architect_output": None,
        "analyst_decision": None,
        "deviation": None,
        "execution_result": None,
        "final_response": None,
    })
    _last_cycle = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "intent": result["intent"],
        "analyst_decision": result["analyst_decision"],
    }
    return {
        "intent": result["intent"],
        "analyst_decision": result["analyst_decision"],
        "response": result["final_response"],
    }


class BacklogItemIn(BaseModel):
    id: str
    title: str
    description: str = ""
    priority: str = "P2"
    decision_level: str = "D1"
    assigned_agent: str = ""


@app.post("/backlog/add")
async def backlog_add(
    item: BacklogItemIn,
    x_agent_role: str = Header(default=""),
):
    if x_agent_role.lower() != "chief-of-staff":
        raise HTTPException(status_code=403, detail="Reserved for Chief of Staff")
    db = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)
    row = {
        "id": item.id,
        "title": item.title,
        "description": item.description,
        "priority": item.priority,
        "status": "PENDING",
        "decision_level": item.decision_level,
        "assigned_agent": item.assigned_agent or None,
    }
    db.table("backlog_items").upsert(row).execute()
    return {"status": "created", "id": item.id}


TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")


async def _tg(text: str):
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            await c.post(
                f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                json={"chat_id": TELEGRAM_CHAT_ID, "text": text},
            )
    except Exception:
        pass


class ThreadStartIn(BaseModel):
    title: str
    wp_id: str = ""
    subject: str


@app.post("/thread/start")
async def thread_start(body: ThreadStartIn):
    import openai as _openai
    db = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)

    thread_id = f"THR-{uuid.uuid4().hex[:8].upper()}"
    db.table("agent_threads").insert({
        "id": thread_id,
        "title": body.title,
        "wp_id": body.wp_id or None,
        "status": "OPEN",
    }).execute()

    await _tg(f"Thread {thread_id} ouvert\n{body.title}")

    architect_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    analyst_client = _openai.OpenAI(
        api_key=GROQ_API_KEY,
        base_url="https://api.groq.com/openai/v1",
    )

    history = [{"role": "user", "content": body.subject}]
    resolved = False

    for turn in range(1, 4):
        # Chief Architect produces ACP
        arch_resp = architect_client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=2048,
            system=(
                "Tu es Chief Architect. Produis un ACP (Architect Contribution Proposal) "
                "clair et structuré sur le sujet donné. Sois concis."
            ),
            messages=history,
        )
        try:
            CostTracker().log_cycle(
                input_tokens=arch_resp.usage.input_tokens,
                output_tokens=arch_resp.usage.output_tokens,
                model=CLAUDE_MODEL,
            )
        except Exception:
            pass
        acp = arch_resp.content[0].text
        msg_id = f"{thread_id}-T{turn}-ARCH"
        db.table("agent_messages").insert({
            "id": msg_id,
            "thread_id": thread_id,
            "sender": "chief-architect",
            "content": acp,
            "status": "PENDING",
            "turn": turn,
        }).execute()
        await _tg(f"Tour {turn}/3 — Chief Architect\n{thread_id}\n\n{acp[:300]}...")
        history.append({"role": "assistant", "content": acp})

        # Chief Analyst validates or objects
        analyst_resp = analyst_client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Tu es Chief Analyst. Réponds VALIDATED si l'ACP est acceptable, "
                        "OBJECTION suivi de tes remarques sinon. Sois bref."
                    ),
                },
                {"role": "user", "content": acp},
            ],
        )
        verdict = analyst_resp.choices[0].message.content
        verdict_id = f"{thread_id}-T{turn}-ANAL"
        verdict_status = "VALIDATED" if verdict.strip().upper().startswith("VALIDATED") else "OBJECTION"
        db.table("agent_messages").insert({
            "id": verdict_id,
            "thread_id": thread_id,
            "sender": "chief-analyst",
            "content": verdict,
            "status": verdict_status,
            "turn": turn,
        }).execute()
        await _tg(f"Tour {turn}/3 — Chief Analyst\n{verdict_status}\n\n{verdict[:300]}")

        if verdict_status == "VALIDATED":
            db.table("agent_threads").update({"status": "RESOLVED", "updated_at": datetime.now(timezone.utc).isoformat()}).eq("id", thread_id).execute()
            await _tg(f"Thread {thread_id} RESOLU au tour {turn}")
            resolved = True
            break

        history.append({"role": "user", "content": f"OBJECTION du Chief Analyst : {verdict}"})

    if not resolved:
        db.table("agent_threads").update({"status": "ESCALATED", "updated_at": datetime.now(timezone.utc).isoformat()}).eq("id", thread_id).execute()
        await _tg(f"Thread {thread_id} ESCALADE CEO — 3 tours sans consensus.")

    messages = db.table("agent_messages").select("*").eq("thread_id", thread_id).order("turn").execute()
    return {"thread_id": thread_id, "status": "RESOLVED" if resolved else "ESCALATED", "messages": messages.data}


@app.get("/thread/{thread_id}")
async def thread_get(thread_id: str):
    db = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)
    thread = db.table("agent_threads").select("*").eq("id", thread_id).single().execute()
    if not thread.data:
        raise HTTPException(status_code=404, detail="Thread not found")
    messages = db.table("agent_messages").select("*").eq("thread_id", thread_id).order("turn").execute()
    return {"thread": thread.data, "messages": messages.data}


@app.get("/context")
async def get_context():
    return {"context": OrgContextSync().get_formatted()}


@app.post("/context/refresh")
async def refresh_context():
    ctx = await OrgContextSync().refresh()
    return {"status": "refreshed", "last_updated": ctx.get("last_updated")}


# Dashboard CEO — served at root
app.mount("/static", StaticFiles(directory="dashboard"), name="static")


@app.get("/")
def root():
    return FileResponse("dashboard/index.html")
