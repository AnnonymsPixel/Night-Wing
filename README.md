#Night Wing

#Updates are not pushed yet

Discord bot with music, role tools, timers, moderation utilities, embeds, and admin commands.

## Project Layout

- `bot.py` - lightweight startup loader
- `functions.py` - shared helpers, bot setup, maintenance, and core utilities
- `events.py` - event handlers and bot lifecycle hooks
- `music.py` - voice, playback, queue, timer, and FFmpeg checks
- `roles.py` - role panels, role info, and reaction roles
- `admin.py` - help, admin, announcement, embed, and message commands

## Requirements

- Python 3.10+ recommended
- Discord bot token
- `OWNER_ID` in `.env` for owner-only commands
- FFmpeg installed on the system for voice playback

## Install

```bash
pip install -r Updated-bot/requirements.txt
```

If you do not already have FFmpeg installed, install it separately with your package manager. The bot checks for it at runtime.

## Environment Variables

Create a `.env` file in `Updated-bot/`:

```env
DISCORD_BOT_TOKEN=your_bot_token_here
OWNER_ID=your_discord_user_id_here
```

## Run

```bash
python Updated-bot/bot.py
```

## Commands

- `!help` - full command list
- `!play`, `!pause`, `!resume`, `!skip`, `!stop`
- `!timer <duration> [message]`
- `!roles` - button role panel
- `!reactroles` or `!rr` - numbered reaction role panel
- `!ffmpeg` - check FFmpeg status
- `!timeleft` - check remaining maintenance time

## Notes

- Reaction roles are still emoji-based, but the panel now shows a numbered list in order.
- Role ID `1485879654270369793` is mapped to `4️⃣` and displays as `RP` if the role cannot be resolved.
- Music playback depends on FFmpeg being installed outside Python packages.
