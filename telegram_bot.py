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
            response = await client.get(f"{BACKEND_URL}/status")
            response.raise_for_status()
            data = response.json()

        cost = data.get("cost", {})
        by_agent = cost.get("by_agent", {})

        agent_lines = ""
        for model, info in by_agent.items():
            name = "Chief Architect" if "claude" in model else "Chief Analyst"
            agent_lines += (
                f"  • {name} : `${info['cost_usd']:.4f}` "
                f"({info['cycles']} cycles, "
                f"{info['input_tokens'] + info['output_tokens']:,} tokens)\n"
            )

        budget_pct = cost.get("budget_pct", 0)
        budget_icon = "🟢" if budget_pct < 80 else "🟡" if budget_pct < 100 else "🔴"

        no_cycle = "  Aucun cycle aujourd'hui"
        msg = (
            f"🏢 *Organisation AI*\n"
            f"Phase : `{data.get('phase', '—')}`  |  "
            f"Backend : ✅  |  Supabase : `{data.get('supabase', '—')}`\n\n"
            f"💰 *Coûts aujourd'hui*\n"
            f"  Total   : `${cost.get('today_usd', 0):.4f}`\n"
            f"  Ce mois : `${cost.get('month_usd', 0):.4f}`\n"
            f"  Budget  : {budget_icon} `{budget_pct:.1f}%` / $5.00\n\n"
            f"🤖 *Par agent*\n"
            f"{agent_lines or no_cycle}\n"
            f"📊 Cycles total : `{data.get('cycles_total', 0)}`"
        )
        await update.message.reply_text(msg, parse_mode='Markdown')

    except Exception as e:
        logger.error(f"Erreur /status: {e}")
        await update.message.reply_text(f"❌ Impossible de récupérer le statut : {e}")


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
    filename = _GOV_FILES.get(doc_id)
    if not filename:
        await update.message.reply_text(f"Document {doc_id} inconnu.")
        return
    path = _DOCS_DIR / filename
    if not path.exists():
        await update.message.reply_text(f"Fichier {filename} introuvable.")
        return
    content = path.read_text()
    await update.message.reply_text(f"Validation {doc_id} en cours...")
    try:
        async with httpx.AsyncClient(timeout=300) as c:
            r = await c.post(
                f"{BACKEND_URL}/validate/doc",
                json={"doc_id": doc_id, "content": content},
            )
            r.raise_for_status()
            result = r.json()
        status = result.get("status", "?")
        remarks = result.get("remarks", [])
        await update.message.reply_text(
            f"Validation {doc_id} — {status}\n"
            f"Remarques Chief Analyst : {len(remarks)}\n"
            f"Thread : {result.get('thread_id')}"
        )
    except Exception as e:
        logger.error(f"validate_single {doc_id}: {e}")
        await update.message.reply_text(f"Erreur validation {doc_id} : {e}")


async def _handle_validate_batch(update: Update):
    docs = []
    for doc_id, filename in _GOV_FILES.items():
        path = _DOCS_DIR / filename
        if path.exists():
            docs.append({"id": doc_id, "content": path.read_text()})
    await update.message.reply_text(f"Batch validation lancé — {len(docs)} documents en file.\nCEO notifié après chaque document.")
    try:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.post(
                f"{BACKEND_URL}/validate/batch",
                json={"documents": docs},
            )
            r.raise_for_status()
    except Exception as e:
        logger.error(f"validate_batch: {e}")
        await update.message.reply_text(f"Erreur lancement batch : {e}")


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

    # PRIORITÉ 2 — Validation manuelle "valide G-XX" / "valide tous"
    msg_lower = message.lower()
    if msg_lower.startswith("valide"):
        if re.search(r"tous|all|batch", msg_lower):
            await _handle_validate_batch(update)
            return
        m = re.search(r"g-(\d+)", msg_lower)
        if m:
            await _handle_validate_single(update, f"G-{m.group(1).zfill(2)}")
            return

    # PRIORITÉ 3 — Tout le reste via /route (Chief of Staff unifié)
    await update.message.reply_text("Traitement en cours...")
    try:
        async with httpx.AsyncClient(timeout=300) as c:
            r = await c.post(f"{BACKEND_URL}/route", json={"message": message})
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
