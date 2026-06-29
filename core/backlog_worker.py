import asyncio
import httpx
import os
import logging
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from threading import Thread

from app.database import get_supabase

logger = logging.getLogger(__name__)
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
BACKEND = os.getenv("BACKEND_URL", "https://organisation-ai.onrender.com")
PORT = int(os.getenv("PORT", 8081))


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


async def run():
    db = get_supabase()
    logger.info("Backlog Worker started")
    while True:
        try:
            items = (
                db.table("backlog_items")
                .select("*")
                .eq("status", "PENDING")
                .order("priority")
                .limit(1)
                .execute()
            )
            if items.data:
                item = items.data[0]
                if item["decision_level"] == "D3":
                    await notify(
                        f"Décision D3 requise\n{item['title']}"
                    )
                    db.table("backlog_items").update(
                        {"status": "WAITING_CEO"}
                    ).eq("id", item["id"]).execute()
                else:
                    db.table("backlog_items").update(
                        {"status": "IN_PROGRESS"}
                    ).eq("id", item["id"]).execute()
                    async with httpx.AsyncClient(timeout=120) as c:
                        r = await c.post(
                            f"{BACKEND}/cycle",
                            json={
                                "message": (
                                    f"{item['id']}: {item['title']}\n\n"
                                    f"{item['description']}"
                                )
                            },
                        )
                    db.table("backlog_items").update(
                        {
                            "status": "DONE",
                            "result": r.json(),
                            "updated_at": datetime.now().isoformat(),
                        }
                    ).eq("id", item["id"]).execute()
                    await notify(
                        f"Backlog {item['id']} traite\n{item['title']}"
                    )
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
