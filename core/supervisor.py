import asyncio
import logging
import os
from http.server import HTTPServer, BaseHTTPRequestHandler
from threading import Thread

import httpx

logger = logging.getLogger(__name__)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
RENDER_API_KEY = os.getenv("RENDER_API_KEY")
TELEGRAM_SERVICE_ID = os.getenv("RENDER_TELEGRAM_SERVICE_ID", "srv-d90on1hkh4rs739kss7g")
PORT = int(os.getenv("PORT", 9090))


class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'{"status":"ok","service":"supervisor"}')

    def log_message(self, format, *args):
        pass


def run_health_server():
    server = HTTPServer(("0.0.0.0", PORT), HealthHandler)
    logger.info(f"Supervisor health server on port {PORT}")
    server.serve_forever()


async def notify_ceo(message: str):
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(
                f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                json={"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"}
            )
    except Exception as e:
        logger.error(f"Telegram notify failed: {e}")


async def check_telegram_bot() -> bool:
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getMe")
            return r.status_code == 200
    except Exception:
        return False


async def check_telegram_health() -> bool:
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get("https://organisation-ai-telegram.onrender.com/")
            return r.status_code == 200
    except Exception:
        return False


async def restart_telegram_service():
    if not RENDER_API_KEY:
        logger.warning("RENDER_API_KEY not set — cannot restart service autonomously")
        return False
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.post(
                f"https://api.render.com/v1/services/{TELEGRAM_SERVICE_ID}/restart",
                headers={"Authorization": f"Bearer {RENDER_API_KEY}"}
            )
            if r.status_code in (200, 202):
                logger.info("Telegram service restart triggered")
                return True
            logger.error(f"Restart API returned {r.status_code}: {r.text[:200]}")
            return False
    except Exception as e:
        logger.error(f"Restart failed: {e}")
        return False


async def supervise():
    logger.info("🔍 Supervisor started")
    failures = 0
    restart_mode = "restart" if RENDER_API_KEY else "notify-only"
    logger.info(f"Mode: {restart_mode} | Telegram service: {TELEGRAM_SERVICE_ID}")

    while True:
        try:
            api_ok = await check_telegram_bot()
            health_ok = await check_telegram_health()
            bot_ok = api_ok and health_ok

            if not bot_ok:
                failures += 1
                logger.warning(f"Bot unhealthy (api={api_ok}, health={health_ok}) — failure #{failures}")

                if failures >= 2:
                    if RENDER_API_KEY:
                        restarted = await restart_telegram_service()
                        if restarted:
                            await notify_ceo(
                                "🔄 *Supervisor — Redémarrage automatique*\n\n"
                                "Le bot Telegram était inaccessible.\n"
                                "Service redémarré automatiquement."
                            )
                            failures = 0
                        else:
                            await notify_ceo(
                                f"🔴 *Supervisor — Redémarrage échoué*\n\n"
                                f"Bot inaccessible après {failures} tentatives.\n"
                                f"Redémarrage manuel requis."
                            )
                    else:
                        await notify_ceo(
                            f"⚠️ *Supervisor — Bot Telegram inaccessible*\n\n"
                            f"Détecté après {failures} vérifications.\n"
                            f"Render redémarre automatiquement.\n\n"
                            f"_Configurez RENDER\\_API\\_KEY pour le redémarrage autonome._"
                        )
                        failures = 0
            else:
                if failures > 0:
                    logger.info("Bot recovered")
                failures = 0

        except Exception as e:
            logger.error(f"Supervisor loop error: {e}")

        await asyncio.sleep(60)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    Thread(target=run_health_server, daemon=True).start()
    asyncio.run(supervise())
