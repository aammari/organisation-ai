import asyncio
import logging
import os

import httpx

logger = logging.getLogger(__name__)

BACKEND_URL = os.getenv("BACKEND_URL", "https://organisation-ai.onrender.com")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
POLL_INTERVAL = int(os.getenv("BACKLOG_POLL_INTERVAL", "300"))


async def _notify(message: str):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(
                f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                json={"chat_id": TELEGRAM_CHAT_ID, "text": message},
            )
    except Exception as e:
        logger.error(f"Backlog notify failed: {e}")


def _get_db():
    from app.database import get_supabase
    return get_supabase()


async def _fetch_pending() -> list:
    db = _get_db()
    rows = (
        db.table("work_packages")
        .select("id,title,status,context_snapshot")
        .like("id", "BT-%")
        .eq("status", "PENDING")
        .order("id")
        .execute()
    )
    return rows.data or []


def _update_status(item_id: str, status: str, snap_patch: dict):
    db = _get_db()
    existing = db.table("work_packages").select("context_snapshot").eq("id", item_id).execute()
    snap = (existing.data[0].get("context_snapshot") or {}) if existing.data else {}
    snap.update(snap_patch)
    db.table("work_packages").update({"status": status, "context_snapshot": snap}).eq("id", item_id).execute()


async def _process(item: dict):
    item_id = item["id"]
    title = item["title"]
    snap = item.get("context_snapshot") or {}
    desc = snap.get("description", title)

    logger.info(f"BacklogWorker processing {item_id}: {title}")
    await asyncio.to_thread(_update_status, item_id, "IN_PROGRESS", {})

    try:
        async with httpx.AsyncClient(timeout=120) as client:
            r = await client.post(
                f"{BACKEND_URL}/cycle",
                json={"message": f"[BACKLOG {item_id}] {desc}"},
            )
            r.raise_for_status()
            result = r.json()

        response = result.get("response", "")[:500]
        await asyncio.to_thread(_update_status, item_id, "DONE", {"result": response})
        await _notify(
            f"Backlog {item_id} traite\n"
            f"Titre : {title}\n"
            f"Resultat : {response[:200]}"
        )
        logger.info(f"{item_id} DONE")

    except Exception as e:
        error = str(e)[:500]
        logger.error(f"{item_id} FAILED: {error}")
        await asyncio.to_thread(_update_status, item_id, "FAILED", {"error": error})
        await _notify(
            f"Backlog {item_id} echoue\n"
            f"Titre : {title}\n"
            f"Erreur : {error[:200]}"
        )


async def run_backlog_worker():
    logger.info(f"BacklogWorker started — interval {POLL_INTERVAL}s")
    while True:
        try:
            items = await _fetch_pending()
            if items:
                logger.info(f"BacklogWorker: {len(items)} item(s) PENDING")
                for item in items:
                    await _process(item)
            else:
                logger.debug("BacklogWorker: queue empty")
        except Exception as e:
            logger.error(f"BacklogWorker loop error: {e}")
        await asyncio.sleep(POLL_INTERVAL)
