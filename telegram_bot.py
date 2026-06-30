import json
import logging
import os
import re
from pathlib import Path
from threading import Thread
from http.server import HTTPServer, BaseHTTPRequestHandler

import anthropic
from telegram import Update
from telegram.ext import Application, MessageHandler, CommandHandler, filters, ContextTypes
import httpx

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s"
)
logger = logging.getLogger(__name__)

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
BACKEND_URL = "https://organisation-ai.onrender.com"
PORT = int(os.getenv("PORT", 8080))
INTERNAL_TOKEN = os.getenv("INTERNAL_TOKEN", "")

CHIEF_OF_STAFF_PROMPT = """Tu es Chief of Staff. Tu qualifies l'intention du CEO et routes vers le bon agent.

Analyse le message et retourne UNIQUEMENT un JSON valide, sans markdown, sans explication :

Si l'intention est DISCUSSION ou VALIDATION (débat inter-agents requis) :
{"route": "thread", "subject": "<sujet précis extrait du message>"}

Pour tout autre intention (ANALYSE, PRODUCTION, ACTION, question, demande d'info) :
{"route": "cycle"}

Règle : préfère "cycle" en cas de doute. "thread" uniquement si un débat structuré entre agents est explicitement utile."""

_ceo_chat_id: int | None = None


class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/chatid" and _ceo_chat_id:
            body = f'{{"chat_id":{_ceo_chat_id}}}'.encode()
        else:
            body = b'{"status":"ok","service":"telegram-bot"}'
        self.send_response(200)
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        pass


def run_health_server():
    server = HTTPServer(("0.0.0.0", PORT), HealthHandler)
    logger.info(f"Health server on port {PORT}")
    server.serve_forever()


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Bonjour ! Je suis l'interface exécutive d'Organisation AI.\n\n"
        "Commandes disponibles :\n"
        "/status — État du système\n\n"
        "Envoyez votre demande et le Chief Architect vous répondra."
    )


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            m = await client.get(f"{BACKEND_URL}/observability/metrics?source=telegram")
            m.raise_for_status()
            metrics = m.json()
            e = await client.get(f"{BACKEND_URL}/observability/errors")
            e.raise_for_status()
            errors = e.json()

        wp = metrics.get("wp_by_status", {})
        failed_total = metrics["total_work_packages_failed"]
        alert_lines = []
        if metrics["waiting_ceo_count"] > 0:
            alert_lines.append(f"  {metrics['waiting_ceo_count']} WP en attente CEO")
        if failed_total > 0:
            alert_lines.append(f"  {failed_total} WP FAILED/ERROR")
        if errors.get("failed_actions"):
            alert_lines.append(f"  {len(errors['failed_actions'])} action(s) FAILED")

        last_run = metrics.get("last_backlog_run_at") or "—"
        if last_run and last_run != "—":
            last_run = last_run[:19].replace("T", " ") + " UTC"

        msg = (
            f"Organisation AI — Status\n\n"
            f"WP :\n"
            f"  PENDING : {wp.get('PENDING', 0)}\n"
            f"  RUNNING : {wp.get('RUNNING', 0)}\n"
            f"  WAITING_CEO : {metrics['waiting_ceo_count']}\n"
            f"  FAILED : {failed_total}\n"
            f"  DONE : {metrics['total_work_packages_done']}\n\n"
            f"Actions aujourd'hui : {metrics['total_actions_today']}\n\n"
            f"Derniere activite :\n  {last_run}\n"
            f"  Temps moyen traitement : {metrics['average_processing_time_seconds']}s\n\n"
            f"Alertes :\n{chr(10).join(alert_lines) if alert_lines else '  Aucune'}"
        )
        await update.message.reply_text(msg, parse_mode=None)

    except Exception as e:
        logger.error(f"Erreur /status: {e}")
        await update.message.reply_text(f"Impossible de recuperer le statut : {e}")


async def send_long_message(update: Update, text: str):
    for i in range(0, len(text), 4000):
        await update.message.reply_text(text[i:i + 4000], parse_mode=None)


async def qualify_intent(message: str) -> dict:
    try:
        client = anthropic.AsyncAnthropic(api_key=ANTHROPIC_API_KEY)
        resp = await client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=128,
            system=CHIEF_OF_STAFF_PROMPT,
            messages=[{"role": "user", "content": message}],
        )
        raw = resp.content[0].text.strip()
        # Strip markdown code fences if Haiku wraps the JSON
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.strip()
        return json.loads(raw)
    except Exception as e:
        logger.warning(f"qualify_intent failed: {e} — fallback cycle")
        return {"route": "cycle"}


_DOCS_DIR = Path(__file__).parent / "docs" / "governance"

_GOV_FILES = {
    "G-01": "MeetingProtocol-G01-v1_0.md",
    "G-02": "DataRetention-G02-v1_0.md",
    "G-03": "AgentOnboarding-G03-v1_0.md",
    "G-04": "ConfigManagement-G04-v1_0.md",
    "G-05": "SecurityPolicy-G05-v1_0.md",
    "G-06": "CapabilityLifecycle-G06-v1_0.md",
    "G-07": "Glossary-G07-v1_0.md",
    "G-08": "ExceptionWaiver-G08-v1_0.md",
    "G-09": "AIEthics-G09-v1_0.md",
    "G-10": "OrgHealthReview-G10-v1_0.md",
    "G-11": "CEOCommunicationProtocol-G11-v1_1.md",
}


async def _handle_validate_single(update: Update, doc_id: str):
    await update.message.reply_text(f"Validation {doc_id} — chargement depuis GitHub...")
    try:
        async with httpx.AsyncClient(timeout=300) as c:
            # No content — backend fetches from canonical GitHub source
            r = await c.post(
                f"{BACKEND_URL}/validate/doc",
                json={"doc_id": doc_id},
            )
            r.raise_for_status()
            result = r.json()
        status = result.get("status", "?")
        if status == "ALREADY_VALIDATED":
            await update.message.reply_text(
                f"{doc_id} — ALREADY_VALIDATED\nDocument inchangé, validation non relancée."
            )
        elif status in ("MISSING_DOCUMENTS", "UPLOAD_FAILED", "UNKNOWN_DOC"):
            await update.message.reply_text(
                f"{doc_id} — {status}\n{result.get('error', result.get('path', ''))}"
            )
        else:
            remarks = result.get("remarks", [])
            extra = f"\nSHA : {result.get('doc_sha','?')[:12]}..." if result.get("doc_sha") else ""
            await update.message.reply_text(
                f"Validation {doc_id} — {status}\n"
                f"Remarques Chief Analyst : {len(remarks)}\n"
                f"Thread : {result.get('thread_id')}{extra}"
            )
    except Exception as e:
        logger.error(f"validate_single {doc_id}: {e}")
        await update.message.reply_text(f"Erreur validation {doc_id} : {e}")


async def _handle_validate_batch(update: Update):
    # Pass only doc_ids — backend fetches content from canonical GitHub source
    # and runs preflight check before launching
    doc_ids = list(_GOV_FILES.keys())
    await update.message.reply_text(
        f"Preflight GitHub en cours — {len(doc_ids)} documents G..."
    )
    try:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.post(
                f"{BACKEND_URL}/validate/batch",
                json={"doc_ids": doc_ids},
            )
            r.raise_for_status()
            result = r.json()
        if result.get("status") == "MISSING_DOCUMENTS":
            missing = [m["doc_id"] for m in result.get("missing", [])]
            await update.message.reply_text(
                "Batch BLOQUÉ — documents absents de GitHub :\n"
                + "\n".join(f"• {d}" for d in missing)
            )
        else:
            await update.message.reply_text(
                f"Batch lancé — {result.get('queued', len(doc_ids))} documents.\nCEO notifié après chaque document."
            )
    except Exception as e:
        logger.error(f"validate_batch: {e}")
        await update.message.reply_text(f"Erreur lancement batch : {e}")


async def _handle_adopt(update: Update, doc_id: str):
    await update.message.reply_text(f"Adoption {doc_id} en cours...")
    try:
        async with httpx.AsyncClient(timeout=60) as c:
            r = await c.post(f"{BACKEND_URL}/adoption/request", json={"doc_id": doc_id})
            r.raise_for_status()
            result = r.json()
        status = result.get("status", "?")
        if status == "ADOPTED":
            await update.message.reply_text(
                f"{doc_id} — ADOPTED\n"
                f"Version: {result.get('version', '?')}\n"
                f"SHA: {result.get('doc_sha', '?')}\n"
                f"Decision: {result.get('decision_level', '?')}"
            )
        elif status == "WAITING_CEO":
            await update.message.reply_text(
                f"{doc_id} — WAITING_CEO (D3)\nApprobation CEO requise."
            )
        elif status == "REFUSED":
            await update.message.reply_text(
                f"{doc_id} — REFUSÉ\nRaison: {result.get('reason', '?')}\n{result.get('detail', '')}"
            )
        else:
            await update.message.reply_text(f"{doc_id} — {status}\n{result.get('detail', '')}")
    except Exception as e:
        logger.error(f"adopt {doc_id}: {e}")
        await update.message.reply_text(f"Erreur adoption {doc_id}: {e}")


async def _handle_compliance_doc(update: Update, doc_id: str):
    try:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.get(f"{BACKEND_URL}/compliance/doc/{doc_id}")
            r.raise_for_status()
            result = r.json()
        gaps = result.get("gaps", [])
        gap_lines = "\n".join(f"• [{g['severity']}] {g['description']}" for g in gaps[:3]) or "Aucun"
        await update.message.reply_text(
            f"Conformité {doc_id} — {result.get('status', '?')}\n"
            f"Score: {result.get('score', 0)}%\n"
            f"Gaps:\n{gap_lines}"
        )
    except Exception as e:
        logger.error(f"compliance_doc {doc_id}: {e}")
        await update.message.reply_text(f"Erreur conformité {doc_id}: {e}")


async def _handle_certification(update: Update):
    try:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.get(f"{BACKEND_URL}/compliance/status")
            r.raise_for_status()
            result = r.json()
        await update.message.reply_text(
            f"Certification organisationnelle\n"
            f"Score global: {result.get('overall_score', 0)}%\n"
            f"Docs vérifiés: {result.get('documents_checked', 0)}\n"
            f"Conformes: {result.get('compliant', 0)}\n"
            f"Partiels: {result.get('partial', 0)}\n"
            f"Non-conformes: {result.get('non_compliant', 0)}\n"
            f"Gaps ouverts: {len(result.get('gaps', []))}"
        )
    except Exception as e:
        logger.error(f"certification: {e}")
        await update.message.reply_text(f"Erreur certification: {e}")


async def _handle_readiness(update: Update):
    try:
        async with httpx.AsyncClient(timeout=30) as c:
            comp = await c.get(f"{BACKEND_URL}/compliance/status")
            comp.raise_for_status()
            adop = await c.get(f"{BACKEND_URL}/adoption/registry")
            adop.raise_for_status()
        comp_data = comp.json()
        adop_data = adop.json()
        adopted = adop_data.get("adopted", [])
        await update.message.reply_text(
            f"Readiness organisationnelle\n"
            f"Docs adoptés: {len(adopted)}\n"
            f"Score conformité: {comp_data.get('overall_score', 0)}%\n"
            f"Gaps ouverts: {len(comp_data.get('gaps', []))}\n"
            f"Documents: {', '.join(d['doc_id'] for d in adopted[:5]) or 'Aucun'}"
        )
    except Exception as e:
        logger.error(f"readiness: {e}")
        await update.message.reply_text(f"Erreur readiness: {e}")


async def _handle_goal(update: Update, goal: str):
    await update.message.reply_text(f"Analyse objectif: {goal[:60]}...")
    try:
        async with httpx.AsyncClient(timeout=60) as c:
            r = await c.post(f"{BACKEND_URL}/goal/plan", json={"goal": goal})
            r.raise_for_status()
            result = r.json()
        wps = result.get("proposed_work_packages", [])
        blockers = result.get("blockers", [])
        wp_lines = "\n".join(f"{w['order']}. {w['title']}" for w in wps[:4])
        blocker_lines = "\n".join(f"• {b}" for b in blockers[:3]) or "Aucun"
        await update.message.reply_text(
            f"Objectif analysé.\n"
            f"Readiness: {result.get('readiness', 0)}%\n"
            f"Bloquants: {len(blockers)}\n"
            f"{blocker_lines}\n\n"
            f"Plan proposé:\n{wp_lines or 'Aucun WP requis'}\n\n"
            f"Décision CEO requise: {'oui' if result.get('requires_ceo_approval') else 'non'}"
        )
    except Exception as e:
        logger.error(f"goal_plan: {e}")
        await update.message.reply_text(f"Erreur analyse objectif: {e}")


async def _handle_improve(update: Update, doc_id: str):
    await update.message.reply_text(f"DIE — {doc_id} : lancement cycle amélioration...")
    try:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.post(f"{BACKEND_URL}/improve/doc", json={"doc_id": doc_id})
            r.raise_for_status()
            result = r.json()
        await update.message.reply_text(
            f"DIE — {doc_id}\n"
            f"Run : {result.get('run_id')}\n"
            f"Statut : {result.get('status')}\n"
            "Validation en arrière-plan. CEO notifié à chaque étape."
        )
    except Exception as e:
        logger.error(f"improve {doc_id}: {e}")
        await update.message.reply_text(f"Erreur DIE {doc_id}: {e}")


async def _handle_docs_ready(update: Update):
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.get(f"{BACKEND_URL}/improve/list?status=ADOPTION_PROPOSAL")
            r.raise_for_status()
        runs = r.json().get("runs", [])
        if not runs:
            await update.message.reply_text("Aucun document en attente d'adoption.")
            return
        lines = "\n".join(f"• {run['doc_id']} (run: {run['id']}) — conformité {run.get('compliance_score','?')}%" for run in runs[:5])
        await update.message.reply_text(f"Documents prêts pour adoption :\n{lines}")
    except Exception as e:
        await update.message.reply_text(f"Erreur: {e}")


async def _handle_docs_to_fix(update: Update):
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.get(f"{BACKEND_URL}/improve/list?status=IMPLEMENTATION")
            r.raise_for_status()
        runs = r.json().get("runs", [])
        if not runs:
            await update.message.reply_text("Aucun document en attente de correction.")
            return
        lines = "\n".join(f"• {run['doc_id']} — itération {run.get('iteration','?')}/3" for run in runs[:5])
        await update.message.reply_text(f"Documents à corriger :\n{lines}")
    except Exception as e:
        await update.message.reply_text(f"Erreur: {e}")


async def _handle_org_health(update: Update):
    try:
        async with httpx.AsyncClient(timeout=20) as c:
            comp = await c.get(f"{BACKEND_URL}/compliance/status")
            adop = await c.get(f"{BACKEND_URL}/adoption/registry")
            runs = await c.get(f"{BACKEND_URL}/improve/list")
        comp_data = comp.json()
        adopted = adop.json().get("adopted", [])
        all_runs = runs.json().get("runs", [])
        by_status: dict[str, int] = {}
        for run in all_runs:
            s = run.get("status", "?")
            by_status[s] = by_status.get(s, 0) + 1
        await update.message.reply_text(
            f"Organisation Health\n\n"
            f"Docs adoptés: {len(adopted)}\n"
            f"Conformité: {comp_data.get('overall_score', 0)}%\n"
            f"Gaps ouverts: {len(comp_data.get('gaps', []))}\n\n"
            f"DIE runs:\n"
            + "\n".join(f"• {s}: {n}" for s, n in sorted(by_status.items()))
        )
    except Exception as e:
        await update.message.reply_text(f"Erreur org health: {e}")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global _ceo_chat_id
    message = update.message.text.strip()
    user = update.message.from_user.username or update.message.from_user.first_name
    chat_id = update.message.chat.id
    _ceo_chat_id = chat_id
    logger.info(f"Message de {user} (chat_id={chat_id}): {message[:80]}")

    # PRIORITÉ 1 — Intervention CEO dans un thread actif (reply_to)
    # Garde-fou : traité avant routing pour ne pas perdre le contexte thread
    reply_to = update.message.reply_to_message
    if reply_to:
        try:
            async with httpx.AsyncClient(timeout=15) as c:
                r = await c.post(
                    f"{BACKEND_URL}/thread/intervene",
                    json={"telegram_thread_msg_id": reply_to.message_id, "text": message},
                )
                data = r.json()
            if data.get("updated", 0) > 0:
                await update.message.reply_text("Intervention CEO transmise aux agents.")
                return
        except Exception as e:
            logger.warning(f"intervene lookup: {e}")

    # PRIORITÉ 2 — Commandes structurées (déterministes, sans LLM)
    msg_lower = message.lower()

    # "valide G-XX" / "valide tous"
    if msg_lower.startswith("valide"):
        if re.search(r"tous|all|batch", msg_lower):
            await _handle_validate_batch(update)
            return
        m = re.search(r"([a-z])-(\d+)", msg_lower)
        if m:
            await _handle_validate_single(update, f"{m.group(1).upper()}-{m.group(2).zfill(2)}")
            return

    # "adopte G-XX" → adoption request
    if msg_lower.startswith("adopt"):
        m = re.search(r"([a-z])-(\d+)", msg_lower)
        if m:
            await _handle_adopt(update, f"{m.group(1).upper()}-{m.group(2).zfill(2)}")
            return

    # "conformite G-XX" → compliance doc
    if re.match(r"conformit[eé]", msg_lower):
        m = re.search(r"([a-z])-(\d+)", msg_lower)
        if m:
            await _handle_compliance_doc(update, f"{m.group(1).upper()}-{m.group(2).zfill(2)}")
        else:
            await _handle_certification(update)
        return

    # "certification" → global compliance score
    if msg_lower.strip() in ("certification", "certif"):
        await _handle_certification(update)
        return

    # "readiness" → context + compliance summary
    if msg_lower.strip() in ("readiness", "maturité", "maturite"):
        await _handle_readiness(update)
        return

    # "prépare X" / "prepare X" → goal planner
    if re.match(r"(prépare|prepare|planifie|objectif)\s+", msg_lower):
        goal = re.sub(r"^(prépare|prepare|planifie|objectif)\s+", "", message.strip(), flags=re.IGNORECASE)
        await _handle_goal(update, goal)
        return

    # "améliore X" / "ameliore X" → improvement engine
    if re.match(r"am[eé]liore?\s+", msg_lower):
        m = re.search(r"([a-z])-(\d+)", msg_lower)
        if m:
            await _handle_improve(update, f"{m.group(1).upper()}-{m.group(2).zfill(2)}")
            return

    # "validation X" (sans s) → validation single doc
    if re.match(r"validation\s+", msg_lower):
        m = re.search(r"([a-z])-(\d+)", msg_lower)
        if m:
            await _handle_validate_single(update, f"{m.group(1).upper()}-{m.group(2).zfill(2)}")
            return

    # Dashboard / list commands
    if msg_lower.strip() in ("documents prêts", "documents prets", "adoptions proposées", "adoptions proposees"):
        await _handle_docs_ready(update)
        return
    if msg_lower.strip() in ("documents à corriger", "documents a corriger"):
        await _handle_docs_to_fix(update)
        return
    if msg_lower.strip() in ("organisation health", "org health", "health"):
        await _handle_org_health(update)
        return

    # PRIORITÉ 3 — Tout le reste via /route (Chief of Staff unifié)
    await update.message.reply_text("Traitement en cours...")
    _route_headers = {"X-Internal-Token": INTERNAL_TOKEN} if INTERNAL_TOKEN else {}
    try:
        async with httpx.AsyncClient(timeout=300) as c:
            r = await c.post(f"{BACKEND_URL}/route", json={"message": message}, headers=_route_headers)
            r.raise_for_status()
            result = r.json()
        logger.info(f"route={result.get('route')} action={result.get('action_id')}")

        # Thread case: open in Telegram then start on backend with msg_id
        if result.get("route") == "thread" and not result.get("thread_id"):
            opening = await update.message.reply_text("Ouverture de la discussion inter-agents...")
            async with httpx.AsyncClient(timeout=300) as c:
                r2 = await c.post(
                    f"{BACKEND_URL}/thread/start",
                    json={
                        "title": message[:100],
                        "wp_id": "WP-Sprint2-001",
                        "subject": message,
                        "telegram_chat_id": update.message.chat_id,
                        "telegram_thread_msg_id": opening.message_id,
                    },
                )
                r2.raise_for_status()
            return

        response_text = result.get("response", str(result))
        await send_long_message(update, response_text)

    except httpx.HTTPStatusError as e:
        logger.error(f"Erreur backend HTTP {e.response.status_code}: {e.response.text}")
        await update.message.reply_text(f"Erreur backend ({e.response.status_code}). Réessayez.")
    except Exception as e:
        logger.error(f"Erreur inattendue: {type(e).__name__}: {e}")
        await update.message.reply_text(f"Erreur: {e}")


async def cmd_dashboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📊 *Dashboard CEO*\nhttps://organisation-ai.onrender.com",
        parse_mode='Markdown'
    )


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Erreur Telegram: {context.error}", exc_info=context.error)


if __name__ == "__main__":
    Thread(target=run_health_server, daemon=True).start()
    logger.info("Organisation AI Telegram Bot starting...")

    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("dashboard", cmd_dashboard))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_error_handler(error_handler)

    app.run_polling()
