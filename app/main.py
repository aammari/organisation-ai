from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.routers import executive, status

app = FastAPI(
    title="Organisation AI - Backend",
    description="Multi-agent orchestration system",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(executive.router, prefix="/executive", tags=["Executive"])
app.include_router(status.router, prefix="/status", tags=["Status"])

@app.get("/")
def root():
    return {"status": "ok", "system": "Organisation AI"}
