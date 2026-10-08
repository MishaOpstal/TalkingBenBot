"""Finding and picking Ben's sound files.

assets/sounds/
  telephone/call/      played in name order when Ben joins (1_..., 2_..., 3_...)
  telephone/hang_up/   one random file when Ben leaves
  answers/yes.mp3      "Yes"
  answers/no.mp3       "No"
  yapping/             everything else Ben can say (ho ho ho, ugh, ...)

The text Ben shows in chat for a sound comes from its file name: "hohoho.mp3" shows
"Hohoho". Put text in square brackets to choose it yourself: "snore [Zzz...].mp3".
"""

from __future__ import annotations

import random
import re
from pathlib import Path

from .guild_settings import GuildSettings

AUDIO_EXTENSIONS = {".mp3", ".ogg", ".wav", ".m4a", ".flac"}
KINDS = ("yes", "no", "yapping")


def label(path: Path) -> str:
    """Chat text for a sound file."""
    match = re.search(r"\[(.+?)\]", path.stem)
    if match:
        return match.group(1)
    name = re.sub(r"[_\-]+", " ", path.stem).strip()
    return name[:1].upper() + name[1:]


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
        # "yes.mp3" or "yes [Yes!].mp3"
        for path in self._list(self.answers_dir):
            if re.sub(r"\s*\[.*?\]", "", path.stem).lower() == name:
                return path
        return None

    def call_sequence(self) -> list[Path]:
        return self._list(self.call_dir)

    def hang_up(self) -> Path | None:
        files = self._list(self.hang_up_dir)
        return random.choice(files) if files else None

    def yapping(self) -> list[Path]:
        return self._list(self.yapping_dir)

    def pick(self, kind: str) -> Path | None:
        """A sound of one kind: "yes", "no" or "yapping" (random one)."""
        if kind == "yapping":
            yaps = self.yapping()
            return random.choice(yaps) if yaps else None
        return self._answer(kind)

    def pick_answer(self, settings: GuildSettings) -> tuple[str, Path] | None:
        """Returns ("yes" | "no" | "yapping", file) using the server's chances."""
        weights = {"yes": settings.chance_yes, "no": settings.chance_no, "yapping": settings.chance_yapping}
        options = [(kind, self.pick(kind), w) for kind, w in weights.items() if w > 0]
        options = [(kind, path, w) for kind, path, w in options if path is not None]
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
