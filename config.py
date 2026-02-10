import json
import os
from typing import Dict

CONFIG_PATH = "data/config.json"

DEFAULT_WEIGHTS: Dict[str, int] = {
    "yes": 10,
    "no": 10,
    "yapping": 2,
}


class ConfigValidationError(Exception):
    pass


class ConfigOptions:
    def __init__(self) -> None:
        self.voice_enabled: Dict[int, bool] = {}
        self.answer_weights: Dict[int, Dict[str, int]] = {}

    # ───────────── Voice ─────────────

    def is_voice_enabled(self, guild_id: int) -> bool:
        return self.voice_enabled.get(guild_id, False)

    def set_voice_enabled(self, guild_id: int, enabled: bool) -> None:
        self.voice_enabled[guild_id] = enabled

    # ───────────── Weights ─────────────

    def get_weights(self, guild_id: int) -> Dict[str, int]:
        weights = self.answer_weights.get(guild_id)
        if weights is None:
            weights = DEFAULT_WEIGHTS.copy()
            self.answer_weights[guild_id] = weights

        self._normalize_weights(weights)
        return weights

    def set_weight(self, guild_id: int, answer_type: str, weight: int) -> None:
        weights = self.get_weights(guild_id)
        weights[answer_type] = max(0, int(weight))
        self._normalize_weights(weights)

    # ───────────── Normalization ─────────────

    @staticmethod
    def _normalize_weights(weights: Dict[str, int]) -> None:
        for key in DEFAULT_WEIGHTS:
            if key not in weights:
                weights[key] = DEFAULT_WEIGHTS[key]

        for key in list(weights.keys()):
            if not isinstance(weights[key], int) or weights[key] < 0:
                weights[key] = 0

    # ───────────── Validation ─────────────

    def validate(self) -> None:
        if not isinstance(self.voice_enabled, dict):
            raise ConfigValidationError("voice_enabled must be a dict")

        if not isinstance(self.answer_weights, dict):
            raise ConfigValidationError("answer_weights must be a dict")

        for guild_id, enabled in self.voice_enabled.items():
            if not isinstance(guild_id, int):
                raise ConfigValidationError("voice_enabled keys must be ints")
            if not isinstance(enabled, bool):
                raise ConfigValidationError("voice_enabled values must be bools")

        for guild_id, weights in self.answer_weights.items():
            if not isinstance(guild_id, int):
                raise ConfigValidationError("answer_weights keys must be ints")
            if not isinstance(weights, dict):
                raise ConfigValidationError("answer_weights values must be dicts")

            for key, value in weights.items():
                if not isinstance(key, str):
                    raise ConfigValidationError("weight keys must be strings")
                if not isinstance(value, int):
                    raise ConfigValidationError("weight values must be ints")


# ─────────────────────────────────────
# Singleton
# ─────────────────────────────────────
config = ConfigOptions()


def load_config() -> None:
    if not os.path.isfile(CONFIG_PATH):
        return

    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)

        # ── voice_enabled ──
        if "voice_enabled" in data:
            config.voice_enabled = {
                int(k): bool(v)
                for k, v in data["voice_enabled"].items()
            }

        # ── answer_weights (migration-aware) ──
        if "answer_weights" in data:
            raw_weights = data["answer_weights"]

            # OLD FORMAT: global weights
            if all(isinstance(v, int) for v in raw_weights.values()):
                for guild_id in config.voice_enabled.keys():
                    config.answer_weights[guild_id] = raw_weights.copy()
            else:
                # NEW FORMAT: per-guild
                for guild_id, weights in raw_weights.items():
                    config.answer_weights[int(guild_id)] = {
                        k: int(v) for k, v in weights.items()
                    }

        config.validate()

    except Exception as e:
        print(f"[Config] Failed to load config: {e}")


def save_config() -> None:
    try:
        os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)

        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "voice_enabled": config.voice_enabled,
                    "answer_weights": config.answer_weights,
                },
                f,
                indent=2,
            )

    except Exception as e:
        print(f"[Config] Failed to save config: {e}")
