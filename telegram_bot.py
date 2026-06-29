import logging
import os
from threading import Thread
from http.server import HTTPServer, BaseHTTPRequestHandler

from telegram import Update
from telegram.ext import Application, MessageHandler, CommandHandler, filters, ContextTypes
import httpx

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s"
)
logger = logging.getLogger(__name__)

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
BACKEND_URL = "https://organisation-ai.onrender.com"
PORT = int(os.getenv("PORT", 8080))

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


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global _ceo_chat_id
    message = update.message.text
    user = update.message.from_user.username or update.message.from_user.first_name
    chat_id = update.message.chat.id
    _ceo_chat_id = chat_id
    logger.info(f"Message reçu de {user} (chat_id={chat_id}): {message[:80]}")

    await update.message.reply_text("⏳ Organisation AI traite votre demande...")

    try:
        async with httpx.AsyncClient(timeout=120) as client:
            response = await client.post(f"{BACKEND_URL}/cycle", json={"message": message})
            response.raise_for_status()
            result = response.json()
            logger.info(f"Backend répondu: intent={result.get('intent')}, decision={result.get('analyst_decision')}")

        reply = f"Chief Architect\n\n{result.get('response', 'Aucune réponse.')}"
        await update.message.reply_text(reply, parse_mode=None)

    except httpx.HTTPStatusError as e:
        logger.error(f"Erreur backend HTTP {e.response.status_code}: {e.response.text}")
        await update.message.reply_text(f"❌ Erreur backend ({e.response.status_code}). Réessayez.")
    except Exception as e:
        logger.error(f"Erreur inattendue: {type(e).__name__}: {e}")
        await update.message.reply_text(f"❌ Erreur: {e}")


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
