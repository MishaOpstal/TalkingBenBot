from dataclasses import dataclass
from typing import Union

import discord

from audio import get_audio_files, YAPPING_PATH
from config import config


@dataclass(frozen=True)
class GuildConfigView:
    voice_enabled: bool
    yes_weight: int
    no_weight: int
    yapping_weight: int
    yes_pct: float
    no_pct: float
    yapping_pct: float
    total_weight: int


def get_context_id(ctx: discord.ApplicationContext) -> str:
    """
    Get a unique context ID for configuration.

    For guilds: returns guild_id as string
    For DMs: returns "direct_messages.{user_id}" to avoid conflicts
    """
    if ctx.guild:
        # Guild context - use guild ID
        return str(ctx.guild_id)
    else:
        # DM context - use prefixed user ID
        return f"direct_messages.{ctx.author.id}"


def get_config(context_id: Union[int, str]) -> GuildConfigView:
    """
    Get configuration for a given context (guild or DM).

    Args:
        context_id: Either a guild_id (int), or a DM context string "direct_messages.{user_id}"
    """
    weights = config.get_weights(context_id)

    yes = weights["yes"]
    no = weights["no"]
    yapping = weights["yapping"]

    yap_count = len(get_audio_files(YAPPING_PATH))
    total = yes + no + (yapping * yap_count)

    if total == 0:
        yes_pct = no_pct = yapping_pct = 0.0
    else:
        yes_pct = (yes / total) * 100
        no_pct = (no / total) * 100
        yapping_pct = ((yapping * yap_count) / total) * 100

    return GuildConfigView(
        voice_enabled=config.is_voice_enabled(context_id),
        yes_weight=yes,
        no_weight=no,
        yapping_weight=yapping,
        yes_pct=yes_pct,
        no_pct=no_pct,
        yapping_pct=yapping_pct,
        total_weight=total,
    )