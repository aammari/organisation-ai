import asyncio
import httpx
import os
import logging
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from threading import Thread

logger = logging.getLogger(__name__)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
BACKEND = os.getenv("BACKEND_URL", "https://organisation-ai.onrender.com")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
PORT = int(os.getenv("PORT", 8081))

_SB_HEADERS = None


def _headers():
    global _SB_HEADERS
    if not _SB_HEADERS:
        _SB_HEADERS = {
            "apikey": SUPABASE_KEY,
            "Authorization": f"Bearer {SUPABASE_KEY}",
            "Content-Type": "application/json",
            "Prefer": "return=representation",
        }
    return _SB_HEADERS


class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'{"status":"ok","service":"backlog-worker"}')

    def log_message(self, format, *args):
        pass


async def notify(msg: str):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            await c.post(
                f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                json={"chat_id": TELEGRAM_CHAT_ID, "text": msg},
            )
    except Exception as e:
        logger.error(f"Notify failed: {e}")


async def fetch_pending() -> list:
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.get(
            f"{SUPABASE_URL}/rest/v1/backlog_items",
            params={"status": "eq.PENDING", "order": "priority.asc", "limit": "1", "select": "*"},
            headers=_headers(),
        )
        r.raise_for_status()
        return r.json()


async def update_item(item_id: str, patch: dict):
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.patch(
            f"{SUPABASE_URL}/rest/v1/backlog_items",
            params={"id": f"eq.{item_id}"},
            headers=_headers(),
            json=patch,
        )
        r.raise_for_status()


async def run():
    logger.info("Backlog Worker started")
    while True:
        try:
            items = await fetch_pending()
            if items:
                item = items[0]
                if item.get("decision_level") == "D3":
                    await notify(f"Décision D3 requise\n{item['title']}")
                    await update_item(item["id"], {"status": "WAITING_CEO"})
                else:
                    await update_item(item["id"], {"status": "IN_PROGRESS"})
                    async with httpx.AsyncClient(timeout=120) as c:
                        r = await c.post(
                            f"{BACKEND}/cycle",
                            json={
                                "message": (
                                    f"{item['id']}: {item['title']}\n\n"
                                    f"{item.get('description', '')}"
                                )
                            },
                        )
                    await update_item(item["id"], {
                        "status": "DONE",
                        "result": r.json(),
                        "updated_at": datetime.now().isoformat(),
                    })
                    await notify(f"Backlog {item['id']} traite\n{item['title']}")
            else:
                await asyncio.sleep(300)
                continue
        except Exception as e:
            logger.error(f"Worker error: {e}")
        await asyncio.sleep(30)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    Thread(
        target=lambda: HTTPServer(("0.0.0.0", PORT), HealthHandler).serve_forever(),
        daemon=True,
    ).start()
    asyncio.run(run())
