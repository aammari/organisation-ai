from datetime import datetime, date
from app.database import get_supabase

INPUT_COST_PER_1K = 0.003   # claude-sonnet-4-6
OUTPUT_COST_PER_1K = 0.015


class CostTracker:
    def __init__(self):
        self.db = get_supabase()

    def log_cycle(self, input_tokens: int, output_tokens: int, model: str) -> float:
        cost = (
            (input_tokens / 1000) * INPUT_COST_PER_1K
            + (output_tokens / 1000) * OUTPUT_COST_PER_1K
        )
        try:
            self.db.table("api_usage").insert({
                "date": date.today().isoformat(),
                "model": model,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "cost_usd": round(cost, 6),
                "created_at": datetime.now().isoformat(),
            }).execute()
        except Exception:
            pass  # table may not exist yet — degrade gracefully
        return cost
