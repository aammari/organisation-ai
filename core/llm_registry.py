"""Dynamic LLM Provider Registry (PARTIE H).

Loads provider config from config/llm_config.json if present,
falls back to hardcoded defaults. Allows runtime model switching
without code changes.
"""

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_CONFIG_PATH = Path(__file__).parent.parent / "config" / "llm_config.json"

_DEFAULTS: dict[str, dict] = {
    "classifier": {
        "provider": "anthropic",
        "model": "claude-haiku-4-5-20251001",
        "max_tokens": 128,
        "description": "Conversation intent classification (budget-protected)",
    },
    "advisor": {
        "provider": "anthropic",
        "model": "claude-haiku-4-5-20251001",
        "max_tokens": 512,
        "description": "Executive advice and reasoning",
    },
    "planner": {
        "provider": "anthropic",
        "model": "claude-haiku-4-5-20251001",
        "max_tokens": 200,
        "description": "Goal planning and goal classification",
    },
}


class LLMRegistry:
    def __init__(self):
        self._config: dict[str, dict] = {}
        self._load()

    def _load(self) -> None:
        if _CONFIG_PATH.exists():
            try:
                with open(_CONFIG_PATH) as f:
                    loaded = json.load(f)
                # Merge loaded over defaults
                self._config = {**_DEFAULTS, **loaded}
                logger.info(f"llm_registry: loaded {_CONFIG_PATH}")
                return
            except Exception as e:
                logger.warning(f"llm_registry: failed to load config ({e}), using defaults")
        self._config = dict(_DEFAULTS)

    def reload(self) -> None:
        self._load()

    def get_model(self, role: str) -> str:
        """Return model ID for the given role, or Haiku as safe default."""
        cfg = self._config.get(role, _DEFAULTS.get("classifier", {}))
        return cfg.get("model", "claude-haiku-4-5-20251001")

    def get_max_tokens(self, role: str) -> int:
        cfg = self._config.get(role, _DEFAULTS.get("classifier", {}))
        return cfg.get("max_tokens", 128)

    def get(self, role: str) -> dict:
        return dict(self._config.get(role, _DEFAULTS.get(role, _DEFAULTS["classifier"])))

    def list_roles(self) -> list[str]:
        return list(self._config.keys())


llm_registry = LLMRegistry()
