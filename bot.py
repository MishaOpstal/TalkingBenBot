import os
import asyncio
import discord
from discord import option

from config import voice_enabled, answer_weights, get_answer_weight, set_answer_weight, save_config, load_config
from audio import (
    CALL_PATH,
    HANG_UP_PATH,
    YAPPING_PATH,
    pick_random_from,
    pick_weighted_ben_answer,
    play_mp3,
    play_mp3_sequence,
    ensure_unsuppressed,
    get_audio_files,
)
from voice_watch import BenSink, monitor_silence

TOKEN = os.environ.get("DISCORD_TOKEN")
if not TOKEN:
    raise RuntimeError("DISCORD_TOKEN env var is required.")

intents = discord.Intents.default()
intents.voice_states = True
intents.members = True

bot = discord.Bot(intents=intents)


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


# ─────────────────────────────────────────────
# Startup cleanup: remove ghost voice sessions
# ─────────────────────────────────────────────


@bot.event
async def on_ready():
    load_config()

    for guild in bot.guilds:
        vc = guild.voice_client
        if vc:
            try:
                await vc.disconnect(force=True)
            except Exception:
                pass

    print(f"Logged in as {bot.user}")


# ─────────────────────────────────────────────
# Ask Ben (text-triggered answer)
# ─────────────────────────────────────────────
@bot.slash_command(description="Ask Talking Ben a question (random answer).")
@option("question", str, description="Your question")
async def ask(ctx: discord.ApplicationContext, question: str):
    await ctx.defer(ephemeral=True)

    vc = ctx.guild.voice_client
    if not vc or not vc.is_connected():
        await ctx.followup.send("Ben isn't in a voice channel. Use `/call` first.")
        return

    answer = pick_weighted_ben_answer()
    if not answer:
        await ctx.followup.send("No answer sounds found.")
        return

    await play_mp3(vc, answer)
    await ctx.followup.send("📞 Ben answered.")


# ─────────────────────────────────────────────
# Config
# ─────────────────────────────────────────────


@bot.slash_command(description="Enable/disable voice-triggered Ben answers.")
@option("voicetalktoben", bool, description="True / False")
async def config(ctx: discord.ApplicationContext, voicetalktoben: bool):
    await ctx.defer(ephemeral=True)

    voice_enabled[ctx.guild_id] = voicetalktoben
    save_config()

    await ctx.followup.send(
        f"🎙 voiceTalkToBen set to **{voicetalktoben}**"
    )


# ─────────────────────────────────────────────
# Answer Weight Configuration
# ─────────────────────────────────────────────
@bot.slash_command(description="Configure the probability weights for Ben's answers.")
@option("yes_weight", int, description="Weight for 'yes' answer (0-100, default: 10)", min_value=0, max_value=100,
        required=False)
@option("no_weight", int, description="Weight for 'no' answer (0-100, default: 10)", min_value=0, max_value=100,
        required=False)
@option("yapping_weight", int, description="Weight for EACH yapping file (0-100, default: 2)", min_value=0,
        max_value=100, required=False)
async def weights(
        ctx: discord.ApplicationContext,
        yes_weight: int = None,
        no_weight: int = None,
        yapping_weight: int = None
):
    """
    Configure answer probability weights.

    Higher weight = more likely to be chosen.
    The final probability is: weight / (sum of all weights)

    Example with 5 yapping files:
    - yes=10, no=10, yapping=2 → yes: 33%, no: 33%, yapping: 33%
    - yes=20, no=5, yapping=1 → yes: 57%, no: 14%, yapping: 29%
    - yes=0, no=0, yapping=10 → yes: 0%, no: 0%, yapping: 100%
    """
    await ctx.defer(ephemeral=True)

    # Update weights if provided
    if yes_weight is not None:
        set_answer_weight("yes", yes_weight)
    if no_weight is not None:
        set_answer_weight("no", no_weight)
    if yapping_weight is not None:
        set_answer_weight("yapping", yapping_weight)

    # Get current weights
    yes = get_answer_weight("yes")
    no = get_answer_weight("no")
    yapping = get_answer_weight("yapping")

    # Calculate probabilities
    yap_count = len(get_audio_files(YAPPING_PATH))
    total = yes + no + (yapping * yap_count)

    if total == 0:
        yes_pct = no_pct = yap_pct = 0
    else:
        yes_pct = (yes / total) * 100
        no_pct = (no / total) * 100
        yap_pct = ((yapping * yap_count) / total) * 100

    response = (
        f"**Ben's Answer Weights**\n\n"
        f"🟢 **Yes**: {yes} → {yes_pct:.1f}%\n"
        f"🔴 **No**: {no} → {no_pct:.1f}%\n"
        f"💬 **Yapping**: {yapping} per file ({yap_count} files) → {yap_pct:.1f}%\n\n"
        f"*Total weight pool: {total}*"
    )

    await ctx.followup.send(response)


# ─────────────────────────────────────────────
# Status
# ─────────────────────────────────────────────
@bot.slash_command(description="Show current Talking Ben settings.")
async def ben_status(ctx):
    enabled = voice_enabled.get(ctx.guild_id, False)

    # Get weights
    yes = get_answer_weight("yes")
    no = get_answer_weight("no")
    yapping = get_answer_weight("yapping")
    yap_count = len(get_audio_files(YAPPING_PATH))

    # Calculate probabilities
    total = yes + no + (yapping * yap_count)
    if total == 0:
        yes_pct = no_pct = yap_pct = 0
    else:
        yes_pct = (yes / total) * 100
        no_pct = (no / total) * 100
        yap_pct = ((yapping * yap_count) / total) * 100

    response = (
        f"**Talking Ben Status**\n\n"
        f"🎙 **voiceTalkToBen**: {enabled}\n\n"
        f"**Answer Probabilities:**\n"
        f"🟢 Yes: {yes_pct:.1f}%\n"
        f"🔴 No: {no_pct:.1f}%\n"
        f"💬 Yapping: {yap_pct:.1f}%\n"
    )

    await ctx.respond(response, ephemeral=True)


# ─────────────────────────────────────────────
# Call Ben (with ghost-VC healing)
# ─────────────────────────────────────────────
@bot.slash_command(description="Call Talking Ben into your current voice channel.")
async def call(ctx: discord.ApplicationContext):
    await ctx.defer(ephemeral=True)

    # Resolve member properly
    member = ctx.guild.get_member(ctx.author.id)
    if member is None:
        member = await ctx.guild.fetch_member(ctx.author.id)

    if not member.voice or not member.voice.channel:
        await ctx.followup.send(
            "You need to be in a voice channel to use this command."
        )
        return

    channel = member.voice.channel
    vc = ctx.guild.voice_client

    # ── Check if already calling (only if in same channel) ──
    if vc and vc.is_connected() and getattr(vc, "recording", False):
        if vc.channel == channel:
            await ctx.followup.send("Ben is already in a call with you!")
            return
        else:
            # If in another channel, we'll stop recording and move
            try:
                vc.stop_recording()
            except Exception:
                pass

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
        print(f"[Stage] Joined stage channel, ensuring speaker status...")
        # Give Discord a moment to process the connection
        await asyncio.sleep(0.5)

        success = await ensure_unsuppressed(ctx.guild)
        if not success:
            print("[Stage Warning] Could not become speaker. Audio might fail.")
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

    # ── Start listening ──
    async def finished_callback(sink, *args):
        pass

    if not vc.is_connected():
        await ctx.followup.send("❌ Failed to connect to voice channel.")
        return

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
    except Exception as e:
        print(f"[Recording Error] {e}")
        await ctx.followup.send("❌ Could not start recording. Ben might be in a weird state, try `/hangup`.")
        return

    asyncio.create_task(monitor_silence(ctx.guild_id, vc, sink))

    await ctx.followup.send("📞 Ben joined the call.")


# ─────────────────────────────────────────────
# Hang up Ben (safe after restarts)
# ─────────────────────────────────────────────
@bot.slash_command(description="Hang up Talking Ben.")
async def hangup(ctx: discord.ApplicationContext):
    await ctx.defer(ephemeral=True)

    vc = ctx.guild.voice_client

    if not vc or not vc.is_connected():
        await ctx.followup.send(
            "Ben isn't connected **from my side**.\n"
            "If he still appears in VC, use `/call` once to force a reconnect, "
            "then `/hangup` again."
        )
        return

    hang = pick_random_from(HANG_UP_PATH)
    if hang:
        await play_mp3(vc, hang)

    try:
        vc.stop_recording()
    except Exception:
        pass

    try:
        await vc.disconnect(force=True)
    except Exception:
        pass

    await ctx.followup.send("☎️ Ben hung up.")


@bot.event
async def on_voice_state_update(member, before, after):
    # If the bot itself is updated (moved, suppressed/unsuppressed)
    if member.id == bot.user.id:
        if before.channel != after.channel:
            if after.channel is None:
                # Bot disconnected, cleanup recording if needed
                vc = before.channel.guild.voice_client
                if vc and getattr(vc, "recording", False):
                    try:
                        vc.stop_recording()
                    except Exception:
                        pass
                return

            # Bot moved to a new channel
            vc = member.guild.voice_client
            if vc:
                print(f"Bot moved from {before.channel} to {after.channel}. Restarting recording to ensure audio flow.")
                try:
                    if getattr(vc, "recording", False):
                        vc.stop_recording()

                    # Wait a bit for the voice connection to stabilize after move
                    await asyncio.sleep(1.0)

                    # ── Handle Stage Channel Move ──
                    if isinstance(after.channel, discord.StageChannel):
                        print(f"[Stage] Moved to stage channel, ensuring speaker status...")
                        # Give it time to process the move
                        await asyncio.sleep(0.5)
                        await ensure_unsuppressed(member.guild)
                        # Extra wait for stage to stabilize
                        await asyncio.sleep(1.5)

                    if not vc.is_connected():
                        return

                    async def finished_callback(sink, *args):
                        pass

                    sink = BenSink(member.guild.id)
                    try:
                        vc.start_recording(sink, finished_callback)
                    except Exception as e:
                        if "Already recording" in str(e):
                            # This can happen if start_recording was called twice rapidly
                            pass
                        else:
                            print(f"[Recording Error in Move] {e}")
                            return

                    asyncio.create_task(monitor_silence(member.guild.id, vc, sink))
                except Exception as e:
                    print(f"Error during bot move recording restart: {e}")
        elif before.suppress != after.suppress:
            # Suppression state changed
            print(f"[Stage] Suppression changed from {before.suppress} to {after.suppress} in {after.channel.name}")

            # If we got suppressed (moved to audience), try to unsuppress
            if after.suppress and isinstance(after.channel, discord.StageChannel):
                print(f"[Stage] Bot was suppressed, attempting to regain speaker status...")
                await asyncio.sleep(0.3)
                await ensure_unsuppressed(member.guild)

            # Don't restart recording on suppression changes to avoid loops
            return

    # Ignore bot's own events for the "empty VC" logic
    if member.bot:
        return

    guild = member.guild
    vc = guild.voice_client

    if not vc or not vc.is_connected():
        return

    channel = vc.channel
    if not channel:
        return

    # Count non-bot members
    non_bot_members = [
        m for m in channel.members
        if not m.bot
    ]

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