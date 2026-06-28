from app.database import get_supabase
from config import MANUAL_IDENTIFIER_ALLOWED

VALID_PREFIXES = ["EVID", "DEC", "WP", "ER", "EVT", "AUD", "PROMPT", "CAP"]

class IdentifierService:
    def __init__(self):
        self.db = get_supabase()

    def generate(self, prefix: str) -> str:
        if prefix not in VALID_PREFIXES:
            raise ValueError(f"Invalid prefix: {prefix}")
        result = self.db.rpc(
            "generate_identifier",
            {"p_prefix": prefix}
        ).execute()
        return result.data

    def validate(self, identifier: str) -> bool:
        parts = identifier.split("-")
        if len(parts) != 2:
            return False
        prefix, number = parts
        return prefix in VALID_PREFIXES and number.isdigit() and len(number) == 4
