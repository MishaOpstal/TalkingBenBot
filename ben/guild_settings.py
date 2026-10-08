"""Per-server settings, changed with /settings and saved to data/guilds.json."""

from __future__ import annotations

import json
import logging
import os
import threading
from dataclasses import asdict, dataclass, fields
from pathlib import Path

log = logging.getLogger("ben.settings")

WAKE_MODES = {
    "name": "Say \"Ben\" first, then ask your question",
    "always": "Ben answers everything anyone says (like the app)",
}

STRICTNESS = {
    "strict": "\"Ben\" has to be the first word (\"Ben, ...\" or \"Hey Ben, ...\"). Fewest false alarms",
    "normal": "\"Ben\" in the first two words, never \"ik ben\". Best balance",
    "relaxed": "Like normal, but also answers when he only thinks he heard Ben",
}


@dataclass
class GuildSettings:
    # Does Ben listen to voice at all? Off = only /ask works.
    listening: bool = True
    # "name" or "always", see WAKE_MODES.
    wake_mode: str = "name"
    # "strict", "normal" or "relaxed", see STRICTNESS. Only used in "name" mode.
    strictness: str = "normal"
    # Seconds of silence after your question before Ben answers.
    answer_delay: float = 0.8
    # Relative chances. 40/40/20 means yes 40%, no 40%, yapping 20%.
    chance_yes: int = 40
    chance_no: int = 40
    chance_yapping: int = 20
    # Ben answers in text chat when you @mention him or reply to him.
    chat: bool = True
    # Percent chance Ben doesn't pick up when you /call him.
    ignore_call_chance: int = 5
    # Percent chance Ben refuses to be hung up on (says "no" and kicks you from the call).
    refuse_hangup_chance: int = 5

    def chances_percent(self) -> tuple[float, float, float]:
        total = self.chance_yes + self.chance_no + self.chance_yapping
        if total <= 0:
            return 0.0, 0.0, 0.0
        return (
            100 * self.chance_yes / total,
            100 * self.chance_no / total,
            100 * self.chance_yapping / total,
        )


_FIELDS = {f.name for f in fields(GuildSettings)}


class SettingsStore:
    def __init__(self, data_dir: Path) -> None:
        self.path = data_dir / "guilds.json"
        self._legacy_path = data_dir / "config.json"
        self._lock = threading.Lock()
        self._guilds: dict[int, GuildSettings] = {}
        self._load()

    def get(self, guild_id: int) -> GuildSettings:
        with self._lock:
            settings = self._guilds.get(guild_id)
            if settings is None:
                settings = self._guilds[guild_id] = GuildSettings()
            return settings

    def update(self, guild_id: int, **changes) -> GuildSettings:
        with self._lock:
            settings = self._guilds.setdefault(guild_id, GuildSettings())
            for key, value in changes.items():
                if key not in _FIELDS:
                    raise KeyError(key)
                setattr(settings, key, value)
            self._save()
            return settings

    def reset(self, guild_id: int) -> GuildSettings:
        with self._lock:
            settings = self._guilds[guild_id] = GuildSettings()
            self._save()
            return settings

    # ───────── persistence ─────────
    def _load(self) -> None:
        if self.path.is_file():
            try:
                raw = json.loads(self.path.read_text(encoding="utf-8"))
                for gid, values in raw.items():
                    clean = {k: v for k, v in values.items() if k in _FIELDS}
                    self._guilds[int(gid)] = GuildSettings(**clean)
                log.info("Loaded settings for %d server(s)", len(self._guilds))
            except Exception:
                log.exception("Could not read %s, starting with default settings", self.path)
            return

        if self._legacy_path.is_file():
            self._migrate_legacy()

    def _migrate_legacy(self) -> None:
        """Convert the old data/config.json (voice_enabled + global answer_weights)."""
        try:
            raw = json.loads(self._legacy_path.read_text(encoding="utf-8"))
        except Exception:
            log.exception("Could not read old config %s, ignoring it", self._legacy_path)
            return

        enabled = raw.get("voice_enabled", {k: v for k, v in raw.items() if k.isdigit()})
        weights = raw.get("answer_weights", {})
        yes = int(weights.get("yes", 10))
        no = int(weights.get("no", 10))
        # The old setting was per yapping file (7 files by default).
        yapping = int(weights.get("yapping", 2)) * 7

        for gid, on in enabled.items():
            self._guilds[int(gid)] = GuildSettings(
                listening=bool(on), chance_yes=yes, chance_no=no, chance_yapping=yapping
            )
        self._save()
        log.info("Migrated old config.json for %d server(s) to guilds.json", len(self._guilds))

    def _save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            data = {str(gid): asdict(s) for gid, s in self._guilds.items()}
            tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
            os.replace(tmp, self.path)
        except Exception:
            log.exception("Could not save settings to %s", self.path)
