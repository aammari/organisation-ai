from fastapi import FastAPI
from core.langgraph_app import workflow_app

app = FastAPI(title="Organisation AI", version="1.0.0")

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
