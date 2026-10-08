"""Playing sounds in a voice channel, including the Stage channel speaker dance."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import discord

log = logging.getLogger("ben.playback")


async def become_speaker(guild: discord.Guild) -> bool:
    """Make sure Ben is a speaker (not audience) when he is in a Stage channel.

    Needs the "Mute Members" permission (or a Stage moderator role) to promote himself.
    Without it Ben raises his hand and someone has to invite him to speak.
    """
    me = guild.me
    if not me.voice or not isinstance(me.voice.channel, discord.StageChannel):
        return True
    if not me.voice.suppress:
        return True

    try:
        await me.edit(suppress=False)
    except discord.Forbidden:
        log.info("No permission to become speaker in %s, raising hand instead", guild.name)
        try:
            await me.request_to_speak()
        except discord.HTTPException:
            pass
        return False
    except discord.HTTPException as exc:
        log.warning("Could not become speaker in %s: %s", guild.name, exc)
        return False

    for _ in range(30):
        if guild.me.voice and not guild.me.voice.suppress:
            return True
        await asyncio.sleep(0.1)
    return False


async def play(vc: discord.VoiceClient, path: Path | None) -> None:
    """Play one file and wait until it is done."""
    if path is None or not vc.is_connected():
        return

    if isinstance(vc.channel, discord.StageChannel):
        await become_speaker(vc.guild)

    if vc.is_playing():
        vc.stop()

    try:
        source = discord.FFmpegOpusAudio(str(path), options="-loglevel error")
        await vc.play(source, wait_finish=True)
    except discord.ClientException as exc:
        log.warning("Could not play %s: %s", path.name, exc)


async def play_sequence(vc: discord.VoiceClient, paths: list[Path], gap: float = 0.15) -> None:
    for path in paths:
        await play(vc, path)
        await asyncio.sleep(gap)
