"""Finding and picking Ben's sound files.

assets/sounds/
  telephone/call/      played in name order when Ben joins (1_..., 2_..., 3_...)
  telephone/hang_up/   one random file when Ben leaves
  answers/yes.mp3      "Yes"
  answers/no.mp3       "No"
  yapping/             everything else Ben can say (ho ho ho, ugh, ...)
"""

from __future__ import annotations

import random
from pathlib import Path

from .guild_settings import GuildSettings

AUDIO_EXTENSIONS = {".mp3", ".ogg", ".wav", ".m4a", ".flac"}


class Sounds:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.call_dir = root / "telephone" / "call"
        self.hang_up_dir = root / "telephone" / "hang_up"
        self.answers_dir = root / "answers"
        self.yapping_dir = root / "yapping"

    @staticmethod
    def _list(folder: Path) -> list[Path]:
        if not folder.is_dir():
            return []
        return sorted(p for p in folder.iterdir() if p.suffix.lower() in AUDIO_EXTENSIONS)

    def _answer(self, name: str) -> Path | None:
        for ext in AUDIO_EXTENSIONS:
            path = self.answers_dir / f"{name}{ext}"
            if path.is_file():
                return path
        return None

    def call_sequence(self) -> list[Path]:
        return self._list(self.call_dir)

    def hang_up(self) -> Path | None:
        files = self._list(self.hang_up_dir)
        return random.choice(files) if files else None

    def yapping(self) -> list[Path]:
        return self._list(self.yapping_dir)

    def pick_answer(self, settings: GuildSettings) -> tuple[str, Path] | None:
        """Returns ("yes" | "no" | "yapping", file) using the server's chances."""
        options: list[tuple[str, Path | None, int]] = [
            ("yes", self._answer("yes"), settings.chance_yes),
            ("no", self._answer("no"), settings.chance_no),
        ]
        yaps = self.yapping()
        if yaps:
            options.append(("yapping", random.choice(yaps), settings.chance_yapping))

        options = [(kind, path, w) for kind, path, w in options if path is not None and w > 0]
        if not options:
            return None

        kind, path, _ = random.choices(options, weights=[w for _, _, w in options])[0]
        return kind, path

    def check(self) -> list[str]:
        """Human readable problems with the sound folder, empty list if all good."""
        problems = []
        if not self.call_sequence():
            problems.append(f"no call sounds in {self.call_dir}")
        if not self._list(self.hang_up_dir):
            problems.append(f"no hang up sounds in {self.hang_up_dir}")
        if not self._answer("yes") or not self._answer("no"):
            problems.append(f"yes/no answers missing in {self.answers_dir}")
        return problems
