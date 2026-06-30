import asyncio
import logging
import os
import uuid
from datetime import datetime, timezone

import httpx
from anthropic import Anthropic

from app.database import get_supabase

logger = logging.getLogger(__name__)

DELEGATED_LEVEL_RANK = {"D1": 1, "D2": 2, "D3": 3}
ACTIVE_WP_ID = os.getenv("ACTIVE_WP_ID", "WP-Sprint2-001")

_ESCALATION_PREFIXES = ("A", "B")
# Only explicit debate/thread triggers → everything else goes to ConversationEngine
_THREAD_KEYWORDS = {"débat", "discut", "thread"}
_SIMPLE_KEYWORDS: set[str] = set()  # ConversationEngine handles all cycle intents


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ChiefOfStaff:
    _last_backlog_run_at: str | None = None

    def __init__(self):
        self.db = get_supabase()

    async def log_action(self, source: str, raw: str) -> str:
        action_id = f"ACT-{uuid.uuid4().hex[:8]}"
        try:
            self.db.table("action_ledger").insert({
                "id": action_id,
                "source": source,
                "raw_message": raw[:500],  # cap to avoid large payloads
                "state": "RECEIVED",
                "created_at": _now(),
                "updated_at": _now(),
            }).execute()
        except Exception as e:
            logger.error(f"log_action: {e}")
        return action_id

    async def route_request(self, raw_message: str, action_id: str) -> dict:
        msg = raw_message.strip()
        parts = msg.split()

        if parts and parts[0].upper() in _ESCALATION_PREFIXES and len(parts) <= 2:
            route = "escalation"
        elif any(k in msg.lower() for k in _THREAD_KEYWORDS):
            route = "thread"
        else:
            # All other messages → ConversationEngine (no Haiku here)
            route = "cycle"

        try:
            self.db.table("action_ledger").update({
                "type": route,
                "state": "ROUTED",
                "updated_at": _now(),
            }).eq("id", action_id).execute()
        except Exception as e:
            logger.error(f"route_request update: {e}")

        return {"route": route, "raw": raw_message}

    async def _qualify_with_haiku(self, message: str) -> str:
        try:
            client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY", ""))
            resp = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=50,
                system="Qualifie ce message CEO. Retourne uniquement: thread ou cycle",
                messages=[{"role": "user", "content": message}],
            )
            text = resp.content[0].text.strip().lower()
            return "thread" if "thread" in text else "cycle"
        except Exception as e:
            logger.warning(f"qualify_with_haiku: {e} → fallback cycle")
            return "cycle"

    async def process_backlog(self):
        """Boucle permanente — traite les WP PENDING éligibles."""
        while True:
            ChiefOfStaff._last_backlog_run_at = _now()
            try:
                now = _now()
                items = (
                    self.db.table("work_packages")
                    .select("*")
                    .eq("status", "PENDING")
                    .eq("approved", True)
                    .eq("blocked", False)
                    .lte("scheduled_at", now)
                    .order("priority")
                    .order("created_at")
                    .limit(1)
                    .execute()
                )
                if not items.data:
                    await asyncio.sleep(300)
                    continue

                item = items.data[0]
                level = item.get("required_decision_level", "D1")
                if DELEGATED_LEVEL_RANK.get(level, 1) >= 3:
                    await self._notify_ceo(
                        f"D3 requis pour {item['id']} — {item['title']}\nEn attente CEO."
                    )
                    self.db.table("work_packages").update(
                        {"status": "WAITING_CEO", "updated_at": _now()}
                    ).eq("id", item["id"]).execute()
                    await asyncio.sleep(30)
                    continue

                # Verrouillage optimiste — évite double traitement
                claim = (
                    self.db.table("work_packages")
                    .update({"status": "CLAIMED", "claimed_at": _now(), "updated_at": _now()})
                    .eq("id", item["id"])
                    .eq("status", "PENDING")
                    .execute()
                )
                if not claim.data:
                    await asyncio.sleep(5)
                    continue

                await self._process_item(item)

            except Exception as e:
                logger.error(f"ChiefOfStaff.process_backlog: {e}")

            await asyncio.sleep(30)

    async def _process_item(self, item: dict):
        wp_id = item["id"]
        try:
            self.db.table("work_packages").update(
                {"status": "RUNNING", "updated_at": _now()}
            ).eq("id", wp_id).execute()

            backend = os.getenv("BACKEND_URL", "https://organisation-ai.onrender.com")
            async with httpx.AsyncClient(timeout=120) as c:
                r = await c.post(
                    f"{backend}/cycle",
                    json={"message": f"{wp_id}: {item['title']}\n{item.get('context_snapshot') or ''}"},
                )
                r.raise_for_status()
                result = r.json()

            self.db.table("work_packages").update({
                "status": "DONE",
                "result": result,
                "updated_at": _now(),
            }).eq("id", wp_id).execute()

        except Exception as e:
            logger.error(f"_process_item {wp_id}: {e}")
            try:
                self.db.table("work_packages").update({
                    "status": "FAILED",
                    "result": {"error": str(e)[:500]},
                    "updated_at": _now(),
                }).eq("id", wp_id).execute()
            except Exception as e2:
                logger.error(f"_process_item FAILED update {wp_id}: {e2}")

    async def _notify_ceo(self, msg: str):
        token = os.getenv("TELEGRAM_BOT_TOKEN", "")
        chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
        if not token or not chat_id:
            return
        try:
            async with httpx.AsyncClient(timeout=10) as c:
                await c.post(
                    f"https://api.telegram.org/bot{token}/sendMessage",
                    json={"chat_id": chat_id, "text": msg},
                )
        except Exception as e:
            logger.error(f"_notify_ceo: {e}")


cos = ChiefOfStaff()
