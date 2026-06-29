from datetime import datetime, date
from app.database import get_supabase

INPUT_COST_PER_1K = 0.003   # claude-sonnet-4-6
OUTPUT_COST_PER_1K = 0.015

# Cost entries stored in audit_log (operation='API_COST') — no extra DDL needed


class CostTracker:
    def __init__(self):
        self.db = get_supabase()

    def log_cycle(self, input_tokens: int, output_tokens: int, model: str) -> float:
        cost = (
            (input_tokens / 1000) * INPUT_COST_PER_1K
            + (output_tokens / 1000) * OUTPUT_COST_PER_1K
        )
        try:
            self.db.table("audit_log").insert({
                "actor": "CostTracker",
                "operation": "API_COST",
                "object_id": model,
                "new_value": {
                    "date": date.today().isoformat(),
                    "model": model,
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "cost_usd": round(cost, 6),
                },
                "metadata": {"timestamp": datetime.now().isoformat()},
            }).execute()
        except Exception:
            pass
        return cost

    def get_daily_rows(self, day: str) -> list:
        try:
            rows = (
                self.db.table("audit_log")
                .select("new_value")
                .eq("operation", "API_COST")
                .gte("timestamp", f"{day}T00:00:00")
                .lt("timestamp", f"{day}T23:59:59")
                .execute()
            )
            return [r["new_value"] for r in rows.data if r.get("new_value")]
        except Exception:
            return []

    def get_daily_cost(self, day: str) -> float:
        return sum(float(r.get("cost_usd", 0)) for r in self.get_daily_rows(day))

    def get_daily_breakdown(self, day: str) -> dict:
        breakdown: dict = {}
        for r in self.get_daily_rows(day):
            model = r.get("model", "unknown")
            if model not in breakdown:
                breakdown[model] = {"cost_usd": 0.0, "input_tokens": 0, "output_tokens": 0, "cycles": 0}
            breakdown[model]["cost_usd"] += float(r.get("cost_usd", 0))
            breakdown[model]["input_tokens"] += int(r.get("input_tokens", 0))
            breakdown[model]["output_tokens"] += int(r.get("output_tokens", 0))
            breakdown[model]["cycles"] += 1
        return breakdown

    def get_monthly_cost(self, month: str) -> float:
        try:
            year, mon = int(month[:4]), int(month[5:7])
            next_year, next_mon = (year + 1, 1) if mon == 12 else (year, mon + 1)
            next_month = f"{next_year:04d}-{next_mon:02d}-01"
            rows = (
                self.db.table("audit_log")
                .select("new_value")
                .eq("operation", "API_COST")
                .gte("timestamp", f"{month}-01T00:00:00")
                .lt("timestamp", f"{next_month}T00:00:00")
                .execute()
            )
            return sum(
                float(r["new_value"].get("cost_usd", 0))
                for r in rows.data
                if r.get("new_value")
            )
        except Exception:
            return 0.0
