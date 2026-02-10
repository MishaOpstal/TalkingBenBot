import asyncio
import os

import discord
from discord import option

from audio import (
    pick_weighted_ben_answer,
    play_mp3,
)
from config import config, load_config, save_config
from helpers.config_helper import get_config
from voice_call.call import join_call, reconnect_call, leave_call

TOKEN = os.environ.get("DISCORD_TOKEN")
if not TOKEN:
    raise RuntimeError("DISCORD_TOKEN env var is required.")

intents = discord.Intents.default()
intents.voice_states = True
intents.members = True


def ensure_opus_loaded() -> None:
    if discord.opus.is_loaded():
        return

    candidates = [
        "libopus.so.0",
        "libopus.so",
        "opus",
    ]

    for candidate in candidates:
        try:
            discord.opus.load_opus(candidate)
            print(f"[Opus] Loaded: {candidate}")
            return
        except Exception:
            continue

    raise RuntimeError("Opus library not found. Install libopus0 / opus package.")


ensure_opus_loaded()

bot = discord.Bot(intents=intents)


@bot.event
async def on_ready():
    load_config()

    await bot.sync_commands()
    await asyncio.sleep(2)
    await reconnect_call(bot)

    print(f"Logged in as {bot.user}")


# ─────────────────────────────────────────────
# Ask Ben
# ─────────────────────────────────────────────
@bot.slash_command(description="Ask Talking Ben a question (random answer).")
@option("question", str, description="Your question")
async def ask(ctx: discord.ApplicationContext, question: str):
    await ctx.defer(ephemeral=True)

    vc = ctx.guild.voice_client
    if not vc or not vc.is_connected():
        await ctx.followup.send("Ben isn't in a voice channel. Use `/call` first.")
        return

    answer = pick_weighted_ben_answer(ctx.guild_id)
    if not answer:
        await ctx.followup.send("No answer sounds found.")
        return

    await play_mp3(vc, answer)
    await ctx.followup.send("📞 Ben answered.")


# ─────────────────────────────────────────────
# Config
# ─────────────────────────────────────────────
@bot.slash_command(description="Configure Talking Ben settings.")
@option("enable_voice", bool, description="Enable/disable voice-triggered answers", required=False)
@option("yes_weight", int, min_value=0, max_value=100, required=False)
@option("no_weight", int, min_value=0, max_value=100, required=False)
@option("yapping_weight", int, min_value=0, max_value=100, required=False)
async def config_cmd(
        ctx: discord.ApplicationContext,
        enable_voice: bool | None = None,
        yes_weight: int | None = None,
        no_weight: int | None = None,
        yapping_weight: int | None = None,
):
    await ctx.defer(ephemeral=True)

    if enable_voice is not None:
        config.set_voice_enabled(ctx.guild_id, enable_voice)

    if yes_weight is not None:
        config.set_weight(ctx.guild_id, "yes", yes_weight)

    if no_weight is not None:
        config.set_weight(ctx.guild_id, "no", no_weight)

    if yapping_weight is not None:
        config.set_weight(ctx.guild_id, "yapping", yapping_weight)

    save_config()

    cfg = get_config(ctx.guild_id)

    response = (
        f"**Talking Ben Configuration**\n\n"
        f"🎙 **voiceTalkToBen**: {cfg.voice_enabled}\n\n"
        f"**Answer Probabilities:**\n"
        f"🟢 Yes: {cfg.yes_pct:.1f}%\n"
        f"🔴 No: {cfg.no_pct:.1f}%\n"
        f"💬 Yapping: {cfg.yapping_pct:.1f}%\n\n"
        f"*Total weight pool: {cfg.total_weight}*"
    )

    await ctx.followup.send(response)


# ─────────────────────────────────────────────
# Status
# ─────────────────────────────────────────────
@bot.slash_command(description="Show current Talking Ben settings.")
async def ben_status(ctx: discord.ApplicationContext):
    cfg = get_config(ctx.guild_id)

    response = (
        f"**Talking Ben Status**\n\n"
        f"🎙 **voiceTalkToBen**: {cfg.voice_enabled}\n\n"
        f"**Answer Probabilities:**\n"
        f"🟢 Yes: {cfg.yes_pct:.1f}%\n"
        f"🔴 No: {cfg.no_pct:.1f}%\n"
        f"💬 Yapping: {cfg.yapping_pct:.1f}%\n"
    )

    await ctx.respond(response, ephemeral=True)


# ─────────────────────────────────────────────
# Call Ben
# ─────────────────────────────────────────────
@bot.slash_command(description="Call Talking Ben into your current voice channel.")
async def call(ctx: discord.ApplicationContext):
    await ctx.defer(ephemeral=True)

    member = ctx.guild.get_member(ctx.author.id) or await ctx.guild.fetch_member(ctx.author.id)

    if not member.voice or not member.voice.channel:
        await ctx.followup.send("You need to be in a voice channel to use this command.")
        return

    channel = member.voice.channel
    vc = ctx.guild.voice_client

    if vc and vc.is_connected() and getattr(vc, "recording", False):
        if vc.channel == channel:
            await ctx.followup.send("Ben is already in a call with you!")
            return
        try:
            vc.stop_recording()
        except Exception:
            pass

    await join_call(channel, vc)


# ─────────────────────────────────────────────
# Hang up
# ─────────────────────────────────────────────
@bot.slash_command(description="Hang up Talking Ben.")
async def hangup(ctx: discord.ApplicationContext):
    await ctx.defer(ephemeral=True)

    vc = ctx.guild.voice_client
    if not vc or not vc.is_connected():
        await ctx.followup.send("Ben isn't connected.")
        return

    await leave_call(vc)
    await ctx.followup.send("☎️ Ben hung up.")


# ─────────────────────────────────────────────
# Voice state handling
# ─────────────────────────────────────────────
@bot.event
async def on_voice_state_update(member, before, after):
    if member.bot:
        return

    guild = member.guild
    vc = guild.voice_client

    if not vc or not vc.is_connected():
        return

    channel = vc.channel
    if not channel:
        return

    non_bot_members = [m for m in channel.members if not m.bot]

    if len(non_bot_members) == 0:
        try:
            vc.stop_recording()
        except Exception:
            pass

        try:
            await vc.disconnect(force=True)
        except Exception:
            pass

        print(f"Auto-disconnected from empty VC in {guild.name}")


bot.run(TOKEN)
