import os
import random
import asyncio
import discord

BASE_PATH = "assets/sounds"

CALL_PATH = os.path.join(BASE_PATH, "telephone", "call")
HANG_UP_PATH = os.path.join(BASE_PATH, "telephone", "hang_up")
ANSWER_PATH = os.path.join(BASE_PATH, "answers")
YAPPING_PATH = os.path.join(BASE_PATH, "yapping")


def get_audio_files(path: str) -> list[str]:
    if not os.path.isdir(path):
        return []

    return [
        os.path.join(path, f)
        for f in os.listdir(path)
        if f.lower().endswith(".mp3")
    ]


def pick_random_from(path: str) -> str | None:
    files = get_audio_files(path)
    if not files:
        return None

    return random.choice(files)


def pick_weighted_ben_answer() -> str | None:
    yes = os.path.join(ANSWER_PATH, "yes.mp3")
    no = os.path.join(ANSWER_PATH, "no.mp3")
    yaps = get_audio_files(YAPPING_PATH)

    weighted_pool: list[str] = []

    if os.path.isfile(yes):
        weighted_pool.extend([yes] * 10)

    if os.path.isfile(no):
        weighted_pool.extend([no] * 10)

    weighted_pool.extend(yaps * 2)

    if not weighted_pool:
        return None

    return random.choice(weighted_pool)


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
    Ensures the bot is unsuppressed in a Stage Channel.
    Returns True if unsuppressed or not in a stage channel, False if it failed.
    """
    me = guild.me
    if not me or not me.voice or not isinstance(me.voice.channel, discord.StageChannel):
        return True

    if not me.voice.suppress:
        return True

    # Check permissions: Mute Members is required to unsuppress oneself
    if not me.guild_permissions.mute_members:
        print(f"[Stage Error] Missing 'Mute Members' permission in {guild.name} to unsuppress.")
        return False

    try:
        await me.edit(suppress=False)
        # Wait a bit for the state to propagate
        for _ in range(10):
            if me.voice and not me.voice.suppress:
                return True
            await asyncio.sleep(0.1)
        return not me.voice.suppress if me.voice else False
    except discord.Forbidden:
        print(f"[Stage Error] 403 Forbidden when unsuppressing in {guild.name}. Missing Access.")
        return False
    except Exception as e:
        print(f"[Stage Error] Failed to unsuppress in {guild.name}: {e}")
        return False