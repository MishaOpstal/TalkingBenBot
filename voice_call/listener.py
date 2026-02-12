import asyncio
from typing import Union

import discord

from voice_call.voice_watch import BenSink, monitor_silence
from exceptions import RecordingStartFailed


async def start_listening(
        vc: discord.VoiceClient,
        context_id: Union[int, str],
        ctx: discord.ApplicationContext = None
) -> bool:
    """
    Start listening to voice channel audio

    Args:
        vc: Discord voice client
        context_id: Guild ID or DM context string
        ctx: Application context for responses

    Returns:
        True if successfully started listening, False otherwise

    Raises:
        RecordingStartFailed: If recording fails to start
    """

    async def finished_callback(sink, *args):
        # Clean up the monitor task when recording stops
        if hasattr(sink, 'monitor_task') and sink.monitor_task:
            sink.monitor_task.cancel()
            try:
                await sink.monitor_task
            except asyncio.CancelledError:
                pass

    # Stop existing recording completely
    if getattr(vc, "recording", False):
        try:
            # Get the old sink to cancel its monitor task
            old_sink = vc.sink
            if hasattr(old_sink, 'monitor_task') and old_sink.monitor_task:
                old_sink.monitor_task.cancel()
                try:
                    await old_sink.monitor_task
                except asyncio.CancelledError:
                    pass

            vc.stop_recording()
            # Brief pause to let internal cleanup happen
            await asyncio.sleep(0.5)
        except Exception as e:
            print(f"[Listener] Error stopping old recording: {e}")

    sink = BenSink(context_id)
    try:
        vc.start_recording(sink, finished_callback)
    except discord.ClientException as e:
        error_msg = f"Discord client error starting recording: {e}"
        print(f"[Listener] {error_msg}")
        if ctx:
            await ctx.followup.send("❌ Could not start recording. Ben might be in a weird state, try `/hangup`.")
        raise RecordingStartFailed(error_msg)
    except Exception as e:
        error_msg = f"Unexpected error starting recording: {e}"
        print(f"[Listener] {error_msg}")
        if ctx:
            await ctx.followup.send("❌ Could not start recording. Ben might be in a weird state, try `/hangup`.")
        raise RecordingStartFailed(error_msg)

    # Store the monitor task on the sink so we can cancel it later
    try:
        sink.monitor_task = asyncio.create_task(monitor_silence(context_id, vc, sink))
    except Exception as e:
        error_msg = f"Failed to create monitor task: {e}"
        print(f"[Listener] {error_msg}")
        # Stop the recording we just started
        try:
            vc.stop_recording()
        except Exception:
            pass
        raise RecordingStartFailed(error_msg)

    return True