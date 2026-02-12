import asyncio
import os
import random
import re
from typing import Union

import discord

from helpers.audio_helper import get_audio_files, ANSWER_PATH, YAPPING_PATH, YES_PATH, NO_PATH
from helpers.config_helper import get_config
from exceptions import SoundNotFound, AudioPlaybackFailed


def pick_random_from(path: str) -> str | None:
    """
    Pick a random audio file from a directory.

    Args:
        path: Directory path to search for audio files

    Returns:
        Random file path or None if no files found

    Raises:
        SoundNotFound: If the directory doesn't exist or contains no audio files
    """
    files = get_audio_files(path)
    if not files:
        return None

    return random.choice(files)


def pick_weighted_ben_answer(context_id: Union[int, str]) -> str | None:
    """
    Pick a Ben answer based on configurable weights.

    Args:
        context_id: Either a guild_id or a DM context string "direct_messages.{user_id}"

    Weights are configured in config.py:
    - "yes": weight for yes.mp3
    - "no": weight for no.mp3
    - "yapping": weight for EACH yapping file

    Example: yes=10, no=10, yapping=2 with 5 yapping files
    → Pool has 10 yes + 10 no + 10 yapping (2*5) = 30 total
    → Yes: 33%, No: 33%, Yapping: 33% (distributed among 5 files)

    Returns:
        Path to selected audio file or None if no sounds available
    """
    yaps = get_audio_files(YAPPING_PATH)

    weighted_pool: list[str] = []

    cfg = get_config(context_id)

    # Add yes with configured weight
    if os.path.isfile(YES_PATH):
        yes_weight = cfg.yes_weight
        weighted_pool.extend([YES_PATH] * yes_weight)

    # Add no with configured weight
    if os.path.isfile(NO_PATH):
        no_weight = cfg.no_weight
        weighted_pool.extend([NO_PATH] * no_weight)

    # Add each yapping file with configured weight
    yapping_weight = cfg.yapping_weight
    weighted_pool.extend(yaps * yapping_weight)

    if not weighted_pool:
        return None

    return random.choice(weighted_pool)


def get_specific_answer(answer_type: str) -> str | None:
    """
    Get a specific answer file based on type.

    Args:
        answer_type: "yes", "no", or "yap"

    Returns:
        Path to the audio file, or None if not found

    Raises:
        SoundNotFound: If the requested answer type file doesn't exist
    """
    if answer_type == "yes":
        if not os.path.isfile(YES_PATH):
            raise SoundNotFound(f"Yes sound file not found at {YES_PATH}")
        return YES_PATH
    elif answer_type == "no":
        if not os.path.isfile(NO_PATH):
            raise SoundNotFound(f"No sound file not found at {NO_PATH}")
        return NO_PATH
    elif answer_type == "yap":
        result = pick_random_from(YAPPING_PATH)
        if not result:
            raise SoundNotFound(f"No yapping sounds found in {YAPPING_PATH}")
        return result

    return None


def extract_message_from_filename(filepath: str) -> str:
    """
    Extract a chat message from an audio filename.

    Format: "filename [Message here.].mp3" -> "Message here."
    If no brackets, uses the filename without extension.

    Args:
        filepath: Full path to the audio file

    Returns:
        The extracted message string
    """
    if not filepath:
        return "..."

    # Get the filename without path
    filename = os.path.basename(filepath)

    # Look for text in brackets
    match = re.search(r'\[(.*?)]', filename)
    if match:
        return match.group(1)

    # Otherwise, return filename without extension
    name_without_ext = os.path.splitext(filename)[0]
    return name_without_ext.capitalize()


async def play_mp3(vc: discord.VoiceClient, file_path: str, delay: float = 0.025) -> None:
    """
    Play an MP3 file into a Discord voice channel.
    Safe for headless / Docker environments.

    Args:
        vc: Discord voice client
        file_path: Path to the MP3 file
        delay: Delay between playback checks in seconds

    Raises:
        SoundNotFound: If the audio file doesn't exist
        AudioPlaybackFailed: If playback fails
    """
    if not file_path:
        raise SoundNotFound("No file path provided")

    if not os.path.isfile(file_path):
        raise SoundNotFound(f"Audio file not found: {file_path}")

    if not vc or not vc.is_connected():
        raise AudioPlaybackFailed("Voice client not connected")

    if vc.is_playing():
        return

    # ── Handle Stage Channels ──
    # If in a stage channel, we must ensure we are not suppressed (are a speaker)
    if isinstance(vc.channel, discord.StageChannel):
        try:
            await ensure_unsuppressed(vc.guild)
        except Exception as e:
            raise AudioPlaybackFailed(f"Failed to unsuppress in stage channel: {e}")

    try:
        audio_source = discord.FFmpegPCMAudio(
            file_path,
            options="-loglevel panic"
        )

        vc.play(audio_source)

        # Wait until playback finishes
        while vc.is_playing():
            await asyncio.sleep(delay)
    except Exception as e:
        raise AudioPlaybackFailed(f"Failed to play audio: {e}")


async def play_mp3_sequence(vc: discord.VoiceClient, files: list[str]) -> None:
    """
    Play a sequence of MP3 files into a Discord voice channel.
    Safe for headless / Docker environments.

    Args:
        vc: Discord voice client
        files: List of file paths to play in sequence

    Raises:
        SoundNotFound: If any audio file doesn't exist
        AudioPlaybackFailed: If playback fails
    """
    for file in files:
        try:
            await play_mp3(vc, file, .7)
        except SoundNotFound as e:
            print(f"[Audio Warning] Skipping missing file in sequence: {e}")
            continue
        except AudioPlaybackFailed as e:
            print(f"[Audio Warning] Failed to play file in sequence: {e}")
            continue


async def ensure_unsuppressed(guild: discord.Guild) -> bool:
    """
    Ensures the bot is unsuppressed in a Stage Channel and can speak.
    Returns True if unsuppressed or not in a stage channel, False if it failed.

    CRITICAL: Only call request_to_speak() when suppressed (in audience).
    Calling it when already a speaker makes you raise your hand and go back to audience!

    Args:
        guild: The Discord guild

    Returns:
        True if successfully unsuppressed, False otherwise
    """
    me = guild.me
    if not me or not me.voice or not isinstance(me.voice.channel, discord.StageChannel):
        return True

    # Check permissions: Mute Members is required to unsuppress oneself
    if not me.guild_permissions.mute_members:
        print(f"[Stage Error] Missing 'Mute Members' permission in {guild.name} to unsuppress.")
        return False

    try:
        # Refresh member state to ensure we have current info
        await asyncio.sleep(0.1)
        me = guild.me

        # If already unsuppressed (already a speaker), we're done!
        if me.voice and not me.voice.suppress:
            print(f"[Stage] Already a speaker in {guild.name}")
            return True

        print(f"[Stage] Currently suppressed in {guild.name}, becoming speaker...")

        # CRITICAL FIX: Only request to speak if we're currently suppressed
        # This prevents the "raise hand" loop
        if me.voice and me.voice.suppress:
            # First, try to directly unsuppress with Mute Members permission
            # This is more reliable than request_to_speak() for bots
            await me.edit(suppress=False)
            print(f"[Stage] Edited suppress=False in {guild.name}")

            # Wait for the state to propagate
            for i in range(25):  # Give it up to 2.5 seconds
                await asyncio.sleep(0.1)
                me = guild.me  # Refresh member object
                if me.voice and not me.voice.suppress:
                    print(f"[Stage] Successfully became speaker in {guild.name}")
                    return True

            # If direct unsuppress didn't work, try request_to_speak as fallback
            print(f"[Stage] Direct unsuppress didn't work, trying request_to_speak...")
            await me.request_to_speak()
            await asyncio.sleep(0.3)

            # Try editing again
            me = guild.me
            if me.voice and me.voice.suppress:
                await me.edit(suppress=False)

            # Final wait
            for i in range(15):
                await asyncio.sleep(0.1)
                me = guild.me
                if me.voice and not me.voice.suppress:
                    print(f"[Stage] Successfully became speaker (via request) in {guild.name}")
                    return True

        me = guild.me
        final_state = not me.voice.suppress if me.voice else False
        print(f"[Stage] Final speaker state in {guild.name}: {final_state}")
        return final_state

    except discord.Forbidden:
        print(f"[Stage Error] 403 Forbidden when unsuppressing in {guild.name}. Missing permissions.")
        return False
    except Exception as e:
        print(f"[Stage Error] Failed to unsuppress in {guild.name}: {e}")
        return False