import asyncio
import json
import logging
import os
import subprocess
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import anthropic
from fastapi import FastAPI
from supabase import create_client

from config import (
    ANTHROPIC_API_KEY, CLAUDE_MODEL, GROQ_MODEL,
    SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY,
)
from core.langgraph_app import workflow_app

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


def check_supabase() -> str:
    try:
        client = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)
        client.table("identifier_counters").select("prefix").limit(1).execute()
        return "online"
    except Exception as e:
        logger.warning(f"Supabase check failed: {e}")
        return "offline"


def get_last_cycle() -> dict | None:
    return _last_cycle


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
    db = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)
    try:
        last_er = (
            db.table("executive_requests")
            .select("*")
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        total = (
            db.table("executive_requests")
            .select("id", count="exact")
            .execute()
        )
        last_cycle_data = last_er.data[0] if last_er.data else get_last_cycle()
        cycles_total = total.count or 0
    except Exception:
        last_cycle_data = get_last_cycle()
        cycles_total = 0

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
            proc = subprocess.run(
                cmd, shell=True, capture_output=True, text=True
            )
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
