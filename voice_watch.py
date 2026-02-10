import asyncio
import json
import math
import struct
import time
import audioop
import discord
from vosk import Model, KaldiRecognizer

from config import voice_enabled
from audio import pick_weighted_ben_answer, play_mp3

# ─────────────────────────────────────────────
# Tunables
# ─────────────────────────────────────────────
MIN_SPEECH_SECONDS = 0.6
SILENCE_SECONDS = 0.35
CHECK_INTERVAL = 0.03
MAX_IDLE_AFTER_WAKE = 5.0

WAKE_WORDS = ("then", "ben", "hey ben", "hi ben", "hello ben", "hallo ben")
VOSK_MODEL_PATH = "models/vosk"

# ─────────────────────────────────────────────
# Load Vosk once
# ─────────────────────────────────────────────
vosk_model = Model(VOSK_MODEL_PATH)


def pcm_rms(pcm: bytes) -> float:
    if not pcm:
        return 0.0

    count = len(pcm) // 2
    if count <= 0:
        return 0.0

    samples = struct.unpack("<" + "h" * count, pcm)
    return math.sqrt(sum(s * s for s in samples) / count)


class BenSink(discord.sinks.Sink):
    def __init__(self, guild_id: int):
        super().__init__(filters=None)
        self.guild_id = guild_id
        self.reset_session(full=True)

    # ───────── Helpers ─────────
    def _new_recognizer(self):
        recognizer = KaldiRecognizer(vosk_model, 16000)
        recognizer.SetWords(False)
        return recognizer

    def reset_session(self, full: bool = False):
        self.ben_activated = False
        self.active_user_id = None

        self.last_loud_time = 0.0
        self.speech_start_time = None
        self.total_speech_time = 0.0

        self.noise_floor_by_user = {}
        self.speech_active = False

        self.ack_played = False
        self.too_short_played = False

        if full:
            self.recognizer = self._new_recognizer()

    # ───────── Audio Input ─────────
    def write(self, pcm: bytes, user_id: int) -> None:
        now = time.monotonic()

        # ─────────────────────────
        # Mono + resample for recognizer
        # ─────────────────────────
        try:
            mono = audioop.tomono(pcm, 2, 1, 1)
            mono_16k, _ = audioop.ratecv(
                mono, 2, 1, 48000, 16000, None
            )
        except Exception:
            return

        # ─────────────────────────
        # Recognition (always running)
        # ─────────────────────────
        text = ""

        if self.recognizer.AcceptWaveform(mono_16k):
            result = json.loads(self.recognizer.Result())
            text = result.get("text", "").lower()
        else:
            result = json.loads(self.recognizer.PartialResult())
            text = result.get("partial", "").lower()

        # ─────────────────────────
        # Wake word detection
        # ─────────────────────────
        if (
            voice_enabled.get(self.guild_id, False)
            and not self.ben_activated
            and any(w in text for w in WAKE_WORDS)
        ):
            print(f"[WakeWord] Activated by user {user_id}")
            self.ben_activated = True
            self.active_user_id = user_id
            self.last_loud_time = now
            self.recognizer = self._new_recognizer()
            return

        # ─────────────────────────
        # Ignore others after wake
        # ─────────────────────────
        if not self.ben_activated or user_id != self.active_user_id:
            return

        # ─────────────────────────
        # Per-user speech detection
        # ─────────────────────────
        volume = pcm_rms(pcm)

        noise_floor = self.noise_floor_by_user.get(user_id, 0.0)

        if noise_floor == 0.0:
            noise_floor = volume
        elif not self.speech_active:
            noise_floor = noise_floor * 0.95 + volume * 0.05

        self.noise_floor_by_user[user_id] = noise_floor

        is_speech = volume > noise_floor * 1.8

        if is_speech:
            self.last_loud_time = now
            self.speech_active = True

            if self.speech_start_time is None:
                self.speech_start_time = now
            else:
                self.total_speech_time += now - self.speech_start_time
                self.speech_start_time = now
        else:
            self.speech_active = False


async def monitor_silence(
    guild_id: int,
    vc: discord.VoiceClient,
    sink: BenSink
):
    while vc.is_connected():
        await asyncio.sleep(CHECK_INTERVAL)

        # If recording was stopped externally, terminate this monitor task
        if not getattr(vc, "recording", False):
            print(f"[Monitor] Recording stopped for guild {guild_id}. Terminating monitor task.")
            break

        if not voice_enabled.get(guild_id, False):
            continue
        if vc.is_playing():
            continue
        if not sink.ben_activated:
            continue

        now = time.monotonic()

        # ─────────────────────────
        # Wake acknowledgment
        # ─────────────────────────
        if not sink.ack_played:
            sink.ack_played = True

        # ─────────────────────────
        # Reset if no speech
        # ─────────────────────────
        if now - sink.last_loud_time > MAX_IDLE_AFTER_WAKE:
            sink.reset_session(full=True)
            continue

        # ─────────────────────────
        # Wait for silence
        # ─────────────────────────
        if now - sink.last_loud_time < SILENCE_SECONDS:
            continue

        # ─────────────────────────
        # Ben answers (never interruptible)
        # ─────────────────────────
        answer = pick_weighted_ben_answer()
        if answer:
            await play_mp3(vc, answer)

        sink.reset_session(full=True)
