"""Slash commands.

/call /hangup /ask       everyone
/settings ...            people with "Manage Server"
"""

from __future__ import annotations

import logging

import discord
from discord.ext import commands

from .call import CallManager
from .guild_settings import STRICTNESS, WAKE_MODES, GuildSettings, SettingsStore
from .sounds import Sounds

log = logging.getLogger("ben.commands")

ANSWER_TEXT = {"yes": "🟢 Yes.", "no": "🔴 No.", "yapping": "💬 *Ben is yapping*"}
GUILD_ONLY = {discord.InteractionContextType.guild}


def settings_embed(s: GuildSettings, guild: discord.Guild) -> discord.Embed:
    yes, no, yap = s.chances_percent()
    e = discord.Embed(title="☎️ Talking Ben settings", colour=0x8B5A2B)
    e.add_field(
        name="👂 Listening",
        value=("**On**: Ben listens in calls." if s.listening else "**Off**: Ben only answers `/ask`.")
        + "\n`/settings listening`",
        inline=False,
    )
    e.add_field(
        name="🗣️ When Ben answers",
        value=f"**{s.wake_mode}**: {WAKE_MODES[s.wake_mode]}\n`/settings mode`",
        inline=False,
    )
    if s.wake_mode == "name":
        e.add_field(
            name="🎯 Hearing his name",
            value=f"**{s.strictness}**: {STRICTNESS[s.strictness]}\n`/settings strictness`",
            inline=False,
        )
    e.add_field(
        name="⏱️ Answer delay",
        value=f"**{s.answer_delay:.1f}s** of silence after your question\n`/settings answer-delay`",
        inline=False,
    )
    e.add_field(
        name="🎲 Answers",
        value=f"🟢 Yes **{yes:.0f}%** · 🔴 No **{no:.0f}%** · 💬 Yapping **{yap:.0f}%**\n`/settings answers`",
        inline=False,
    )
    e.set_footer(text=guild.name)
    return e


class BenCommands(commands.Cog):
    settings_group = discord.SlashCommandGroup(
        "settings",
        "Change how Talking Ben behaves in this server",
        default_member_permissions=discord.Permissions(manage_guild=True),
        contexts=GUILD_ONLY,
    )

    def __init__(self, bot: discord.Bot, calls: CallManager, store: SettingsStore, sounds: Sounds):
        self.bot = bot
        self.calls = calls
        self.store = store
        self.sounds = sounds

    # ───────── calls ─────────
    @discord.slash_command(description="Call Talking Ben into your voice channel", contexts=GUILD_ONLY)
    async def call(self, ctx: discord.ApplicationContext):
        voice = ctx.author.voice if isinstance(ctx.author, discord.Member) else None
        if voice is None or voice.channel is None:
            await ctx.respond("Join a voice channel first, then `/call` Ben.", ephemeral=True)
            return

        current = self.calls.get(ctx.guild_id)
        if current and current.vc.channel == voice.channel:
            await ctx.respond("Ben is already on the phone with you.", ephemeral=True)
            return

        perms = voice.channel.permissions_for(ctx.guild.me)
        if not (perms.connect and perms.speak):
            await ctx.respond(
                f"I need **Connect** and **Speak** permissions in {voice.channel.mention}.", ephemeral=True
            )
            return

        await ctx.defer(ephemeral=True)
        try:
            await self.calls.start(voice.channel)
        except Exception as exc:
            log.exception("Call failed")
            await ctx.followup.send(f"📵 Couldn't call Ben: `{exc}`", ephemeral=True)
            return

        s = self.store.get(ctx.guild_id)
        if not s.listening:
            how = "He isn't listening to voice right now (`/settings listening`), use `/ask`."
        elif s.wake_mode == "name":
            how = "Say **\"Ben\"** and ask him something."
        else:
            how = "Just ask him something."
        await ctx.followup.send(f"📞 Ben picked up. {how}", ephemeral=True)

    @discord.slash_command(description="Hang up on Talking Ben", contexts=GUILD_ONLY)
    async def hangup(self, ctx: discord.ApplicationContext):
        await ctx.defer(ephemeral=True)
        ended = await self.calls.end(ctx.guild_id)
        if not ended and ctx.guild.voice_client:
            # Ben is in a channel we lost track of (e.g. after a restart)
            await ctx.guild.voice_client.disconnect(force=True)
            ended = True
        await ctx.followup.send("☎️ Ben hung up." if ended else "Ben isn't on a call.", ephemeral=True)

    @discord.slash_command(description="Ask Talking Ben a question", contexts=GUILD_ONLY)
    @discord.option("question", str, description="What do you want to ask Ben?", max_length=200)
    async def ask(self, ctx: discord.ApplicationContext, question: str):
        call = self.calls.get(ctx.guild_id)
        if call:
            await ctx.defer()
            kind = await call.answer()
            await ctx.followup.send(f"> {question}\n{ANSWER_TEXT.get(kind, '...')}")
            return

        picked = self.sounds.pick_answer(self.store.get(ctx.guild_id))
        if picked is None:
            await ctx.respond("Ben has no sounds to answer with.", ephemeral=True)
            return
        kind, path = picked
        await ctx.respond(f"> {question}\n{ANSWER_TEXT[kind]}", file=discord.File(path))

    # ───────── settings ─────────
    async def _show(self, ctx: discord.ApplicationContext, s: GuildSettings, note: str | None = None):
        await ctx.respond(note, embed=settings_embed(s, ctx.guild), ephemeral=True)

    @settings_group.command(name="show", description="Show all Talking Ben settings")
    async def settings_show(self, ctx: discord.ApplicationContext):
        await self._show(ctx, self.store.get(ctx.guild_id))

    @settings_group.command(name="listening", description="Turn voice listening on or off")
    @discord.option("enabled", bool, description="On: Ben listens in calls. Off: only /ask works.")
    async def settings_listening(self, ctx: discord.ApplicationContext, enabled: bool):
        s = self.store.update(ctx.guild_id, listening=enabled)
        await self._show(ctx, s, f"✅ Listening is now **{'on' if enabled else 'off'}**.")

    @settings_group.command(name="mode", description="When does Ben answer?")
    @discord.option(
        "mode",
        str,
        description="How Ben decides someone is talking to him",
        choices=[discord.OptionChoice(f"{k}: {v}"[:100], k) for k, v in WAKE_MODES.items()],
    )
    async def settings_mode(self, ctx: discord.ApplicationContext, mode: str):
        s = self.store.update(ctx.guild_id, wake_mode=mode)
        await self._show(ctx, s, f"✅ Mode is now **{mode}**.")

    @settings_group.command(name="strictness", description="How picky Ben is about hearing his name")
    @discord.option(
        "level",
        str,
        description="Ben doesn't hear you: go looser. Ben answers random stuff: go stricter.",
        choices=[discord.OptionChoice(f"{k}: {v}"[:100], k) for k, v in STRICTNESS.items()],
    )
    async def settings_strictness(self, ctx: discord.ApplicationContext, level: str):
        s = self.store.update(ctx.guild_id, strictness=level)
        await self._show(ctx, s, f"✅ Strictness is now **{level}**.")

    @settings_group.command(name="answer-delay", description="How long Ben waits after you stop talking")
    @discord.option("seconds", float, description="Default 0.8. Lower = snappier, higher = lets you pause",
                    min_value=0.3, max_value=3.0)
    async def settings_answer_delay(self, ctx: discord.ApplicationContext, seconds: float):
        s = self.store.update(ctx.guild_id, answer_delay=round(seconds, 2))
        await self._show(ctx, s, f"✅ Ben now waits **{seconds:.1f}s**.")

    @settings_group.command(name="answers", description="How often Ben says yes, no or yaps")
    @discord.option("yes", int, description="Chance of 'yes' (default 40)", min_value=0, max_value=100, required=False)
    @discord.option("no", int, description="Chance of 'no' (default 40)", min_value=0, max_value=100, required=False)
    @discord.option("yapping", int, description="Chance of ho-ho-ho, ugh and friends (default 20)",
                    min_value=0, max_value=100, required=False)
    async def settings_answers(self, ctx: discord.ApplicationContext,
                               yes: int | None = None, no: int | None = None, yapping: int | None = None):
        current = self.store.get(ctx.guild_id)
        new = {
            "chance_yes": current.chance_yes if yes is None else yes,
            "chance_no": current.chance_no if no is None else no,
            "chance_yapping": current.chance_yapping if yapping is None else yapping,
        }
        if sum(new.values()) == 0:
            await ctx.respond("At least one of them has to be above 0.", ephemeral=True)
            return
        s = self.store.update(ctx.guild_id, **new)
        note = "✅ Updated."
        if sum(new.values()) != 100:
            note += " (They don't add up to 100, so they're scaled: what you see below is what you get.)"
        await self._show(ctx, s, note)

    @settings_group.command(name="reset", description="Put every setting back to default")
    async def settings_reset(self, ctx: discord.ApplicationContext):
        s = self.store.reset(ctx.guild_id)
        await self._show(ctx, s, "✅ Back to defaults.")
