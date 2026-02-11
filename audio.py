import asyncio
import os
import random
import re
from typing import Union

import discord

from helpers.audio_helper import get_audio_files, ANSWER_PATH, YAPPING_PATH
from helpers.config_helper import get_config


def pick_random_from(path: str) -> str | None:
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
    """
    answer_file_list = os.listdir(ANSWER_PATH)

    # Let's look for a file starting with yes
    yes = os.path.join(ANSWER_PATH, [f for f in answer_file_list if f.lower().startswith("yes")][0])
    no = os.path.join(ANSWER_PATH, [f for f in answer_file_list if f.lower().startswith("no")][0])

    yaps = get_audio_files(YAPPING_PATH)

    weighted_pool: list[str] = []

    cfg = get_config(context_id)

    # Add yes with configured weight
    if os.path.isfile(yes):
        yes_weight = cfg.yes_weight
        weighted_pool.extend([yes] * yes_weight)

    # Add no with configured weight
    if os.path.isfile(no):
        no_weight = cfg.no_weight
        weighted_pool.extend([no] * no_weight)

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
    """
    if answer_type == "yes":
        yes = os.path.join(ANSWER_PATH, "yes.mp3")
        return yes if os.path.isfile(yes) else None
    elif answer_type == "no":
        no = os.path.join(ANSWER_PATH, "no.mp3")
        return no if os.path.isfile(no) else None
    elif answer_type == "yap":
        return pick_random_from(YAPPING_PATH)

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
    match = re.search(r'\[(.*?)\]', filename)
    if match:
        return match.group(1)

    # Otherwise, return filename without extension
    name_without_ext = os.path.splitext(filename)[0]
    return name_without_ext.capitalize()


async def play_mp3(vc: discord.VoiceClient, file_path: str, delay: float = 0.025) -> None:
    """
    Play an MP3 file into a Discord voice channel.
    Safe for headless / Docker environments.
    """
    if not file_path or not os.path.isfile(file_path):
        return

    if not vc or not vc.is_connected():
        return

    if vc.is_playing():
        return

    # ── Handle Stage Channels ──
    # If in a stage channel, we must ensure we are not suppressed (are a speaker)
    if isinstance(vc.channel, discord.StageChannel):
        await ensure_unsuppressed(vc.guild)

    audio_source = discord.FFmpegPCMAudio(
        file_path,
        options="-loglevel panic"
    )

    vc.play(audio_source)

    # Wait until playback finishes
    while vc.is_playing():
        await asyncio.sleep(delay)


async def play_mp3_sequence(vc: discord.VoiceClient, files: list[str]) -> None:
    """
    Play a sequence of MP3 files into a Discord voice channel.
    Safe for headless / Docker environments.
    """
    for file in files:
        await play_mp3(vc, file, .7)


async def ensure_unsuppressed(guild: discord.Guild) -> bool:
    """
    Ensures the bot is unsuppressed in a Stage Channel and can speak.
    Returns True if unsuppressed or not in a stage channel, False if it failed.

    CRITICAL: Only call request_to_speak() when suppressed (in audience).
    Calling it when already a speaker makes you raise your hand and go back to audience!
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