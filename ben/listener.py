"""Turning everyone's voice audio into "Ben should answer now".

py-cord calls BenListener.write() from its own thread for every 20 ms of audio per person.
That only drops the audio in a queue; a separate worker thread runs the Conversation,
so speech recognition can never stall Discord's audio receiving.
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field

import discord

from .guild_settings import GuildSettings
from .speech import Heard, SpeechModel, WakeSpotter, discord_to_16k, rms

log = logging.getLogger("ben.listener")

FRAME_SECONDS = 0.02
# Vosk gets audio in 100 ms chunks instead of 20 ms: same accuracy, far less overhead.
CHUNK_SAMPLES = 1600
# Below this loudness it's never speech (int16 RMS).
MIN_SPEECH_RMS = 180.0
# "always" mode: how much someone must say before it counts as a question.
MIN_UTTERANCE_SECONDS = 0.5
# After "Ben": how much more must be said before it counts as the question.
MIN_QUESTION_SECONDS = 0.3
# Someone said only "Ben" and then nothing: answer anyway after this long.
WAIT_FOR_QUESTION_SECONDS = 2.5
# Recognised "Ben" only at the end of a sentence this long: the question was in it.
LONG_SENTENCE_SECONDS = 0.9
# No audio packets for this long = they stopped talking (Discord stops sending when you're quiet).
PACKET_GAP_SECONDS = 0.25
# Forget people we haven't heard in a while (frees their recognizer).
FORGET_SPEAKER_SECONDS = 300.0


@dataclass
class Speaker:
    user_id: int
    spotter: WakeSpotter | None = None
    pending: list = field(default_factory=list)
    pending_samples: int = 0
    noise_floor: float = 300.0
    last_packet: float = 0.0
    last_voice: float = 0.0
    utterance_voiced: float = 0.0

    def is_voiced(self, level: float) -> bool:
        if level < self.noise_floor:
            self.noise_floor = level * 0.5 + self.noise_floor * 0.5
        else:
            self.noise_floor += (level - self.noise_floor) * 0.002
        return level > max(MIN_SPEECH_RMS, self.noise_floor * 2.5)


class Conversation:
    """Decides when Ben answers. Pure logic (no Discord), so it can be tested with audio files."""

    def __init__(
        self,
        speech: SpeechModel,
        get_settings: Callable[[], GuildSettings],
        on_answer: Callable[[int], None],
    ) -> None:
        self.speech = speech
        self.get_settings = get_settings
        self.on_answer = on_answer
        self.speakers: dict[int, Speaker] = {}
        self.busy = False  # Ben is talking, ignore everyone
        self.active_user: int | None = None
        self.wake_time = 0.0
        self.question_voiced = 0.0
        self._strictness: str | None = None
        # Recognizers may only be touched by the listener thread, so other threads ask for a reset.
        self._reset_requested = threading.Event()

    # ───────── input ─────────
    def feed(self, user_id: int, pcm: bytes, now: float) -> None:
        if self._reset_requested.is_set():
            self._do_reset()
        if self.busy:
            return
        settings = self.get_settings()
        if not settings.listening:
            return

        if settings.strictness != self._strictness:
            # strictness changed via /settings: rebuild recognizers lazily
            self._strictness = settings.strictness
            for sp in self.speakers.values():
                sp.spotter = None

        sp = self.speakers.get(user_id)
        if sp is None:
            sp = self.speakers[user_id] = Speaker(user_id)

        samples = discord_to_16k(pcm)
        voiced = sp.is_voiced(rms(samples))
        sp.last_packet = now
        if voiced:
            sp.last_voice = now
            sp.utterance_voiced += FRAME_SECONDS

        if self.active_user is not None:
            if user_id == self.active_user and voiced and now > self.wake_time:
                self.question_voiced += FRAME_SECONDS
            return

        if settings.wake_mode == "always":
            if sp.utterance_voiced >= MIN_UTTERANCE_SECONDS:
                self._wake(user_id, now, needs_question=False)
            return

        # "name" mode: run the wake word spotter on 100 ms chunks
        sp.pending.append(samples)
        sp.pending_samples += samples.size
        if sp.pending_samples < CHUNK_SAMPLES:
            return
        chunk = b"".join(s.tobytes() for s in sp.pending)
        sp.pending.clear()
        sp.pending_samples = 0

        if sp.spotter is None:
            sp.spotter = self.speech.spotter(settings.strictness)
        heard = sp.spotter.feed(chunk)
        if heard:
            self._wake_at_end(user_id, sp, heard)

    # ───────── timers (called ~20x per second) ─────────
    def tick(self, now: float) -> None:
        if self._reset_requested.is_set():
            self._do_reset()
        if self.busy:
            return
        settings = self.get_settings()

        for uid, sp in list(self.speakers.items()):
            stopped = now - sp.last_packet > PACKET_GAP_SECONDS
            if stopped and sp.spotter is not None and self.active_user is None:
                heard = None
                if sp.pending:
                    chunk = b"".join(s.tobytes() for s in sp.pending)
                    sp.pending.clear()
                    sp.pending_samples = 0
                    heard = sp.spotter.feed(chunk)
                heard = heard or sp.spotter.flush()
                if heard:
                    self._wake_at_end(uid, sp, heard)
            if now - sp.last_voice > settings.answer_delay:
                sp.utterance_voiced = 0.0
            if now - sp.last_packet > FORGET_SPEAKER_SECONDS:
                del self.speakers[uid]

        if self.active_user is None:
            return

        sp = self.speakers.get(self.active_user)
        silence = now - (sp.last_voice if sp else self.wake_time)
        if silence < settings.answer_delay:
            return

        asked = self.question_voiced >= MIN_QUESTION_SECONDS
        if asked or now - self.wake_time >= WAIT_FOR_QUESTION_SECONDS:
            user = self.active_user
            log.debug("Answering user %s (question %.1fs)", user, self.question_voiced)
            self.busy = True
            self.active_user = None
            self.on_answer(user)

    # ───────── state ─────────
    def _wake(self, user_id: int, now: float, *, needs_question: bool) -> None:
        log.info("Ben heard his name from user %s", user_id)
        self.active_user = user_id
        self.wake_time = now
        self.question_voiced = 0.0 if needs_question else MIN_QUESTION_SECONDS
        sp = self.speakers[user_id]
        if sp.spotter is not None:
            sp.spotter.reset()
        sp.pending.clear()
        sp.pending_samples = 0

    def _wake_at_end(self, user_id: int, sp: Speaker, heard: Heard) -> None:
        # Vosk recognises Ben once a sentence (or a pause) ends. If more words came after "Ben"
        # ("Ben, ben je gek?") the question was in it: answer after the delay.
        # If it was just "Ben", wait for the question.
        asked = heard.question_included or sp.utterance_voiced >= LONG_SENTENCE_SECONDS
        self._wake(user_id, sp.last_voice, needs_question=not asked)

    def ben_done_talking(self) -> None:
        """Ben finished his answer: start listening for a fresh "Ben". Safe from any thread."""
        self.active_user = None
        self._reset_requested.set()
        self.busy = False

    def reset(self) -> None:
        self.ben_done_talking()

    def _do_reset(self) -> None:
        self._reset_requested.clear()
        for sp in self.speakers.values():
            if sp.spotter is not None:
                sp.spotter.reset()
            sp.pending.clear()
            sp.pending_samples = 0
            sp.utterance_voiced = 0.0
        self.active_user = None


class BenListener(discord.sinks.Sink):
    """The py-cord sink. Hands audio to a worker thread and stores nothing."""

    def __init__(self, conversation: Conversation) -> None:
        super().__init__()
        self.conversation = conversation
        self.queue: queue.Queue[tuple[int, bytes, float]] = queue.Queue(maxsize=500)
        self._stop = threading.Event()
        self._worker = threading.Thread(target=self._run, name="ben-listener", daemon=True)
        self._worker.start()

    def write(self, data, user) -> None:  # called by py-cord's receive thread, must never raise
        try:
            if user is None or getattr(user, "bot", False):
                return
            pcm = getattr(data, "pcm", data)
            if pcm:
                self.queue.put_nowait((user.id, pcm, time.monotonic()))
        except queue.Full:
            pass  # worker is behind, dropping a frame is fine
        except Exception:
            log.exception("Error receiving audio")

    def cleanup(self) -> None:  # called by py-cord when recording stops
        self.stop()

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        conv = self.conversation
        next_tick = 0.0
        while not self._stop.is_set():
            try:
                user_id, pcm, t = self.queue.get(timeout=0.05)
                conv.feed(user_id, pcm, t)
            except queue.Empty:
                pass
            except Exception:
                log.exception("Error processing audio")
            now = time.monotonic()
            if now >= next_tick:
                next_tick = now + 0.05
                try:
                    conv.tick(now)
                except Exception:
                    log.exception("Error in conversation timer")
