import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from fastapi import FastAPI
from supabase import create_client
from config import SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY, CLAUDE_MODEL, GROQ_MODEL
from core.langgraph_app import workflow_app

logger = logging.getLogger(__name__)

_last_cycle: dict | None = None


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
    import httpx
    import os
    port = os.getenv("PORT", "10000")
    url = f"http://localhost:{port}/health"
    await asyncio.sleep(60)
    while True:
        try:
            async with httpx.AsyncClient() as client:
                await client.get(url, timeout=10)
            logger.info("Keep-alive ping OK")
        except Exception as e:
            logger.warning(f"Keep-alive ping failed: {e}")
        await asyncio.sleep(540)  # 9 minutes


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
    return {
        "organization": "Organisation AI MVP",
        "phase": "IMPLEMENTING",
        "backend": "online",
        "supabase": check_supabase(),
        "last_cycle": get_last_cycle(),
        "agents": {
            "chief_architect": CLAUDE_MODEL,
            "chief_analyst": GROQ_MODEL,
        }
    }


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
        "final_response": None
    })
    _last_cycle = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "intent": result["intent"],
        "analyst_decision": result["analyst_decision"],
    }
    return {
        "intent": result["intent"],
        "analyst_decision": result["analyst_decision"],
        "response": result["final_response"]
    }
