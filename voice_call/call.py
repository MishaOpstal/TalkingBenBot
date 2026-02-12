import asyncio
import os
from typing import Union

import discord

from audio import (
    pick_random_from,
    play_mp3,
    play_mp3_sequence,
    ensure_unsuppressed,
    AudioPlaybackFailed,
    SoundNotFound,
)
from helpers.audio_helper import CALL_PATH, HANG_UP_PATH
from voice_call.listener import start_listening


# Define voice exceptions locally to avoid circular imports
class VoiceException(Exception):
    """Base exception for voice-related errors"""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class VoiceJoinFailed(VoiceException):
    """Raised when joining a voice channel fails"""
    pass


class VoiceNotConnected(VoiceException):
    """Raised when attempting an operation that requires voice connection"""
    pass


class RecordingStartFailed(VoiceException):
    """Raised when starting audio recording fails"""
    pass


async def join_call(
        channel: discord.VoiceChannel | discord.StageChannel,
        vc: discord.VoiceClient,
        context_id: Union[int, str],
        ctx: discord.ApplicationContext = None
):
    """
    Join a voice channel and start listening

    Args:
        channel: Voice or stage channel to join
        vc: Existing voice client (if any)
        context_id: Guild ID or DM context string
        ctx: Application context for responses

    Raises:
        VoiceJoinFailed: If failed to join the channel
        RecordingStartFailed: If failed to start recording
    """
    # ── Heal ghost connections ──
    if vc and not vc.is_connected():
        try:
            await vc.disconnect(force=True)
        except Exception:
            pass
        vc = None

    # ── Connect / move ──
    try:
        if not vc:
            vc = await channel.connect(reconnect=True)
        else:
            await vc.move_to(channel)
    except discord.ClientException as e:
        raise VoiceJoinFailed(f"Failed to connect to voice channel: {e}")
    except discord.opus.OpusNotLoaded:
        raise VoiceJoinFailed("Opus library not loaded. Cannot join voice channel.")
    except Exception as e:
        raise VoiceJoinFailed(f"Unexpected error joining voice channel: {e}")

    # ── Handle Stage Channel Join ──
    is_stage = isinstance(channel, discord.StageChannel)
    if is_stage:
        # Give Discord a moment to process the connection
        await asyncio.sleep(0.5)

        # Note: Stage channels only exist in guilds, not DMs
        try:
            success = await ensure_unsuppressed(ctx.guild)
            if not success:
                if ctx:
                    await ctx.followup.send(
                        "⚠️ Ben joined but may not be able to speak. Try manually promoting him to speaker.")
        except Exception as e:
            print(f"[Stage Error] Failed to unsuppress: {e}")
            if ctx:
                await ctx.followup.send(
                    "⚠️ Ben joined but encountered an error becoming a speaker.")

        # Extra wait for Stage Channel to fully establish speaker state
        # This is critical - stage channels need time to propagate permissions
        await asyncio.sleep(1.5)

    # ── Play call sequence (ORDERED, FULL PATHS) ──
    try:
        call_sequence = sorted(
            os.path.join(CALL_PATH, f)
            for f in os.listdir(CALL_PATH)
            if f.lower().endswith(".mp3")
        )

        if call_sequence:
            await play_mp3_sequence(vc, call_sequence)

            # CRITICAL: Wait for audio to finish before starting recording
            # This prevents the recording from interfering with playback
            if is_stage:
                # Extra delay for Stage Channels to ensure audio completed
                await asyncio.sleep(0.8)
    except (SoundNotFound, AudioPlaybackFailed) as e:
        print(f"[Call Audio Warning] Failed to play call sequence: {e}")
        # Continue even if call audio fails
    except Exception as e:
        print(f"[Call Audio Error] Unexpected error playing call sequence: {e}")

    if not vc.is_connected():
        if ctx:
            await ctx.followup.send("❌ Failed to connect to voice channel.")
        raise VoiceJoinFailed("Voice client disconnected unexpectedly")

    try:
        success = await start_listening(vc, context_id, ctx)
        if not success:
            raise RecordingStartFailed("Failed to start listening")
    except RecordingStartFailed:
        raise
    except Exception as e:
        raise RecordingStartFailed(f"Unexpected error starting listener: {e}")

    if ctx:
        await ctx.followup.send("📞 Ben joined the call.")


async def reconnect_call(bot: discord.Bot):
    """
    Attempt to reconnect to a previously connected voice channel if we detect
    we were still active on an older instance

    Args:
        bot: Discord bot instance
    """
    for guild in bot.guilds:
        # Check if bot is in a voice channel in this guild
        bot_member = guild.me
        if not bot_member or not bot_member.voice or not bot_member.voice.channel:
            continue

        channel = bot_member.voice.channel

        # Get or create voice client
        vc = guild.voice_client

        # Use guild ID as context_id for reconnections
        context_id = str(guild.id)

        try:
            await join_call(channel, vc, context_id)
            print(f"[Reconnect] Successfully reconnected to {channel.name} in {guild.name}")
        except VoiceException as e:
            print(f"[Reconnect Error] Failed to reconnect to {guild.name}: {e}")
        except Exception as e:
            print(f"[Reconnect Error] Unexpected error reconnecting to {guild.name}: {e}")


async def leave_call(vc: discord.VoiceClient):
    """
    Safely disconnect from voice call with proper cleanup.
    This function ensures the sink and monitor task are properly cleaned up
    before disconnecting to prevent race conditions.

    Args:
        vc: Discord voice client

    Raises:
        VoiceNotConnected: If voice client is not connected
    """
    if not vc or not vc.is_connected():
        raise VoiceNotConnected("Voice client is not connected")

    # Play hangup sound first
    try:
        hang = pick_random_from(HANG_UP_PATH)
        if hang:
            await play_mp3(vc, hang)
            await asyncio.sleep(0.5)
    except (SoundNotFound, AudioPlaybackFailed) as e:
        print(f"[Hangup Audio Warning] Failed to play hangup sound: {e}")
        # Continue with hangup even if sound fails
    except Exception as e:
        print(f"[Hangup Audio Error] Unexpected error playing hangup sound: {e}")

    # Stop recording and clean up sink BEFORE disconnecting
    # This prevents the sink from processing audio during cleanup
    try:
        if getattr(vc, "recording", False):
            # Get the sink before stopping recording
            sink = vc.sink

            # Cancel the monitor task first to prevent it from interfering
            if sink and hasattr(sink, 'monitor_task') and sink.monitor_task:
                sink.monitor_task.cancel()
                try:
                    await sink.monitor_task
                except asyncio.CancelledError:
                    pass
                except Exception as e:
                    print(f"[Leave] Error canceling monitor task: {e}")

            # Now stop recording - this will trigger the finished_callback
            vc.stop_recording()

            # Give the recording system time to finish cleanup
            await asyncio.sleep(0.3)

            # Clean up the sink explicitly
            if sink and hasattr(sink, 'cleanup'):
                try:
                    sink.cleanup()
                except Exception as e:
                    print(f"[Leave] Error during sink cleanup: {e}")
    except Exception as e:
        print(f"[Leave] Error stopping recording: {e}")

    # Now it's safe to disconnect
    try:
        await vc.disconnect(force=True)
    except Exception as e:
        print(f"[Leave] Error disconnecting: {e}")
        raise VoiceException(f"Failed to disconnect from voice channel: {e}")