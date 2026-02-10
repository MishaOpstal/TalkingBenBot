import asyncio

import discord

from voice_call.voice_watch import BenSink, monitor_silence


async def start_listening(
        vc: discord.VoiceClient,
        ctx: discord.ApplicationContext = None
):
    async def finished_callback(sink, *args):
        pass

    if getattr(vc, "recording", False):
        try:
            vc.stop_recording()
            # Brief pause to let internal cleanup happen
            await asyncio.sleep(0.5)
        except Exception:
            pass

    sink = BenSink(ctx.guild_id)
    try:
        vc.start_recording(sink, finished_callback)
    except Exception:
        if ctx:
            await ctx.followup.send("❌ Could not start recording. Ben might be in a weird state, try `/hangup`.")
        return False

    asyncio.create_task(monitor_silence(ctx.guild_id, vc, sink))

    return True
