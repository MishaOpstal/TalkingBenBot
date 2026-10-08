"""Slash commands and chat replies.

/call /hangup /ask /say   everyone (/ask and /say also work in DMs)
/settings ...             people with "Manage Server"
@Ben, replies to Ben, DMs Ben answers in chat
"""

from __future__ import annotations

import logging
import random
import re
from pathlib import Path

import discord
from discord.ext import commands

from .call import CallManager
from .guild_settings import STRICTNESS, WAKE_MODES, GuildSettings, SettingsStore
from .sounds import Sounds, label

log = logging.getLogger("ben.commands")

GUILD_ONLY = {discord.InteractionContextType.guild}
GUILD_AND_DM = {discord.InteractionContextType.guild, discord.InteractionContextType.bot_dm}
CHAT_MESSAGE_TYPES = {discord.MessageType.default, discord.MessageType.reply}
BEN_WORD = re.compile(r"\bBen\b")

GREEN = discord.Colour.green()
RED = discord.Colour.red()
ORANGE = discord.Colour.orange()
BROWN = discord.Colour(0x8B5A2B)


def answer_text(kind: str, path: Path) -> str:
    if kind == "yes":
        return f"🟢 {label(path)}."
    if kind == "no":
        return f"🔴 {label(path)}."
    return f"💬 *{label(path)}*"


def settings_embed(s: GuildSettings, guild: discord.Guild) -> discord.Embed:
    yes, no, yap = s.chances_percent()
    e = discord.Embed(title="☎️ Talking Ben settings", colour=BROWN)
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
    e.add_field(
        name="💬 Chat",
        value=("**On**: answers when you @mention him or reply to him." if s.chat else "**Off**")
        + "\n`/settings chat`",
        inline=False,
    )
    e.add_field(
        name="📵 Moody phone",
        value=f"Ignores a `/call`: **{s.ignore_call_chance}%** · "
        f"Refuses a `/hangup`: **{s.refuse_hangup_chance}%**\n`/settings phone`",
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

    def __init__(
        self,
        bot: discord.Bot,
        calls: CallManager,
        store: SettingsStore,
        sounds: Sounds,
        *,
        read_chat: bool = False,
    ):
        self.bot = bot
        self.calls = calls
        self.store = store
        self.sounds = sounds
        self.read_chat = read_chat

    # ───────── helpers ─────────
    def _settings(self, guild_id: int | None) -> GuildSettings:
        return self.store.get(guild_id) if guild_id else GuildSettings()

    def _embed(self, text: str, colour: discord.Colour = BROWN) -> discord.Embed:
        e = discord.Embed(description=text, colour=colour)
        me = self.bot.user
        e.set_author(name="Talking Ben", icon_url=me.display_avatar.url if me else None)
        return e

    @staticmethod
    def _rolled(percent: int) -> bool:
        return percent > 0 and random.random() * 100 < percent

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

        lock = self.calls.lock(ctx.guild_id)
        if lock.locked():
            await ctx.respond("Ben is busy with the phone, try again in a second.", ephemeral=True)
            return

        s = self._settings(ctx.guild_id)
        if self._rolled(s.ignore_call_chance):
            await ctx.respond(embed=self._embed(
                f"📵 {ctx.author.mention} tried to call Ben, but he didn't pick up.", RED))
            return

        await ctx.defer()
        async with lock:
            try:
                await self.calls.start(voice.channel)
            except Exception as exc:
                log.exception("Call failed")
                await ctx.followup.send(f"📵 Couldn't call Ben: `{exc}`", ephemeral=True)
                return

        if not s.listening:
            how = "He isn't listening to voice right now (`/settings listening`), use `/ask`."
        elif s.wake_mode == "name":
            how = "Say **\"Ben\"** and ask him something."
        else:
            how = "Just ask him something."
        await ctx.followup.send(embed=self._embed(f"📞 {ctx.author.mention} called Ben! {how}", GREEN))

    @discord.slash_command(description="Hang up on Talking Ben", contexts=GUILD_ONLY)
    async def hangup(self, ctx: discord.ApplicationContext):
        call = self.calls.get(ctx.guild_id)
        if call is None:
            if ctx.guild.voice_client:  # Ben is in a channel we lost track of
                await ctx.guild.voice_client.disconnect(force=True)
                await ctx.respond("☎️ Ben hung up.", ephemeral=True)
            else:
                await ctx.respond("Ben isn't on a call.", ephemeral=True)
            return

        lock = self.calls.lock(ctx.guild_id)
        if lock.locked():
            await ctx.respond("Ben is busy with the phone, try again in a second.", ephemeral=True)
            return

        await ctx.defer()
        async with lock:
            if self._rolled(self._settings(ctx.guild_id).refuse_hangup_chance):
                await call.say(self.sounds.pick("no"))
                text = f"📞 {ctx.author.mention} tried to hang up on Ben. Ben did not like that."
                voice = ctx.author.voice if isinstance(ctx.author, discord.Member) else None
                if voice and voice.channel == call.vc.channel and ctx.guild.me.guild_permissions.move_members:
                    try:
                        await ctx.author.move_to(None, reason="Tried to hang up on Ben")
                        text += " Bye."
                    except discord.HTTPException:
                        pass
                await ctx.followup.send(embed=self._embed(text, RED))
                return

            await self.calls.end(ctx.guild_id)
        await ctx.followup.send(embed=self._embed(f"☎️ {ctx.author.mention} hung up on Ben.", ORANGE))

    # ───────── answers ─────────
    async def _reply_with(self, ctx: discord.ApplicationContext, kind: str, path: Path, question: str | None):
        text = answer_text(kind, path)
        if question:
            who = f"{ctx.author.mention}: " if ctx.guild else ""
            text = f"{who}**{question}**\n\n{text}"

        call = self.calls.get(ctx.guild_id)
        if call:
            await ctx.defer()
            await call.say(path)
            await ctx.followup.send(embed=self._embed(text))
        else:
            # not in a call: send the sound along so you can still hear him
            await ctx.respond(embed=self._embed(text), file=discord.File(path))

    @discord.slash_command(description="Ask Talking Ben a question", contexts=GUILD_AND_DM)
    @discord.option("question", str, description="What do you want to ask Ben?", max_length=200)
    async def ask(self, ctx: discord.ApplicationContext, question: str):
        picked = self.sounds.pick_answer(self._settings(ctx.guild_id))
        if picked is None:
            await ctx.respond("Ben has no sounds to answer with.", ephemeral=True)
            return
        await self._reply_with(ctx, *picked, question)

    @discord.slash_command(description="Make Talking Ben say something specific", contexts=GUILD_AND_DM)
    @discord.option("what", str, description="What Ben says", choices=["yes", "no", "yapping"])
    async def say(self, ctx: discord.ApplicationContext, what: str):
        path = self.sounds.pick(what)
        if path is None:
            await ctx.respond(f"Ben has no '{what}' sound.", ephemeral=True)
            return
        await self._reply_with(ctx, what, path, None)

    # ───────── chat ─────────
    async def _is_reply_to_me(self, message: discord.Message) -> bool:
        ref = message.reference
        if ref is None or ref.message_id is None:
            return False
        author = getattr(ref.resolved, "author", None)  # resolved can also be a deleted message
        if author is None and ref.resolved is None:
            try:
                author = (await message.channel.fetch_message(ref.message_id)).author
            except discord.HTTPException:
                return False
        return author is not None and author.id == self.bot.user.id

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or message.type not in CHAT_MESSAGE_TYPES:
            return

        if message.guild is not None:
            s = self.store.get(message.guild.id)
            if not s.chat:
                return
            talking_to_ben = (
                self.bot.user in message.mentions
                or (self.read_chat and BEN_WORD.search(message.content or ""))
                or await self._is_reply_to_me(message)
            )
            if not talking_to_ben:
                return
        else:
            s = GuildSettings()  # DMs: always answer, default chances

        picked = self.sounds.pick_answer(s)
        if picked is None:
            return
        kind, path = picked

        await message.reply(answer_text(kind, path), mention_author=False)
        call = self.calls.get(message.guild.id) if message.guild else None
        if call:
            await call.say(path)

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

    @settings_group.command(name="chat", description="Should Ben answer in text chat?")
    @discord.option("enabled", bool, description="On: Ben answers when you @mention him or reply to him")
    async def settings_chat(self, ctx: discord.ApplicationContext, enabled: bool):
        s = self.store.update(ctx.guild_id, chat=enabled)
        await self._show(ctx, s, f"✅ Chat answers are now **{'on' if enabled else 'off'}**.")

    @settings_group.command(name="phone", description="How moody Ben is about the phone")
    @discord.option("ignore_calls", int, description="% chance Ben doesn't pick up a /call (default 5)",
                    min_value=0, max_value=100, required=False)
    @discord.option("refuse_hangups", int,
                    description="% chance Ben refuses /hangup, says no and kicks you from voice (default 5)",
                    min_value=0, max_value=100, required=False)
    async def settings_phone(self, ctx: discord.ApplicationContext,
                             ignore_calls: int | None = None, refuse_hangups: int | None = None):
        changes = {}
        if ignore_calls is not None:
            changes["ignore_call_chance"] = ignore_calls
        if refuse_hangups is not None:
            changes["refuse_hangup_chance"] = refuse_hangups
        s = self.store.update(ctx.guild_id, **changes) if changes else self.store.get(ctx.guild_id)
        note = "✅ Updated."
        if s.refuse_hangup_chance and not ctx.guild.me.guild_permissions.move_members:
            note += " (Ben needs the **Move Members** permission to kick people, without it he only says no.)"
        await self._show(ctx, s, note)

    @settings_group.command(name="reset", description="Put every setting back to default")
    async def settings_reset(self, ctx: discord.ApplicationContext):
        s = self.store.reset(ctx.guild_id)
        await self._show(ctx, s, "✅ Back to defaults.")
