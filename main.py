import asyncio
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from core.langgraph_app import workflow_app

logger = logging.getLogger(__name__)


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


@app.post("/cycle")
def run_cycle(request: dict):
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
    return {
        "intent": result["intent"],
        "analyst_decision": result["analyst_decision"],
        "response": result["final_response"]
    }
