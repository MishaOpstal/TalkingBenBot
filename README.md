# Talking Ben Bot

Talking Ben in your Discord voice channel. `/call` him, say "Ben", ask a question, get a "Yes.", "No.", "Ho ho ho" or "Ugh".

## Setup

1. **Make the bot** at <https://discord.com/developers/applications>: New Application → **Bot** → **Reset Token**, copy it. No privileged intents needed.
2. **Configure**: copy `.env.example` to `.env` and paste the token after `DISCORD_TOKEN=`.
3. **Run** it, either way:
   - Docker: `docker compose up -d --build`
   - Python 3.10 to 3.14 with git and ffmpeg installed: `pip install -r requirements.txt` then `python bot.py`
4. **Invite** Ben with the link printed in the log on startup (it has the right permissions already).

The speech model (~40 MB) downloads by itself the first time.

## Commands

| Command | Who | What |
|---|---|---|
| `/call` | everyone | Ben joins your voice channel |
| `/hangup` | everyone | Ben leaves |
| `/ask question` | everyone | Ben answers out loud in the call, or with a sound file if he isn't in one |
| `/settings show` | Manage Server | See everything below |
| `/settings listening` | Manage Server | Voice on/off. Off = only `/ask` works |
| `/settings mode` | Manage Server | `name`: say "Ben" first. `always`: answers whatever anyone says, like the app |
| `/settings strictness` | Manage Server | How picky he is about hearing "Ben" (see below) |
| `/settings answer-delay` | Manage Server | Seconds of silence before he answers (default 0.8) |
| `/settings answers` | Manage Server | Chances for yes / no / yapping (default 40 / 40 / 20) |
| `/settings reset` | Manage Server | Back to defaults |

Ben hangs up by himself when everyone leaves.

### Ben doesn't hear you, or hears things that aren't there

`/settings strictness`:

- `strict`: "Ben" has to be the first word ("Ben, ...", "Hey Ben, ..."). Fewest false alarms.
- `normal` (default): "Ben" has to be one of the first two words, and "ik ben" never counts.
- `relaxed`: also answers when he only *thinks* he heard Ben. Hears almost everything, but in a busy call he'll butt in now and then.

Speaking Dutch? Keep `SPEECH_MODEL=nl`. "Ik **ben** moe" rarely sets him off, but "**Ben** je gek?" will, since that's a question starting with Ben. Talking Ben will gladly answer it.

Want to check how well he understands *your* voice? Record yourself a few times and run `python testing/simulate_call.py clip1.wav clip2.wav` (add `--strictness relaxed` etc. to compare). `LOG_LEVEL=DEBUG` also logs what Ben thinks everyone said.

## .env options

| Name | Default | |
|---|---|---|
| `DISCORD_TOKEN` | | required |
| `SPEECH_MODEL` | `nl` | `nl`, `en`, or a path to a Vosk model folder |
| `DEV_GUILD_ID` | | Test server ID: command changes show up there instantly |
| `LOG_LEVEL` | `INFO` | `DEBUG` for more detail |

## Sounds

`assets/sounds/`: `telephone/call/` plays in name order on `/call`, one random `telephone/hang_up/` file on hang up, `answers/yes.mp3` + `answers/no.mp3`, and anything in `yapping/`. Drop in more yapping files whenever; with Docker the folder is mounted, so a restart is enough.

## How it works

- **Voice receive**: Discord made every call end-to-end encrypted (DAVE) in March 2026. py-cord 2.8.1 can send audio in those calls but not receive it, so `requirements.txt` pins py-cord to the pull request that fixes receiving (#3159). Swap back to a normal release when one includes it.
- **Hearing "Ben"**: [Vosk](https://alphacephei.com/vosk/) small model with a tiny grammar: "ben", a few greetings, ~40 common short words (ik, je, dan, the, you...) and "unknown". It only has to decide "Ben or not" instead of transcribing everything, which is far more accurate and light. Everyone gets their own recognizer (the old version fed everybody's audio into one, which garbled it).
- **Tested** on ~650 synthetic clips with Dutch accents pushed through Opus like Discord does: the default (`nl`, `normal`) hears 89% of "Ben"s with about 6% false alarms. The old setup heard 62% with 16% false alarms.
- **Memory**: about 200-250 MB in total. The old setup most likely used the big English model (1.8 GB download, gigabytes in RAM), which explains the 2 GB.
