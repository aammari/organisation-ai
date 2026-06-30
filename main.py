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
from fastapi import BackgroundTasks, FastAPI, HTTPException, Header
from pydantic import BaseModel
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from supabase import create_client

from config import (
    ANTHROPIC_API_KEY, CLAUDE_MODEL,
    SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY,
)
from core.langgraph_app import workflow_app, get_model_for_task
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
            "chief_analyst": "claude-haiku-4-5-20251001",
        },
        "model_routing": {
            task: get_model_for_task(task)
            for task in [
                "cycle_analyse", "cycle_production", "cycle_action",
                "thread_turn_1", "thread_turn_2", "thread_turn_3",
                "validate", "qualify_intent", "ceo_intervention",
            ]
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
        "model_used": result.get("workflow_state", "cycle_production"),
    }
    return {
        "intent": result["intent"],
        "analyst_decision": result["analyst_decision"],
        "model_used": result.get("workflow_state", "cycle_production"),
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


async def _tg(text: str):
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            await c.post(
                f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                json={"chat_id": TELEGRAM_CHAT_ID, "text": text},
            )
    except Exception:
        pass


async def notify_turn(turn: int, sender: str, content: str):
    short = content[:300]
    await _tg(
        f"Thread en cours — Tour {turn}\n\n"
        f"{sender} :\n{short}..."
    )


async def _tg_reply(chat_id: int, reply_to: int, text: str):
    if not chat_id or not reply_to:
        return
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            await c.post(
                f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                json={"chat_id": chat_id, "reply_to_message_id": reply_to, "text": text},
            )
    except Exception:
        pass


class ThreadStartIn(BaseModel):
    title: str
    wp_id: str = ""
    subject: str
    telegram_chat_id: int = 0
    telegram_thread_msg_id: int = 0


class ThreadInterveneIn(BaseModel):
    telegram_thread_msg_id: int
    text: str


@app.post("/thread/intervene")
async def thread_intervene(body: ThreadInterveneIn):
    db = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)
    result = db.table("agent_threads") \
        .update({"ceo_input": body.text}) \
        .eq("telegram_thread_msg_id", body.telegram_thread_msg_id) \
        .in_("status", ["OPEN"]) \
        .execute()
    updated = len(result.data) if result.data else 0
    return {"updated": updated}


async def _run_thread(
    title: str,
    wp_id: str,
    subject: str,
    tg_chat_id: int = 0,
    tg_msg_id: int = 0,
) -> dict:
    db = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)
    thread_id = f"THR-{uuid.uuid4().hex[:8].upper()}"
    db.table("agent_threads").insert({
        "id": thread_id,
        "title": title,
        "wp_id": wp_id or None,
        "status": "OPEN",
        "telegram_chat_id": tg_chat_id or None,
        "telegram_thread_msg_id": tg_msg_id or None,
    }).execute()

    await _tg(f"Thread {thread_id} ouvert\n{title}")

    anthropic_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    history = [{"role": "user", "content": subject}]
    resolved = False
    ceo_stopped = False

    for turn in range(1, 4):
        try:
            row = db.table("agent_threads").select("ceo_input").eq("id", thread_id).single().execute()
            ceo_input = (row.data or {}).get("ceo_input")
        except Exception:
            ceo_input = None

        if ceo_input:
            ceo_lower = ceo_input.strip().lower()
            if ceo_lower in ("stop", "stoppe", "arrête", "arrete"):
                db.table("agent_threads").update({
                    "status": "CEO_STOPPED", "updated_at": datetime.now(timezone.utc).isoformat()
                }).eq("id", thread_id).execute()
                await _tg_reply(tg_chat_id, tg_msg_id, "CEO_STOPPED — discussion arrêtée par le CEO.")
                ceo_stopped = True
                break
            elif ceo_lower in ("valide", "validé", "ok", "approved"):
                db.table("agent_threads").update({
                    "status": "CEO_VALIDATED", "updated_at": datetime.now(timezone.utc).isoformat()
                }).eq("id", thread_id).execute()
                await _tg_reply(tg_chat_id, tg_msg_id, "CEO_VALIDATED — discussion validée par le CEO.")
                resolved = True
                break
            else:
                await _tg_reply(tg_chat_id, tg_msg_id, f"CEO intervient : {ceo_input}")
                subject = subject + f"\n\nCEO : {ceo_input}"
                history.append({"role": "user", "content": f"Instruction CEO : {ceo_input}"})
                db.table("agent_threads").update({"ceo_input": None}).eq("id", thread_id).execute()

        arch_task = "thread_turn_1" if turn == 1 else f"thread_turn_{turn}"
        arch_model = get_model_for_task(arch_task)
        arch_resp = await asyncio.to_thread(
            anthropic_client.messages.create,
            model=arch_model,
            max_tokens=2048 if arch_model == CLAUDE_MODEL else 1024,
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
                model=arch_model,
            )
        except Exception:
            pass
        acp = arch_resp.content[0].text
        db.table("agent_messages").insert({
            "id": f"{thread_id}-T{turn}-ARCH",
            "thread_id": thread_id,
            "sender": "chief-architect",
            "content": acp,
            "status": "PENDING",
            "turn": turn,
        }).execute()
        await notify_turn(turn, "Chief Architect", acp)
        await _tg_reply(tg_chat_id, tg_msg_id, f"[Tour {turn}] Chief Architect\n\n{acp[:500]}")
        history.append({"role": "assistant", "content": acp})

        try:
            analyst_resp = await asyncio.to_thread(
                anthropic_client.messages.create,
                model=get_model_for_task("validate"),
                max_tokens=512,
                system=(
                    "Tu es Chief Analyst. Réponds VALIDATED si l'ACP est acceptable, "
                    "OBJECTION suivi de tes remarques sinon. Sois bref."
                ),
                messages=[{"role": "user", "content": acp}],
            )
            verdict = analyst_resp.content[0].text
            verdict_status = "VALIDATED" if "VALIDATED" in verdict.upper()[:40] else "OBJECTION"
        except Exception as err:
            verdict = f"ANALYST_UNAVAILABLE — {str(err)[:200]}"
            verdict_status = "ESCALATED"
            db.table("agent_messages").insert({
                "id": f"{thread_id}-T{turn}-ANAL",
                "thread_id": thread_id,
                "sender": "chief-analyst",
                "content": verdict,
                "status": verdict_status,
                "turn": turn,
            }).execute()
            await notify_turn(turn, "Chief Analyst (indisponible)", verdict)
            await _tg_reply(tg_chat_id, tg_msg_id, f"[Tour {turn}] Chief Analyst indisponible\n\n{verdict[:500]}")
            break

        db.table("agent_messages").insert({
            "id": f"{thread_id}-T{turn}-ANAL",
            "thread_id": thread_id,
            "sender": "chief-analyst",
            "content": verdict,
            "status": verdict_status,
            "turn": turn,
        }).execute()
        await notify_turn(turn, f"Chief Analyst [{verdict_status}]", verdict)
        await _tg_reply(tg_chat_id, tg_msg_id, f"[Tour {turn}] Chief Analyst [{verdict_status}]\n\n{verdict[:500]}")

        if verdict_status == "VALIDATED":
            db.table("agent_threads").update({"status": "RESOLVED", "updated_at": datetime.now(timezone.utc).isoformat()}).eq("id", thread_id).execute()
            await _tg(f"Discussion {thread_id} RESOLVED — consensus atteint au tour {turn}")
            await _tg_reply(tg_chat_id, tg_msg_id, f"RESOLVED — consensus atteint au tour {turn}")
            resolved = True
            break

        history.append({"role": "user", "content": f"OBJECTION du Chief Analyst : {verdict}"})

    if not resolved and not ceo_stopped:
        db.table("agent_threads").update({"status": "ESCALATED", "updated_at": datetime.now(timezone.utc).isoformat()}).eq("id", thread_id).execute()
        await _tg(f"Discussion {thread_id} ESCALATED — 3 tours sans consensus. Decision CEO requise.")
        await _tg_reply(tg_chat_id, tg_msg_id, "ESCALATED — 3 tours sans consensus. Decision CEO requise.")

    thread_row = db.table("agent_threads").select("status").eq("id", thread_id).single().execute()
    final_status = (thread_row.data or {}).get("status", "ESCALATED")
    messages = db.table("agent_messages").select("*").eq("thread_id", thread_id).order("turn").execute()
    return {"thread_id": thread_id, "status": final_status, "messages": messages.data}


@app.post("/thread/start")
async def thread_start(body: ThreadStartIn):
    return await _run_thread(
        title=body.title,
        wp_id=body.wp_id,
        subject=body.subject,
        tg_chat_id=body.telegram_chat_id,
        tg_msg_id=body.telegram_thread_msg_id,
    )


async def _validate_single_doc(doc_id: str, content: str) -> dict:
    db = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)
    thread = await _run_thread(
        title=f"Validation {doc_id}",
        wp_id="WP-Sprint2-001",
        subject=(
            f"Valide le document {doc_id}.\n"
            "Analyse chaque section. Note les points forts et les remarques.\n\n"
            f"CONTENU :\n{content[:3000]}"
        ),
    )
    remarks = [
        {
            "tour": msg["turn"],
            "decision": "VALIDATED" if "VALIDATED" in msg["content"].upper()[:40] else "OBJECTION",
            "content": msg["content"][:500],
        }
        for msg in thread.get("messages", [])
        if msg["sender"] == "chief-analyst"
    ]
    val_id = f"VAL-{doc_id}-{thread['thread_id']}"
    db.table("doc_validations").insert({
        "id": val_id,
        "document_id": doc_id,
        "thread_id": thread["thread_id"],
        "status": thread["status"],
        "remarks": remarks,
        "validated_at": datetime.now(timezone.utc).isoformat(),
    }).execute()
    result = {"doc_id": doc_id, "thread_id": thread["thread_id"], "status": thread["status"], "remarks": remarks}

    if thread["status"] == "ESCALATED":
        await _handle_escalation(doc_id, thread["thread_id"], remarks)

    return result


async def _handle_escalation(doc_id: str, thread_id: str, remarks: list) -> str:
    """Insert pending_escalations + notify CEO. Returns objections_text."""
    db = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)
    objections = [r for r in remarks if r.get("decision") == "OBJECTION"]
    points = "\n".join(
        f"• Tour {r['tour']} : {r['content'][:150]}..."
        for r in objections
    )
    objections_text = points or f"Voir thread {thread_id}"
    esc_id = f"ESC-{doc_id}-{thread_id}"
    try:
        db.table("pending_escalations").insert({
            "id": esc_id,
            "doc_id": doc_id,
            "thread_id": thread_id,
            "status": "WAITING_CEO",
            "objections": objections_text,
        }).execute()
    except Exception as e:
        logger.error(f"pending_escalations insert {esc_id}: {e}")
    await _tg(
        f"ESCALADE — {doc_id}\n\n"
        f"Les agents n'ont pas atteint consensus.\n\n"
        f"Points bloquants :\n{objections_text}\n\n"
        f"Action requise :\n"
        f"A — Corriger le document\n"
        f"B — Valider en l'état (dérogation CEO)"
    )
    return objections_text


async def _run_correction(esc: dict):
    doc_id = esc["doc_id"]
    objections_text = esc.get("objections", "")
    await _tg(f"Correction lancée pour {doc_id}\nLes agents produisent v1.1...")
    await _run_thread(
        title=f"Correction {doc_id} v1.1",
        wp_id="WP-Sprint2-001",
        subject=(
            f"Produis une version corrigée de {doc_id}.\n"
            f"Points à corriger identifiés lors de la validation précédente :\n"
            f"{objections_text}\n\n"
            f"Produis le document corrigé complet."
        ),
    )


@app.post("/escalation/respond")
async def escalation_respond(request: dict, background_tasks: BackgroundTasks):
    response = request.get("response", "").strip().upper()
    target_doc_id = request.get("doc_id")  # optional — None means FIFO
    if response not in ("A", "B"):
        raise HTTPException(status_code=422, detail="response must be A or B")

    db = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)
    pending = (
        db.table("pending_escalations")
        .select("*")
        .eq("status", "WAITING_CEO")
        .order("created_at", desc=False)  # oldest first → FIFO
        .execute()
    )
    if not pending.data:
        return {"handled": False, "message": "Aucune escalade en attente"}

    if len(pending.data) == 1:
        esc = pending.data[0]
    elif target_doc_id:
        esc = next((e for e in pending.data if e["doc_id"] == target_doc_id), pending.data[0])
    else:
        esc = pending.data[0]  # FIFO: oldest waiting

    doc_id = esc["doc_id"]
    remaining = len(pending.data) - 1

    db.table("pending_escalations").update({
        "status": "RESOLVED",
        "ceo_response": response,
    }).eq("id", esc["id"]).execute()

    if response == "A":
        background_tasks.add_task(_run_correction, esc)
    else:
        db.table("doc_validations").update({"status": "CEO_VALIDATED"}).eq("document_id", doc_id).execute()
        await _tg(f"Dérogation appliquée — {doc_id}\nValidé en l'état par CEO.")

    if remaining > 0:
        next_docs = [e["doc_id"] for e in pending.data if e["doc_id"] != doc_id]
        await _tg(
            f"{remaining} escalade(s) encore en attente : {', '.join(next_docs)}\n"
            f"Réponds A/B ou 'A {next_docs[0]}' pour cibler un document précis."
        )

    return {"handled": True, "doc_id": doc_id, "response": response, "remaining": remaining}


@app.get("/escalation/pending")
async def escalation_pending():
    db = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)
    result = (
        db.table("pending_escalations")
        .select("id,doc_id,thread_id,status,created_at")
        .eq("status", "WAITING_CEO")
        .order("created_at", desc=True)
        .execute()
    )
    return {"pending": result.data or [], "count": len(result.data or [])}


@app.post("/validate/doc")
async def validate_doc(request: dict):
    doc_id = request.get("doc_id", "")
    content = request.get("content", "")
    if not doc_id or not content:
        raise HTTPException(status_code=422, detail="doc_id and content are required")
    return await _validate_single_doc(doc_id, content)


@app.get("/validate/status")
async def validate_status():
    db = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)
    result = db.table("doc_validations").select("*").order("validated_at", desc=True).execute()
    rows = result.data or []
    return {
        "total": len(rows),
        "resolved": len([r for r in rows if r["status"] == "RESOLVED"]),
        "escalated": len([r for r in rows if r["status"] == "ESCALATED"]),
        "documents": rows,
    }


async def _run_batch_validation(docs: list):
    for doc in docs:
        doc_id = doc["id"]
        # Isolation totale : une exception sur un doc ne bloque pas les suivants
        try:
            result = await _validate_single_doc(doc_id, doc["content"])
        except Exception as e:
            logger.error(f"batch validate {doc_id}: {e}")
            result = {"status": "ERROR", "error": str(e), "remarks": [], "thread_id": ""}

        status = result.get("status", "ERROR")
        if status == "ESCALATED":
            try:
                await _handle_escalation(doc_id, result["thread_id"], result["remarks"])
            except Exception as e:
                logger.error(f"_handle_escalation {doc_id}: {e}")
                await _tg(
                    f"ESCALADE — {doc_id} (notification dégradée)\n"
                    f"Erreur : {str(e)[:100]}\n"
                    f"Vérifie /validate/status manuellement."
                )
        else:
            icon = "OK" if status == "RESOLVED" else "ERREUR"
            await _tg(f"{icon} — {doc_id} : {status}")

        await asyncio.sleep(20)
    await _tg(f"Batch validation terminé — {len(docs)} documents traités.")


@app.post("/validate/batch")
async def validate_batch(request: dict, background_tasks: BackgroundTasks):
    docs = request.get("documents", [])
    if not docs:
        raise HTTPException(status_code=422, detail="documents list is required")
    background_tasks.add_task(_run_batch_validation, docs)
    await _tg(f"Batch validation démarré — {len(docs)} documents en file.")
    return {"queued": len(docs), "message": "Validation lancée en arrière-plan. CEO notifié à chaque doc."}


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
