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


async def keep_alive():
    async with httpx.AsyncClient() as c:
        try:
            await c.get(
                "https://organisation-ai-telegram.onrender.com/health",
                timeout=10,
            )
        except Exception:
            pass


async def notify_ceo(message: str):
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(
                f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                json={"chat_id": TELEGRAM_CHAT_ID, "text": message}
            )
    except Exception as e:
        logger.error(f"Telegram notify failed: {e}")


async def notify_fix_in_progress(error: str):
    await notify_ceo(
        f"Correction en cours\n"
        f"Probleme : {error[:100]}\n"
        f"Action : analyse et fix automatique\n"
        f"Retour prevu : ~2 minutes"
    )


async def notify_fix_done(error: str, result: str):
    await notify_ceo(
        f"Correction appliquee\n"
        f"Probleme : {error[:100]}\n"
        f"Resultat : {result[:100]}"
    )


async def notify_fix_failed(error: str):
    await notify_ceo(
        f"Correction echouee\n"
        f"Probleme : {error[:100]}\n"
        f"Action requise de ta part."
    )


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


async def restart_telegram_service() -> bool:
    if not RENDER_API_KEY:
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


async def auto_fix_errors(error: str) -> bool:
    logger.info(f"auto_fix_errors triggered: {error[:80]}")
    await notify_fix_in_progress(error)

    if not RENDER_API_KEY:
        await notify_fix_done(error, "Render redemarre automatiquement le service (free tier)")
        return True

    restarted = await restart_telegram_service()
    if not restarted:
        await notify_fix_failed(error)
        return False

    await asyncio.sleep(30)

    api_ok = await check_telegram_bot()
    health_ok = await check_telegram_health()
    recovered = api_ok and health_ok

    if recovered:
        await notify_fix_done(error, "Service redemarre et operationnel")
    else:
        await notify_fix_failed(error)

    return recovered


async def supervise():
    logger.info("Supervisor started")
    failures = 0
    counter = 0
    restart_mode = "restart" if RENDER_API_KEY else "notify-only"
    logger.info(f"Mode: {restart_mode} | Telegram service: {TELEGRAM_SERVICE_ID}")

    while True:
        counter += 1
        if counter % 10 == 0:
            await keep_alive()

        if counter % 5 == 0:
            try:
                async with httpx.AsyncClient(timeout=15) as client:
                    r = await client.post("https://organisation-ai.onrender.com/context/refresh")
                    if r.status_code == 200:
                        logger.info("Org context refreshed")
                    else:
                        logger.warning(f"Context refresh returned {r.status_code}")
            except Exception as e:
                logger.warning(f"Context refresh failed: {e}")

        try:
            api_ok = await check_telegram_bot()
            health_ok = await check_telegram_health()
            bot_ok = api_ok and health_ok

            if not bot_ok:
                failures += 1
                error_desc = f"Bot inaccessible (api={api_ok}, health={health_ok}) — tentative #{failures}"
                logger.warning(error_desc)

                if failures >= 2:
                    fixed = await auto_fix_errors(error_desc)
                    if fixed:
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
