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


class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'{"status":"ok","service":"telegram-bot"}')

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

        last = data.get("last_cycle")
        if last:
            ts = last.get("created_at") or last.get("timestamp", "—")
            intent = last.get("qualified_intent") or last.get("intent", "—")
            last_cycle_str = f"  • `{ts[:19].replace('T', ' ')}` — `{intent}`"
        else:
            last_cycle_str = "  • Aucun cycle exécuté"

        msg = (
            f"🏢 *Organisation AI*\n\n"
            f"📋 Phase : `{data['phase']}`\n"
            f"⚙️ Backend : ✅ `{data['backend']}`\n"
            f"🗄️ Supabase : `{data['supabase']}`\n"
            f"🔢 Cycles total : `{data.get('cycles_total', 0)}`\n\n"
            f"🤖 *Agents actifs*\n"
            f"  • Chief Architect : `{data['agents']['chief_architect']}`\n"
            f"  • Chief Analyst : `{data['agents']['chief_analyst']}`\n\n"
            f"🔄 *Dernier cycle*\n{last_cycle_str}"
        )
        await update.message.reply_text(msg, parse_mode='Markdown')

    except Exception as e:
        logger.error(f"Erreur /status: {e}")
        await update.message.reply_text(f"❌ Impossible de récupérer le statut : {e}")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message.text
    user = update.message.from_user.username or update.message.from_user.first_name
    logger.info(f"Message reçu de {user}: {message[:80]}")

    await update.message.reply_text("⏳ Organisation AI traite votre demande...")

    try:
        async with httpx.AsyncClient(timeout=120) as client:
            response = await client.post(f"{BACKEND_URL}/cycle", json={"message": message})
            response.raise_for_status()
            result = response.json()
            logger.info(f"Backend répondu: intent={result.get('intent')}, decision={result.get('analyst_decision')}")

        reply = f"*Chief Architect*\n\n{result.get('response', 'Aucune réponse.')}"
        await update.message.reply_text(reply, parse_mode='Markdown')

    except httpx.HTTPStatusError as e:
        logger.error(f"Erreur backend HTTP {e.response.status_code}: {e.response.text}")
        await update.message.reply_text(f"❌ Erreur backend ({e.response.status_code}). Réessayez.")
    except Exception as e:
        logger.error(f"Erreur inattendue: {type(e).__name__}: {e}")
        await update.message.reply_text(f"❌ Erreur: {e}")


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Erreur Telegram: {context.error}", exc_info=context.error)


if __name__ == "__main__":
    Thread(target=run_health_server, daemon=True).start()
    logger.info("Organisation AI Telegram Bot starting...")

    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_error_handler(error_handler)

    app.run_polling()
