"""Talking Ben for Discord. Start with:  python bot.py   (or: docker compose up -d)"""

from __future__ import annotations

import asyncio
import ctypes.util
import logging
import sys

import discord

from ben.call import CallManager
from ben.commands import BenCommands
from ben.config import ConfigError, load_config
from ben.guild_settings import SettingsStore
from ben.playback import become_speaker
from ben.sounds import Sounds
from ben.speech import SpeechModel, resolve_model_path

log = logging.getLogger("ben")

# Permissions Ben needs, used for the invite link printed at startup.
INVITE_PERMISSIONS = discord.Permissions(
    view_channel=True,
    send_messages=True,
    attach_files=True,
    connect=True,
    speak=True,
    use_voice_activation=True,
    mute_members=True,  # only to become a speaker in Stage channels
    request_to_speak=True,
)


def patch_pycord() -> None:
    # py-cord bug (issue #3388): the UDP keep-alive sleeps 5000 s instead of 5 s,
    # so Discord stops sending audio after a few minutes.
    try:
        from discord.voice.receive.reader import UDPKeepAlive

        if UDPKeepAlive.delay > 60:
            UDPKeepAlive.delay = 5
    except ImportError:
        pass


def load_opus() -> None:
    # py-cord's own loader: the bundled DLL on Windows, the system libopus elsewhere
    if discord.opus.is_loaded() or discord.opus._load_default():
        return
    for name in (ctypes.util.find_library("opus"), "libopus.so.0", "libopus.so", "opus"):
        if not name:
            continue
        try:
            discord.opus.load_opus(name)
            return
        except OSError:
            continue
    raise ConfigError("Opus isn't installed. Docker has it built in; on Linux: apt install libopus0.")


def main() -> int:
    try:
        config = load_config()
    except ConfigError as exc:
        print(f"Config problem: {exc}", file=sys.stderr)
        return 1

    logging.basicConfig(
        level=config.log_level,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    logging.getLogger("discord").setLevel(max(logging.WARNING, logging.getLevelName(config.log_level)))

    try:
        load_opus()
        speech = SpeechModel(resolve_model_path(config.speech_model, config.models_dir))
    except ConfigError as exc:
        log.error("%s", exc)
        return 1

    patch_pycord()
    sounds = Sounds(config.sounds_dir)
    for problem in sounds.check():
        log.warning("Sounds: %s", problem)

    store = SettingsStore(config.data_dir)
    calls = CallManager(speech, store, sounds)

    bot = discord.Bot(
        intents=discord.Intents.default(),  # guilds + voice states, no privileged intents needed
        debug_guilds=[config.dev_guild_id] if config.dev_guild_id else None,
        activity=discord.CustomActivity("☎️ /call me"),
    )
    bot.add_cog(BenCommands(bot, calls, store, sounds))

    @bot.event
    async def on_ready():
        # Leftover voice connections from before a restart
        for guild in bot.guilds:
            if guild.voice_client and calls.get(guild.id) is None:
                try:
                    await guild.voice_client.disconnect(force=True)
                except Exception:
                    pass
        log.info("Logged in as %s in %d server(s)", bot.user, len(bot.guilds))
        log.info(
            "Invite link: %s",
            discord.utils.oauth_url(bot.user.id, permissions=INVITE_PERMISSIONS,
                                    scopes=("bot", "applications.commands")),
        )

    @bot.event
    async def on_voice_state_update(member: discord.Member, before, after):
        guild = member.guild
        call = calls.get(guild.id)

        if member.id == bot.user.id:
            if after.channel is None and guild.id in calls.calls:
                # Ben got disconnected (kicked / channel deleted)
                await calls.end(guild.id, play_sound=False)
            elif (
                isinstance(after.channel, discord.StageChannel)
                and after.suppress
                and (not before.suppress or before.channel != after.channel)
            ):
                # moved to the audience: try to get back on stage (only once per demotion)
                await asyncio.sleep(0.3)
                await become_speaker(guild)
            return

        # Leave when nobody (human) is left in Ben's channel
        if call and call.vc.channel and not any(not m.bot for m in call.vc.channel.members):
            log.info("Channel empty in %s, hanging up", guild.name)
            await calls.end(guild.id, play_sound=False)

    try:
        bot.run(config.token)
    except discord.LoginFailure:
        log.error("Discord rejected DISCORD_TOKEN. Reset the token in the developer portal and paste the new one.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
