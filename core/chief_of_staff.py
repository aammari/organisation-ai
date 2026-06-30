import asyncio
import logging
import os
import uuid
from datetime import datetime

import httpx
from anthropic import Anthropic

from app.database import get_supabase

logger = logging.getLogger(__name__)

DELEGATED_LEVEL_RANK = {"D1": 1, "D2": 2, "D3": 3}

_ESCALATION_PREFIXES = ("A", "B")
_THREAD_KEYWORDS = {"débat", "discut", "valide", "validation", "thread"}
_SIMPLE_KEYWORDS = {"status", "état", "liste", "combien", "qui", "résume"}


class ChiefOfStaff:
    def __init__(self):
        self.db = get_supabase()

    async def log_action(self, source: str, raw: str) -> str:
        action_id = f"ACT-{uuid.uuid4().hex[:8]}"
        self.db.table("action_ledger").insert({
            "id": action_id,
            "source": source,
            "raw_message": raw,
            "state": "RECEIVED",
        }).execute()
        return action_id

    async def route_request(self, raw_message: str, action_id: str) -> dict:
        msg = raw_message.strip()
        parts = msg.split()

        if parts and parts[0].upper() in _ESCALATION_PREFIXES and len(parts) <= 2:
            route = "escalation"
        elif any(k in msg.lower() for k in _THREAD_KEYWORDS):
            route = "thread"
        elif any(k in msg.lower() for k in _SIMPLE_KEYWORDS):
            route = "cycle_simple"
        else:
            route = await self._qualify_with_haiku(msg)

        self.db.table("action_ledger").update({
            "type": route,
            "state": "ROUTED",
            "updated_at": datetime.now().isoformat(),
        }).eq("id", action_id).execute()

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
        """Boucle permanente — traite les WP PENDING éligibles (amendements 1, 4)."""
        while True:
            try:
                now = datetime.now().isoformat()
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
                        {"status": "WAITING_CEO"}
                    ).eq("id", item["id"]).execute()
                    await asyncio.sleep(30)
                    continue

                # Verrouillage optimiste — évite double traitement (amendement 4)
                claim = (
                    self.db.table("work_packages")
                    .update({"status": "CLAIMED", "claimed_at": datetime.now().isoformat()})
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
        self.db.table("work_packages").update({"status": "RUNNING"}).eq("id", item["id"]).execute()
        try:
            backend = os.getenv("BACKEND_URL", "https://organisation-ai.onrender.com")
            async with httpx.AsyncClient(timeout=120) as c:
                r = await c.post(
                    f"{backend}/cycle",
                    json={"message": f"{item['id']}: {item['title']}\n{item.get('description', '')}"},
                )
                result = r.json()
            self.db.table("work_packages").update({"status": "DONE", "result": result}).eq("id", item["id"]).execute()
        except Exception as e:
            logger.error(f"_process_item {item['id']}: {e}")
            self.db.table("work_packages").update({"status": "ERROR"}).eq("id", item["id"]).execute()

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
