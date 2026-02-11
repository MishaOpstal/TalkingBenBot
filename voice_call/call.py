import asyncio
import os
from typing import Union

import discord

from audio import (
    pick_random_from,
    play_mp3,
    play_mp3_sequence,
    ensure_unsuppressed,
)
from helpers.audio_helper import CALL_PATH, HANG_UP_PATH
from voice_call.listener import start_listening


async def join_call(
        channel: discord.VoiceChannel | discord.StageChannel,
        vc: discord.VoiceClient,
        context_id: Union[int, str],
        ctx: discord.ApplicationContext = None
):
    # ── Heal ghost connections ──
    if vc and not vc.is_connected():
        try:
            await vc.disconnect(force=True)
        except Exception:
            pass
        vc = None

    # ── Connect / move ──
    if not vc:
        vc = await channel.connect(reconnect=True)
    else:
        await vc.move_to(channel)

    # ── Handle Stage Channel Join ──
    is_stage = isinstance(channel, discord.StageChannel)
    if is_stage:
        # Give Discord a moment to process the connection
        await asyncio.sleep(0.5)

        # Note: Stage channels only exist in guilds, not DMs
        success = await ensure_unsuppressed(ctx.guild)
        if not success:
            if ctx:
                await ctx.followup.send(
                    "⚠️ Ben joined but may not be able to speak. Try manually promoting him to speaker.")

        # Extra wait for Stage Channel to fully establish speaker state
        # This is critical - stage channels need time to propagate permissions
        await asyncio.sleep(1.5)

    # ── Play call sequence (ORDERED, FULL PATHS) ──
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

    if not vc.is_connected():
        if ctx:
            await ctx.followup.send("❌ Failed to connect to voice channel.")
        return

    if not await start_listening(vc, context_id, ctx):
        return

    if ctx:
        await ctx.followup.send("📞 Ben joined the call.")


async def reconnect_call(bot: discord.Bot):
    # ─────────────────────────────────────────────
    # Reconnect to existing VCs
    # ─────────────────────────────────────────────
    """
    Attempt to reconnect to a previously connected voice channel if we detect
    we were still active on an older instance
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
        await join_call(channel, vc, context_id)


async def leave_call(vc: discord.VoiceClient):
    """
    Safely disconnect from voice call with proper cleanup.
    This function ensures the sink and monitor task are properly cleaned up
    before disconnecting to prevent race conditions.
    """
    # Play hangup sound first
    hang = pick_random_from(HANG_UP_PATH)
    if hang:
        await play_mp3(vc, hang)
        await asyncio.sleep(0.5)

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