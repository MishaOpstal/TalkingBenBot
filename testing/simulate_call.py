"""Run recorded audio through Ben's real listening logic, without Discord.

    python testing/simulate_call.py clip1.wav clip2.mp3 ...

Each file is played as if one person said it in a call. Prints whether Ben would have
answered and how long after you stopped talking. Needs ffmpeg. Handy to tune settings
or to check how well Ben understands your own voice: record yourself saying
"Ben, ben je gek?" a few times and throw the files at this.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ben.guild_settings import GuildSettings  # noqa: E402
from ben.listener import Conversation  # noqa: E402
from ben.speech import SpeechModel, resolve_model_path  # noqa: E402

FRAME = 3840  # 20 ms of 48 kHz stereo int16


def load_pcm(path: Path) -> bytes:
    if path.suffix == ".pcm":  # raw 48 kHz stereo s16le
        return path.read_bytes()
    return subprocess.run(
        ["ffmpeg", "-loglevel", "error", "-i", str(path), "-f", "s16le", "-ar", "48000", "-ac", "2", "-"],
        capture_output=True, check=True,
    ).stdout


def simulate(speech: SpeechModel, pcm: bytes, settings: GuildSettings) -> float | None:
    """Returns seconds between end of speech and Ben answering, or None if he didn't."""
    answered: list[float] = []
    t = 1000.0
    conv = Conversation(speech, lambda: settings, lambda uid: answered.append(t))

    # Discord stops sending packets when you're quiet: skip quiet frames like it does
    frames = [pcm[i:i + FRAME] for i in range(0, len(pcm) - FRAME + 1, FRAME)]
    levels = np.array([np.sqrt(np.mean(np.frombuffer(f, np.int16).astype(np.float32) ** 2)) for f in frames])
    gate = max(200.0, 4 * float(np.percentile(levels, 10)))
    last_loud = None
    for frame, level in zip(frames, levels, strict=True):
        if level > gate:
            last_loud = t
        if last_loud is not None and t - last_loud < 0.2:  # a little hangover, like Discord
            conv.feed(1, frame, t)
        t += 0.02
        if round(t * 50) % 2 == 0:
            conv.tick(t)
        if answered:
            break
    end = t
    while not answered and t < end + 6:
        t += 0.05
        conv.tick(t)
    if not answered:
        return None
    return answered[0] - (last_loud or end)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+", type=Path)
    ap.add_argument("--model", default="nl", help="nl, en or a model folder (default nl)")
    ap.add_argument("--strictness", default="normal", choices=["strict", "normal", "relaxed"])
    ap.add_argument("--mode", default="name", choices=["name", "always"])
    ap.add_argument("--delay", type=float, default=0.8)
    args = ap.parse_args()

    settings = GuildSettings(wake_mode=args.mode, strictness=args.strictness, answer_delay=args.delay)
    speech = SpeechModel(resolve_model_path(args.model, ROOT / "models"))
    for f in args.files:
        lag = simulate(speech, load_pcm(f), settings)
        print(f"{f.name:40s} " + ("no answer" if lag is None else f"answered {lag:+.2f}s after you stopped"))


if __name__ == "__main__":
    main()
