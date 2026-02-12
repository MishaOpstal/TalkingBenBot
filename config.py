import json
import os
from typing import Dict, Union

from exceptions import ConfigException, InvalidWeight, InvalidChance

CONFIG_PATH = "data/config.json"

DEFAULT_WEIGHTS: Dict[str, int] = {
    "yes": 10,
    "no": 10,
    "yapping": 2,
}

DEFAULT_PICKUP_CHANCE = 19  # 1 in 20 chance Ben doesn't pick up (0 = always picks up, 19 = 1 in 20)
DEFAULT_HANGUP_CHANCE = 5  # 1 in 20


class ConfigValidationError(ConfigException):
    """Raised when configuration validation fails"""
    pass


class ConfigOptions:
    def __init__(self) -> None:
        self.voice_enabled: Dict[str, bool] = {}
        self.answer_weights: Dict[str, Dict[str, int]] = {}
        self.pickup_chance: Dict[str, int] = {}  # New: per-context pickup chance
        self.hangup_chance: Dict[str, int] = {}  # New: per-context hangup chance

    # ───────────── ID Helpers ─────────────

    @staticmethod
    def _make_guild_key(guild_id: int) -> str:
        """Create a string key for guild configuration."""
        return str(guild_id)

    @staticmethod
    def _make_dm_key(user_id: int) -> str:
        """Create a string key for DM configuration, prefixed to avoid conflicts."""
        return f"direct_messages.{user_id}"

    # ───────────── Voice ─────────────

    def is_voice_enabled(self, context_id: Union[int, str]) -> bool:
        """Check if voice recognition is enabled for a context"""
        key = str(context_id)
        return self.voice_enabled.get(key, False)

    def set_voice_enabled(self, context_id: Union[int, str], enabled: bool) -> None:
        """
        Enable or disable voice recognition for a context

        Args:
            context_id: Guild ID or DM context string
            enabled: Whether to enable voice recognition
        """
        key = str(context_id)
        self.voice_enabled[key] = enabled

    # ───────────── Pickup Chance ─────────────

    def get_pickup_chance(self, context_id: Union[int, str]) -> int:
        """
        Get the pickup chance (0 = always picks up, 19 = 1 in 20 doesn't pick up)

        Args:
            context_id: Guild ID or DM context string

        Returns:
            Pickup chance value (0-99)
        """
        key = str(context_id)
        return self.pickup_chance.get(key, DEFAULT_PICKUP_CHANCE)

    def set_pickup_chance(self, context_id: Union[int, str], chance: int) -> None:
        """
        Set the pickup chance (0-99, where 0 = always picks up)

        Args:
            context_id: Guild ID or DM context string
            chance: Pickup chance (0-99)

        Raises:
            InvalidChance: If chance is not between 0 and 99
        """
        if not isinstance(chance, int):
            raise InvalidChance(f"Pickup chance must be an integer, got {type(chance).__name__}")
        if chance < 0 or chance > 99:
            raise InvalidChance(f"Pickup chance must be between 0 and 99, got {chance}")

        key = str(context_id)
        self.pickup_chance[key] = chance

    # ───────────── Hangup Chance ─────────────

    def get_hangup_chance(self, context_id: Union[int, str]) -> int:
        """
        Get the hangup chance (0 = always hangs up, 19 = 1 in 20 doesn't hang up)

        Args:
            context_id: Guild ID or DM context string

        Returns:
            Hangup chance value (0-99)
        """
        key = str(context_id)
        return self.hangup_chance.get(key, DEFAULT_HANGUP_CHANCE)

    def set_hangup_chance(self, context_id: Union[int, str], chance: int) -> None:
        """
        Set the hangup chance (0-99, where 0 = always hangs up)

        Args:
            context_id: Guild ID or DM context string
            chance: Hangup chance (0-99)

        Raises:
            InvalidChance: If chance is not between 0 and 99
        """
        if not isinstance(chance, int):
            raise InvalidChance(f"Hangup chance must be an integer, got {type(chance).__name__}")
        if chance < 0 or chance > 99:
            raise InvalidChance(f"Hangup chance must be between 0 and 99, got {chance}")

        key = str(context_id)
        self.hangup_chance[key] = chance

    # ───────────── Weights ─────────────

    def get_weights(self, context_id: Union[int, str]) -> Dict[str, int]:
        """
        Get answer weights for a context

        Args:
            context_id: Guild ID or DM context string

        Returns:
            Dictionary of answer type to weight
        """
        key = str(context_id)
        weights = self.answer_weights.get(key)
        if weights is None:
            weights = DEFAULT_WEIGHTS.copy()
            self.answer_weights[key] = weights

        self._normalize_weights(weights)
        return weights

    def set_weight(self, context_id: Union[int, str], answer_type: str, weight: int) -> None:
        """
        Set the weight for a specific answer type

        Args:
            context_id: Guild ID or DM context string
            answer_type: Type of answer ("yes", "no", "yapping")
            weight: Weight value (0-100)

        Raises:
            InvalidWeight: If weight is not between 0 and 100
        """
        if not isinstance(weight, int):
            raise InvalidWeight(f"Weight must be an integer, got {type(weight).__name__}")
        if weight < 0 or weight > 100:
            raise InvalidWeight(f"Weight must be between 0 and 100, got {weight}")

        key = str(context_id)
        weights = self.get_weights(key)
        weights[answer_type] = weight
        self._normalize_weights(weights)

    # ───────────── Normalization ─────────────

    @staticmethod
    def _normalize_weights(weights: Dict[str, int]) -> None:
        """
        Normalize weights dictionary to ensure all required keys exist

        Args:
            weights: Dictionary of weights to normalize
        """
        for key in DEFAULT_WEIGHTS:
            if key not in weights:
                weights[key] = DEFAULT_WEIGHTS[key]

        for key in list(weights.keys()):
            if not isinstance(weights[key], int) or weights[key] < 0:
                weights[key] = 0

    # ───────────── Validation ─────────────

    def validate(self) -> None:
        """
        Validate configuration data structure

        Raises:
            ConfigValidationError: If validation fails
        """
        if not isinstance(self.voice_enabled, dict):
            raise ConfigValidationError("voice_enabled must be a dict")

        if not isinstance(self.answer_weights, dict):
            raise ConfigValidationError("answer_weights must be a dict")

        if not isinstance(self.pickup_chance, dict):
            raise ConfigValidationError("pickup_chance must be a dict")

        if not isinstance(self.hangup_chance, dict):
            raise ConfigValidationError("hangup_chance must be a dict")

        for context_key, enabled in self.voice_enabled.items():
            if not isinstance(context_key, str):
                raise ConfigValidationError("voice_enabled keys must be strings")
            if not isinstance(enabled, bool):
                raise ConfigValidationError("voice_enabled values must be bools")

        for context_key, weights in self.answer_weights.items():
            if not isinstance(context_key, str):
                raise ConfigValidationError("answer_weights keys must be strings")
            if not isinstance(weights, dict):
                raise ConfigValidationError("answer_weights values must be dicts")

            for key, value in weights.items():
                if not isinstance(key, str):
                    raise ConfigValidationError("weight keys must be strings")
                if not isinstance(value, int):
                    raise ConfigValidationError("weight values must be ints")

        for context_key, chance in self.pickup_chance.items():
            if not isinstance(context_key, str):
                raise ConfigValidationError("pickup_chance keys must be strings")
            if not isinstance(chance, int):
                raise ConfigValidationError("pickup_chance values must be ints")

        for context_key, chance in self.hangup_chance.items():
            if not isinstance(context_key, str):
                raise ConfigValidationError("hangup_chance keys must be strings")
            if not isinstance(chance, int):
                raise ConfigValidationError("hangup_chance values must be ints")


# ─────────────────────────────────────
# Singleton
# ─────────────────────────────────────
config = ConfigOptions()


def load_config() -> None:
    """
    Load configuration from JSON file

    Raises:
        ConfigException: If loading or validation fails
    """
    if not os.path.isfile(CONFIG_PATH):
        return

    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)

        # ── voice_enabled ──
        if "voice_enabled" in data:
            # Handle both old int keys and new string keys
            config.voice_enabled = {
                str(k): bool(v)
                for k, v in data["voice_enabled"].items()
            }

        # ── pickup_chance ──
        if "pickup_chance" in data:
            config.pickup_chance = {
                str(k): int(v)
                for k, v in data["pickup_chance"].items()
            }

        # ── hangup_chance ──
        if "hangup_chance" in data:
            config.hangup_chance = {
                str(k): int(v)
                for k, v in data["hangup_chance"].items()
            }

        # ── answer_weights (migration-aware) ──
        if "answer_weights" in data:
            raw_weights = data["answer_weights"]

            # OLD FORMAT: global weights (all int values)
            if all(isinstance(v, int) for v in raw_weights.values()):
                # Migrate to per-context format for existing guilds
                for context_key in config.voice_enabled.keys():
                    config.answer_weights[context_key] = raw_weights.copy()
            else:
                # NEW FORMAT: per-context (guild or DM)
                # Handle both old int keys and new string keys
                for context_key, weights in raw_weights.items():
                    config.answer_weights[str(context_key)] = {
                        k: int(v) for k, v in weights.items()
                    }

        config.validate()

    except json.JSONDecodeError as e:
        raise ConfigException(f"Failed to parse config JSON: {e}")
    except ConfigValidationError as e:
        raise ConfigException(f"Config validation failed: {e}")
    except Exception as e:
        raise ConfigException(f"Failed to load config: {e}")


def save_config() -> None:
    """
    Save configuration to JSON file

    Raises:
        ConfigException: If saving fails
    """
    try:
        os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)

        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "voice_enabled": config.voice_enabled,
                    "answer_weights": config.answer_weights,
                    "pickup_chance": config.pickup_chance,
                    "hangup_chance": config.hangup_chance,
                },
                f,
                indent=2,
            )

    except OSError as e:
        raise ConfigException(f"Failed to save config (OS error): {e}")
    except Exception as e:
        raise ConfigException(f"Failed to save config: {e}")