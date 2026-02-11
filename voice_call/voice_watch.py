import asyncio
import audioop
import json
import math
import random
import struct
import time
import os
import threading
from typing import Union, Optional

import discord
from vosk import Model, KaldiRecognizer

from audio import pick_weighted_ben_answer, play_mp3
from helpers.config_helper import get_config

# Debug voice recognition flag
DEBUG_VOICE = os.environ.get("DEBUG_VOICE", "false").lower() in ("true", "1", "yes")

# ─────────────────────────────────────────────
# Tunables
# ─────────────────────────────────────────────
MIN_SPEECH_SECONDS = 0.6
SILENCE_SECONDS = 0.35
CHECK_INTERVAL = 0.35
MAX_IDLE_AFTER_WAKE = 5.0

WAKE_WORDS = (
    "ben",
    "pen",
    "men",
    "bin",
    "baan"
)

VOSK_MODEL_PATH = "/app/models/vosk"

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
    def __init__(self, context_id: Union[int, str]):
        super().__init__(filters=None)
        self.context_id = context_id
        self.monitor_task = None  # Track the monitor task
        self._recognizer_lock = threading.Lock()  # Thread safety for recognizer access
        self.recognizer = self._new_recognizer()  # Initialize recognizer immediately
        self.reset_session(full=False)  # Don't recreate recognizer in reset
        self.config = get_config(context_id)

    # ───────── Helpers ─────────
    def _new_recognizer(self):
        recognizer = KaldiRecognizer(vosk_model, 16000)
        recognizer.SetWords(False)
        return recognizer

    def _safe_replace_recognizer(self) -> None:
        """Thread-safe recognizer replacement that cleans up old one"""
        with self._recognizer_lock:
            try:
                if self.recognizer is not None:
                    old_recognizer = self.recognizer
                    self.recognizer = self._new_recognizer()  # Create new one first
                    # Small delay to ensure any in-flight audio packets complete
                    time.sleep(0.01)
                    del old_recognizer  # Then delete old one
                else:
                    self.recognizer = self._new_recognizer()
            except Exception as e:
                print(f"[BenSink] Error replacing recognizer: {e}")
                # Make sure we always have a recognizer
                if self.recognizer is None:
                    self.recognizer = self._new_recognizer()

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
            # Thread-safe recognizer replacement
            self._safe_replace_recognizer()

    def cleanup(self):
        """Clean up resources when sink is no longer needed"""
        if self.monitor_task:
            self.monitor_task.cancel()

        # CRITICAL: Thread-safe cleanup of the recognizer
        with self._recognizer_lock:
            if hasattr(self, 'recognizer') and self.recognizer is not None:
                try:
                    old_recognizer = self.recognizer
                    self.recognizer = None
                    # Small delay to ensure write() isn't using it
                    time.sleep(0.02)
                    del old_recognizer
                except Exception as e:
                    print(f"[BenSink] Error during recognizer cleanup: {e}")

    # ───────── Audio Input ─────────
    def write(self, pcm: bytes, user_id: int) -> None:
        # Thread-safe recognizer access
        with self._recognizer_lock:
            # Safety check: make sure recognizer exists
            if not hasattr(self, 'recognizer') or self.recognizer is None:
                return

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
            try:
                if self.recognizer.AcceptWaveform(mono_16k):
                    result = json.loads(self.recognizer.Result())
                    text = result.get("text", "").lower()
                    if DEBUG_VOICE and text.strip():
                        print(f"[VoiceDebug] Final from user {user_id}: '{text}'")
                else:
                    result = json.loads(self.recognizer.PartialResult())
                    text = result.get("partial", "").lower()
                    if DEBUG_VOICE and text.strip():
                        print(f"[VoiceDebug] Partial from user {user_id}: '{text}'")
            except Exception as e:
                # Handle any recognition errors gracefully
                return

        # ─────────────────────────
        # Wake word detection (outside lock - we'll use safe replacement)
        # ─────────────────────────
        if (
                self.config.voice_enabled
                and not self.ben_activated
                and any(w in text for w in WAKE_WORDS)
        ):
            matched_word = next((w for w in WAKE_WORDS if w in text), "unknown")
            print(f"[WakeWord] Activated by user {user_id} in context {self.context_id} (detected: '{matched_word}')")
            if DEBUG_VOICE:
                print(f"[VoiceDebug] Wake word detected in text: '{text}'")
            self.ben_activated = True
            self.active_user_id = user_id
            self.last_loud_time = now

            # Thread-safe recognizer replacement
            self._safe_replace_recognizer()
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
        context_id: Union[int, str],
        vc: discord.VoiceClient,
        sink: BenSink
):
    # Import here to avoid circular import
    from voice_call.call import leave_call

    cfg = get_config(context_id)

    while vc.is_connected():
        await asyncio.sleep(CHECK_INTERVAL)

        # If recording was stopped externally, terminate this monitor task
        if not getattr(vc, "recording", False):
            print(f"[Monitor] Recording stopped for context {context_id}. Terminating monitor task.")
            break

        if not cfg.voice_enabled:
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
        # 1 in 500 chance he just hangs up
        # ─────────────────────────
        random_chance: int = random.randint(0, 500)
        if random_chance == 250:
            sink.reset_session(full=True)
            await leave_call(vc)
            continue

        # ─────────────────────────
        # Ben answers (never interruptible)
        # ─────────────────────────
        answer = pick_weighted_ben_answer(context_id)
        if answer:
            await play_mp3(vc, answer)

        sink.reset_session(full=True)