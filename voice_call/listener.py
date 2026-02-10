import asyncio
from typing import Union

import discord

from voice_call.voice_watch import BenSink, monitor_silence


async def start_listening(
        vc: discord.VoiceClient,
        context_id: Union[int, str],
        ctx: discord.ApplicationContext = None
):
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
    except Exception as e:
        print(f"[Listener] Error starting recording: {e}")
        if ctx:
            await ctx.followup.send("❌ Could not start recording. Ben might be in a weird state, try `/hangup`.")
        return False

    # Store the monitor task on the sink so we can cancel it later
    sink.monitor_task = asyncio.create_task(monitor_silence(context_id, vc, sink))

    return True