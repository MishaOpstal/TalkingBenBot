"""Bot-wide settings, read once at startup from environment variables / the .env file.

Everything a server admin can change lives in guild_settings.py instead (changed with /settings).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:  # python-dotenv is optional, Docker passes env vars directly
    load_dotenv = None

ROOT = Path(__file__).resolve().parent.parent


class ConfigError(RuntimeError):
    pass


@dataclass(frozen=True)
class BotConfig:
    token: str
    speech_model: str
    models_dir: Path
    data_dir: Path
    sounds_dir: Path
    dev_guild_id: int | None
    log_level: str


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def load_config() -> BotConfig:
    if load_dotenv is not None:
        load_dotenv(ROOT / ".env")

    token = _env("DISCORD_TOKEN")
    if not token:
        raise ConfigError(
            "DISCORD_TOKEN is missing. Copy .env.example to .env and paste your bot token in it."
        )

    dev_guild = _env("DEV_GUILD_ID")
    if dev_guild and not dev_guild.isdigit():
        raise ConfigError(f"DEV_GUILD_ID must be a server ID (numbers only), got {dev_guild!r}.")

    return BotConfig(
        token=token,
        speech_model=_env("SPEECH_MODEL", "nl") or "nl",
        models_dir=Path(_env("MODELS_DIR", str(ROOT / "models"))),
        data_dir=Path(_env("DATA_DIR", str(ROOT / "data"))),
        sounds_dir=Path(_env("SOUNDS_DIR", str(ROOT / "assets" / "sounds"))),
        dev_guild_id=int(dev_guild) if dev_guild else None,
        log_level=(_env("LOG_LEVEL", "INFO") or "INFO").upper(),
    )
