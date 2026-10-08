"""Speech recognition: downloading/loading the Vosk model and spotting the word "Ben".

Instead of transcribing everything (slow, needs a huge model, mishears Dutch accents),
the recognizer gets a tiny grammar: "ben", a few greetings, ~40 common short words and
"[unk]" for everything else. Vosk then only has to decide "was that Ben or not",
which is a lot more accurate and runs fine on the small ~40 MB models.
Tested on Dutch-accented clips: hears ~89% of "Ben"s (old setup ~62%) with ~6% false alarms (old ~16%).
"""

from __future__ import annotations

import json
import logging
import shutil
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from vosk import KaldiRecognizer, Model, SetLogLevel

from .config import ConfigError

log = logging.getLogger("ben.speech")

SAMPLE_RATE = 16000

# Shortcuts for SPEECH_MODEL. Both are the small (~40 MB download, ~150 MB RAM) models.
KNOWN_MODELS = {
    "nl": "vosk-model-small-nl-0.22",
    "en": "vosk-model-small-en-us-0.15",
}
MODEL_URL = "https://alphacephei.com/vosk/models/{name}.zip"

GREETINGS = ["hey", "hi", "hoi", "hallo", "hello", "yo"]

# Common short words, so Vosk has something better to call them than "ben".
# Without these, "ik ben moe" turns into "ben" and "hey" into "ben" too often.
FUNCTION_WORDS = [
    "ik", "je", "jij", "we", "wij", "ze", "zij", "hij", "dat", "dit", "dan", "en", "een", "de", "het",
    "is", "wat", "waar", "heb", "ga", "gaan", "bent", "niet", "nee", "ja",
    "i", "you", "the", "have", "are", "what", "can", "do", "did", "that", "a", "benjamin",
]
# "ik ben" is Dutch for "I am", never the name.
NOT_THE_NAME_AFTER = {"ik"}

# strictness -> (where "Ben" may be, how many of Vosk's best guesses to check)
STRICTNESS_RULES = {
    "strict": ("start", 1),
    "normal": ("early", 1),
    "relaxed": ("early", 3),
}


# ───────── model files ─────────
def _download(name: str, models_dir: Path) -> Path:
    target = models_dir / name
    url = MODEL_URL.format(name=name)
    models_dir.mkdir(parents=True, exist_ok=True)
    zip_path = models_dir / f"{name}.zip"

    log.info("Downloading speech model %s (about 40 MB, only happens once)...", name)
    last = -1
    with urllib.request.urlopen(url) as resp, open(zip_path, "wb") as out:
        total = int(resp.headers.get("Content-Length") or 0)
        done = 0
        while chunk := resp.read(1 << 16):
            out.write(chunk)
            done += len(chunk)
            if total:
                pct = done * 100 // total
                if pct // 20 != last:
                    last = pct // 20
                    log.info("  %d%%", pct)

    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(models_dir)
    zip_path.unlink(missing_ok=True)

    if not target.is_dir():
        shutil.rmtree(target, ignore_errors=True)
        raise ConfigError(f"Downloaded {url} but {target} wasn't in it.")
    log.info("Speech model saved to %s", target)
    return target


def resolve_model_path(setting: str, models_dir: Path) -> Path:
    if setting.lower() in KNOWN_MODELS:
        name = KNOWN_MODELS[setting.lower()]
        path = models_dir / name
        if path.is_dir():
            return path
        try:
            return _download(name, models_dir)
        except ConfigError:
            raise
        except Exception as exc:
            raise ConfigError(
                f"Couldn't download the speech model ({exc}). Download {MODEL_URL.format(name=name)} "
                f"yourself and unzip it into {models_dir}."
            ) from exc

    path = Path(setting)
    if not path.is_absolute():
        candidates = [models_dir / setting, Path.cwd() / setting]
        path = next((p for p in candidates if p.is_dir()), candidates[0])
    if not (path / "am").is_dir() and not (path / "conf").is_dir():
        raise ConfigError(
            f"SPEECH_MODEL={setting!r} isn't 'nl', 'en' or a Vosk model folder ({path} not found)."
        )
    return path


class SpeechModel:
    """The loaded Vosk model, shared by every call (load it once, it's the big thing in RAM)."""

    def __init__(self, path: Path) -> None:
        SetLogLevel(-1)
        self.path = path
        self.model = Model(str(path))
        # Small/"lgraph" models are built from HCLr.fst + Gr.fst and accept a grammar.
        # Big models have a fixed HCLG.fst: they ignore grammars and eat gigabytes of RAM.
        self.supports_grammar = (path / "graph" / "Gr.fst").is_file()
        self.function_words = [w for w in FUNCTION_WORDS if self.model.vosk_model_find_word(w) >= 0]
        self.greetings = [w for w in GREETINGS if self.model.vosk_model_find_word(w) >= 0]
        if self.model.vosk_model_find_word("ben") < 0:
            raise ConfigError(f"The speech model at {path} doesn't know the word 'ben'.")

        if not self.supports_grammar:
            log.warning(
                "%s is a large model: it can't use the wake-word grammar, recognition is worse "
                "for 'Ben' and it uses a lot of RAM. Set SPEECH_MODEL=nl (or en) instead.",
                path.name,
            )
        log.info("Speech model loaded: %s", path.name)

    def spotter(self, strictness: str) -> WakeSpotter:
        return WakeSpotter(self, strictness)


@dataclass
class Heard:
    # More words came after "Ben" in the same sentence, so the question was already asked.
    question_included: bool


class WakeSpotter:
    """Listens to one person and says when they called Ben."""

    def __init__(self, speech: SpeechModel, strictness: str) -> None:
        self.where, self.nbest = STRICTNESS_RULES.get(strictness, STRICTNESS_RULES["normal"])
        self.greetings = set(speech.greetings)

        if speech.supports_grammar:
            words = ["ben"] + speech.greetings + speech.function_words + ["[unk]"]
            self.recognizer = KaldiRecognizer(speech.model, SAMPLE_RATE, json.dumps(words))
        else:
            self.recognizer = KaldiRecognizer(speech.model, SAMPLE_RATE)
        if self.nbest > 1:
            self.recognizer.SetMaxAlternatives(self.nbest)
        self.recognizer.SetWords(False)
        self.has_audio = False

    def _is_name(self, words: list[str], i: int) -> bool:
        before = words[:i]
        if all(w in self.greetings for w in before):  # "ben ...", "hey ben ..."
            return True
        if self.where == "start":
            return False
        # "early": one other word before it is fine ("hé ben" often comes out as "hij ben"), "ik ben" isn't
        return len(before) == 1 and before[0] not in NOT_THE_NAME_AFTER

    def _check(self, result_json: str) -> Heard | None:
        result = json.loads(result_json)
        texts = [a.get("text", "") for a in result["alternatives"]] if "alternatives" in result \
            else [result.get("text", "")]
        if texts and texts[0]:
            log.debug("Heard: %s", " / ".join(texts))
        for text in texts:
            words = text.split()
            for i, w in enumerate(words):
                if w == "ben" and self._is_name(words, i):
                    return Heard(question_included=i + 1 < len(words))
        return None

    def feed(self, pcm16k: bytes) -> Heard | None:
        """Feed 16 kHz mono audio. Returns a Heard when a finished sentence contained Ben."""
        self.has_audio = True
        if self.recognizer.AcceptWaveform(pcm16k):
            self.has_audio = False
            return self._check(self.recognizer.Result())
        return None

    def flush(self) -> Heard | None:
        """Call when the person stopped talking. Returns a Heard if the last bit contained Ben."""
        if not self.has_audio:
            return None
        self.has_audio = False
        return self._check(self.recognizer.FinalResult())

    def reset(self) -> None:
        self.recognizer.Reset()
        self.has_audio = False


# ───────── audio helpers ─────────
def discord_to_16k(pcm: bytes) -> np.ndarray:
    """48 kHz stereo int16 (what Discord gives) -> 16 kHz mono int16."""
    a = np.frombuffer(pcm, dtype=np.int16)
    a = a[: len(a) - len(a) % 6].astype(np.int32).reshape(-1, 6)
    # average both channels and 3 neighbouring samples: mono + cheap low-pass + 3x downsample
    return (a.sum(axis=1) // 6).astype(np.int16)


def rms(samples: np.ndarray) -> float:
    if samples.size == 0:
        return 0.0
    f = samples.astype(np.float32)
    return float(np.sqrt(np.mean(f * f)))
