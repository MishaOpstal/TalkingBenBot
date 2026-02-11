import asyncio
import os
import random

import discord
from discord import option

from audio import (
    pick_weighted_ben_answer,
    get_specific_answer,
    play_mp3, pick_random_from,
)
from config import config, load_config, save_config
from helpers.audio_helper import HANG_UP_PATH, NO_PATH
from helpers.sound_inventory import refresh_sound_inventory, get_message_for_sound
from helpers.config_helper import get_config, get_context_id
from voice_call.call import join_call, reconnect_call, leave_call

TOKEN = os.environ.get("DISCORD_TOKEN")
if not TOKEN:
    raise RuntimeError("DISCORD_TOKEN env var is required.")

intents = discord.Intents.default()
intents.voice_states = True
intents.members = True
intents.message_content = True  # Required to read DM content

send_params = {
    "silent": True,
    "mention_author": False
}


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
    refresh_sound_inventory()

    await bot.sync_commands()
    await asyncio.sleep(2)
    await reconnect_call(bot)

    print(f"Logged in as {bot.user}")


@bot.event
async def on_message(message):
    # Ignore bot's own messages
    if message.author == bot.user:
        return

    # Ignore system messages (cannot reply to them)
    if message.type != discord.MessageType.default:
        return

    # Ignore messages that start with / (commands)
    if message.content.startswith('/'):
        return

    # Handle DMs
    if message.guild is None:
        # Treat the message as a question to Ben
        question = message.content.strip()

        if not question:
            return

        # Get DM context ID
        context_id = f"direct_messages.{message.author.id}"

        # In DMs, we typically don't have voice clients since voice is guild-based
        vc = None

        # Pick an answer
        answer = pick_weighted_ben_answer(context_id)

        if not answer:
            await message.reply("I don't have any answers available right now.", **send_params)
            return

        # Extract message from filename
        response_text = get_message_for_sound(answer)

        # If in voice channel, play audio (unlikely in DMs, but check anyway)
        if vc and vc.is_connected():
            await play_mp3(vc, answer)

        # Send the response as plain text
        await message.reply(response_text, **send_params)
        return

    # Handle server messages that mention "Ben" (capital B)
    if "Ben" not in message.content:
        return

    # Get the question (the full message)
    question = message.content.strip()

    # Get server context ID
    context_id = str(message.guild.id)

    # Get voice client if bot is in voice channel
    vc = message.guild.voice_client

    # Pick an answer
    answer = pick_weighted_ben_answer(context_id)

    if not answer:
        return  # Silently ignore if no answers available in server

    # Extract message from filename
    response_text = get_message_for_sound(answer)

    # If in voice channel, play audio first
    if vc and vc.is_connected():
        await play_mp3(vc, answer)

    # Send the response as plain text
    await message.reply(response_text, **send_params)


# ─────────────────────────────────────────────
# Ask Ben
# ─────────────────────────────────────────────
@bot.slash_command(description="Ask Talking Ben a question (random answer).")
@option("question", str, description="Your question")
async def ask(ctx: discord.ApplicationContext, question: str):
    # Get appropriate voice client (guild or DM)
    vc = ctx.guild.voice_client if ctx.guild else ctx.voice_client

    context_id = get_context_id(ctx)
    answer = pick_weighted_ben_answer(context_id)

    if not answer:
        await ctx.respond("No answer sounds found.", ephemeral=True)
        return

    # Extract message from filename
    message = get_message_for_sound(answer)

    # Create embed
    if ctx.guild:
        # In guilds, show who asked
        embed = discord.Embed(
            description=f"{ctx.author.mention}: **{question}**\n\n{message}",
            color=discord.Color.blue()
        )
    else:
        # In DMs, no need to show who asked
        embed = discord.Embed(
            description=f"**{question}**\n\n{message}",
            color=discord.Color.blue()
        )

    embed.set_author(name="Talking Ben", icon_url=bot.user.avatar.url if bot.user.avatar else None)

    # If not in voice channel, just send the text response
    if not vc or not vc.is_connected():
        await ctx.respond(embed=embed)
        return

    # In voice channel - play audio then respond
    await ctx.defer()
    await play_mp3(vc, answer)
    await ctx.respond(embed=embed)


# ─────────────────────────────────────────────
# Say (specific answer)
# ─────────────────────────────────────────────
@bot.slash_command(description="Make Ben say a specific response.")
@option(
    "response_type",
    str,
    description="Type of response",
    choices=["yes", "no", "yap"]
)
async def say(ctx: discord.ApplicationContext, response_type: str):
    # Get appropriate voice client (guild or DM)
    vc = ctx.guild.voice_client if ctx.guild else ctx.voice_client

    answer = get_specific_answer(response_type)

    if not answer:
        await ctx.respond(f"No {response_type} sound found.", ephemeral=True)
        return

    # Extract message from filename
    message = get_message_for_sound(answer)

    # Create embed
    embed = discord.Embed(
        description=message,
        color=discord.Color.blue()
    )
    embed.set_author(name="Talking Ben", icon_url=bot.user.avatar.url if bot.user.avatar else None)

    # If not in voice channel, just send the text response
    if not vc or not vc.is_connected():
        await ctx.respond(embed=embed)
        return

    # In voice channel - play audio then respond
    await ctx.defer()
    await play_mp3(vc, answer)
    await ctx.respond(embed=embed)


# ─────────────────────────────────────────────
# Config - RENAMED to avoid shadowing the config module
# ─────────────────────────────────────────────
@bot.slash_command(name="config", description="Configure Talking Ben settings.")
@option("enable_voice", bool, description="Enable/disable voice-triggered answers", required=False)
@option("yes_weight", int, min_value=0, max_value=100, required=False)
@option("no_weight", int, min_value=0, max_value=100, required=False)
@option("yapping_weight", int, min_value=0, max_value=100, required=False)
@option("pickup_chance", int, min_value=0, max_value=99,
        description="Chance Ben doesn't pick up (0 = always picks up, 19 = 1 in 20)", required=False)
@option("hangup_chance", int, min_value=0, max_value=99,
        description="Chance Ben doesn't hang up (0 = always hangs up, 19 = 1 in 20)", required=False)
async def ben_config(
        ctx: discord.ApplicationContext,
        enable_voice: bool | None = None,
        yes_weight: int | None = None,
        no_weight: int | None = None,
        yapping_weight: int | None = None,
        pickup_chance: int | None = None,
        hangup_chance: int | None = None,
):
    await ctx.defer(ephemeral=True)

    context_id = get_context_id(ctx)

    if enable_voice is not None:
        config.set_voice_enabled(context_id, enable_voice)

    if yes_weight is not None:
        config.set_weight(context_id, "yes", yes_weight)

    if no_weight is not None:
        config.set_weight(context_id, "no", no_weight)

    if yapping_weight is not None:
        config.set_weight(context_id, "yapping", yapping_weight)

    if pickup_chance is not None:
        config.set_pickup_chance(context_id, pickup_chance)

    if hangup_chance is not None:
        config.set_hangup_chance(context_id, hangup_chance)

    save_config()

    cfg = get_config(context_id)
    fresh_pickup = config.get_pickup_chance(context_id)
    fresh_hangup = config.get_hangup_chance(context_id)

    context_type = "Server" if ctx.guild else "DM"
    response = (
        f"**Talking Ben Configuration ({context_type})**\n\n"
        f"🎙 **voiceTalkToBen**: {cfg.voice_enabled}\n"
        f"📞 **Pickup Chance**: {fresh_pickup} (1 in {fresh_pickup + 1} chance he doesn't pick up)\n\n"
        f"📞 **Hangup Chance**: {fresh_hangup} (1 in {fresh_hangup + 1} chance he doesn't hang up)\n\n"
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
    context_id = get_context_id(ctx)
    cfg = get_config(context_id)
    pickup = config.get_pickup_chance(context_id)
    hangup = config.get_hangup_chance(context_id)

    context_type = "Server" if ctx.guild else "DM"
    response = (
        f"**Talking Ben Status ({context_type})**\n\n"
        f"🎙 **voiceTalkToBen**: {cfg.voice_enabled}\n"
        f"📞 **Pickup Chance**: {pickup} (1 in {pickup + 1} chance he doesn't pick up)\n\n"
        f"📞 **Hangup Chance**: {hangup} (1 in {hangup + 1} chance he doesn't hang up)\n\n"
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
    # For guilds, check member voice state
    if ctx.guild:
        member = ctx.guild.get_member(ctx.author.id) or await ctx.guild.fetch_member(ctx.author.id)

        if not member.voice or not member.voice.channel:
            await ctx.respond("You need to be in a voice channel to use this command.", ephemeral=True)
            return

        channel = member.voice.channel
        vc = ctx.guild.voice_client
    else:
        # For DMs, we can't directly access voice state
        # The user needs to be in a guild voice channel to call Ben
        await ctx.respond(
            "Sorry, I can't join voice channels from DMs. "
            "Please use the `/call` command from within a server where you're in a voice channel.",
            ephemeral=True
        )
        return

    if vc and vc.is_connected() and getattr(vc, "recording", False):
        if vc.channel == channel:
            await ctx.respond("Ben is already in a call with you!", ephemeral=True)
            return
        try:
            vc.stop_recording()
        except Exception:
            pass

    context_id = get_context_id(ctx)

    # Check if Ben picks up the phone
    pickup_chance = config.get_pickup_chance(context_id)

    if pickup_chance > 0 and random.randint(0, pickup_chance) == 0:
        await ben_not_care(
            ctx,
            f"📞 {ctx.author.mention} tried to call Ben, but he didn't pick up the phone...",
            discord.Color.red()
        )
        return

    # Ben picks up - announce in chat
    embed = discord.Embed(
        description=f"📞 {ctx.author.mention} called Ben!",
        color=discord.Color.green()
    )
    embed.set_author(name="Talking Ben", icon_url=bot.user.avatar.url if bot.user.avatar else None)

    # Defer to give us time to connect
    await ctx.defer()

    # Join the call
    await join_call(channel, vc, context_id, ctx)

    # Send the announcement (no send_params because we used defer - it goes through webhook)
    await ctx.respond(embed=embed)


# ─────────────────────────────────────────────
# Hang up
# ─────────────────────────────────────────────
@bot.slash_command(description="Hang up Talking Ben.")
async def hangup(ctx: discord.ApplicationContext):
    # Get appropriate voice client (guild or DM)
    vc = ctx.guild.voice_client if ctx.guild else ctx.voice_client

    if not vc or not vc.is_connected():
        await ctx.respond("Ben isn't connected.", ephemeral=True)
        return

    context_id = get_context_id(ctx)

    # Check if Ben picks up the phone
    hangup_chance = config.get_hangup_chance(context_id)

    if hangup_chance > 0 and random.randint(0, hangup_chance) == 0:
        # Play no sound
        await play_mp3(vc, NO_PATH)

        # Ben doesn't hang up
        await ben_not_care(
            ctx,
            f"📞 {ctx.author.mention} tried to hang up on Ben, but Ben has no interest in hanging up...",
            discord.Color.red()
        )
        return

    await ctx.defer()
    await leave_call(vc)

    embed = discord.Embed(
        description=f"☎️ {ctx.author.mention} hung up on Ben.",
        color=discord.Color.orange()
    )
    embed.set_author(name="Talking Ben", icon_url=bot.user.avatar.url if bot.user.avatar else None)

    # No send_params because we used defer - it goes through webhook
    await ctx.respond(embed=embed)


# ─────────────────────────────────────────────
# Ben doesn't care about your bs
# ─────────────────────────────────────────────
async def ben_not_care(ctx: discord.ApplicationContext, message: str, color: discord.colour.Colour = discord.Color.red()):
    # Ben doesn't pick up
    embed = discord.Embed(
        description=message,
        color=color
    )
    embed.set_author(name="Talking Ben", icon_url=bot.user.avatar.url if bot.user.avatar else None)

    await ctx.respond(embed=embed)


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