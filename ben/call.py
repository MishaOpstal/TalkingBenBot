"""One phone call with Ben in one server: joining, listening, answering, hanging up."""

from __future__ import annotations

import asyncio
import logging

import discord

from . import playback
from .guild_settings import SettingsStore
from .listener import BenListener, Conversation
from .sounds import Sounds
from .speech import SpeechModel

log = logging.getLogger("ben.call")

WATCHDOG_SECONDS = 3.0


class Call:
    def __init__(
        self,
        vc: discord.VoiceClient,
        speech: SpeechModel,
        settings: SettingsStore,
        sounds: Sounds,
    ) -> None:
        self.vc = vc
        self.guild_id = vc.guild.id
        self.settings = settings
        self.sounds = sounds
        self.loop = asyncio.get_running_loop()
        self.conversation = Conversation(
            speech, lambda: settings.get(self.guild_id), self._answer_from_thread
        )
        self.listener: BenListener | None = None
        self._secret_key: bytes | None = None
        self._watchdog: asyncio.Task | None = None
        self._talk_lock = asyncio.Lock()
        self.ended = False

    # ───────── lifecycle ─────────
    async def start(self) -> None:
        async with self._talk_lock:
            self.conversation.busy = True
            await playback.play_sequence(self.vc, self.sounds.call_sequence())
            self.conversation.ben_done_talking()
        self.start_listening()
        self._watchdog = asyncio.create_task(self._watch(), name=f"ben-watchdog-{self.guild_id}")

    async def hang_up(self, *, play_sound: bool = True) -> None:
        if self.ended:
            return
        self.ended = True
        if self._watchdog:
            self._watchdog.cancel()
        self.stop_listening()
        if play_sound and self.vc.is_connected():
            async with self._talk_lock:
                await playback.play(self.vc, self.sounds.hang_up())
        try:
            await self.vc.disconnect(force=True)
        except Exception:
            pass

    # ───────── listening ─────────
    def start_listening(self) -> None:
        if self.ended or not self.vc.is_connected():
            return
        self.stop_listening()
        self.conversation.reset()
        self.listener = BenListener(self.conversation)
        try:
            self.vc.start_recording(self.listener)
            self._secret_key = bytes(self.vc.secret_key or [])
            log.info("Listening in %s / %s", self.vc.guild.name, self.vc.channel)
        except Exception:
            log.exception("Could not start listening")
            self.listener.stop()
            self.listener = None

    def stop_listening(self) -> None:
        if self.listener is not None:
            self.listener.stop()
            self.listener = None
        try:
            if self.vc.is_recording():
                self.vc.stop_recording()
        except Exception:
            pass

    async def _watch(self) -> None:
        """Restart listening if py-cord's receiver died or the voice connection was renewed."""
        while not self.ended:
            await asyncio.sleep(WATCHDOG_SECONDS)
            if not self.vc.is_connected():
                continue
            key = bytes(self.vc.secret_key or [])
            if not self.vc.is_recording() or (self._secret_key and key != self._secret_key):
                log.info("Voice receiver stopped or reconnected, restarting it")
                self.start_listening()

    # ───────── answering ─────────
    def _answer_from_thread(self, user_id: int) -> None:
        # called from the listener thread
        self.loop.call_soon_threadsafe(lambda: asyncio.create_task(self.answer()))

    async def answer(self) -> str | None:
        """Ben gives a random answer. Returns "yes", "no" or "yapping"."""
        if self.ended:
            return None
        async with self._talk_lock:
            self.conversation.busy = True
            try:
                picked = self.sounds.pick_answer(self.settings.get(self.guild_id))
                if picked is None:
                    return None
                kind, path = picked
                await playback.play(self.vc, path)
                return kind
            finally:
                self.conversation.ben_done_talking()


class CallManager:
    """All active calls, one per server."""

    def __init__(self, speech: SpeechModel, settings: SettingsStore, sounds: Sounds) -> None:
        self.speech = speech
        self.settings = settings
        self.sounds = sounds
        self.calls: dict[int, Call] = {}

    def get(self, guild_id: int) -> Call | None:
        call = self.calls.get(guild_id)
        if call and (call.ended or not call.vc.is_connected()):
            return None
        return call

    async def start(self, channel: discord.VoiceChannel | discord.StageChannel) -> Call:
        guild = channel.guild
        await self.end(guild.id, play_sound=False)

        vc = guild.voice_client
        if vc is not None:  # leftover/ghost connection
            try:
                await vc.disconnect(force=True)
            except Exception:
                pass

        vc = await channel.connect(reconnect=True, timeout=20)
        if isinstance(channel, discord.StageChannel):
            await asyncio.sleep(0.5)
            await playback.become_speaker(guild)

        call = self.calls[guild.id] = Call(vc, self.speech, self.settings, self.sounds)
        await call.start()
        return call

    async def end(self, guild_id: int, *, play_sound: bool = True) -> bool:
        call = self.calls.pop(guild_id, None)
        if call is None:
            return False
        await call.hang_up(play_sound=play_sound)
        return True

    async def end_all(self) -> None:
        for gid in list(self.calls):
            await self.end(gid, play_sound=False)
