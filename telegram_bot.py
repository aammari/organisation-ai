import logging
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes
import httpx
import os

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
BACKEND_URL = "https://organisation-ai.onrender.com/cycle"

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message.text
    await update.message.reply_text("⏳ Organisation AI traite votre demande...")

    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.post(
            BACKEND_URL,
            json={"message": message}
        )
        result = response.json()

    reply = f"*Chief Architect*\n\n{result.get('response', 'Erreur')}"
    await update.message.reply_text(reply, parse_mode='Markdown')

app = Application.builder().token(TOKEN).build()
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

if __name__ == "__main__":
    logger.info("Organisation AI Telegram Bot starting...")
    app.run_polling()
