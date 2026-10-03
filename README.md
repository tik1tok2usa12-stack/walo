# Staff Architect Bot

A `discord.py` bot that builds a complete staff structure for a Discord server:

- **120 staff roles** (Owners, Admins, Moderators, Special Ops) in a rounded Fredoka-style font, unique colors and emojis
- **Among Us themed staff channels** with per-role permissions
- **32 game hubs** (Valorant, Free Fire, Minecraft, ...) with game roles and a self-role dropdown
- **Developer-only tools**: DMs by user/role, announcements, scheduler, polls, bot control

## Setup

1. Create a bot at the [Discord Developer Portal](https://discord.com/developers/applications).
2. Under **Bot**, enable **Server Members Intent** and **Message Content Intent**.
3. Invite it with the Administrator permission:
   `https://discord.com/oauth2/authorize?client_id=YOUR_CLIENT_ID&permissions=8&scope=bot%20applications.commands`
4. Drag the bot's role to the **top** of your server's role list.
5. Install and run:

```bash
pip install -r requirements.txt
cp .env.example .env      # then edit .env and paste your token
python bot.py
```

## Usage

Run in this order: `!makeroles` -> `!cleanroles` -> `!makechannels` -> `!makegames all` -> `!giveallroles @you`

Type `!staffhelp` for all commands and `!devhelp` for developer-only tools
(developer = the bot application's owner, or the IDs in `DEV_IDS` in `bot.py`).

## Notes

- Owner roles have the **Administrator** permission. Only give them to people you fully trust.
- Never commit your bot token. If it ever leaks, reset it in the Developer Portal.
- Discord can't use custom fonts; the rounded look uses Unicode characters.

## Deploy on Railway

1. Push this repo to GitHub (the `.env` file must NOT be included).
2. On [Railway](https://railway.com): **New Project -> Deploy from GitHub repo** and pick this repo.
3. Open the service -> **Variables** -> add `DISCORD_TOKEN` with your bot token.
4. `railway.json` already sets the start command (`python bot.py`) and auto-restart.
5. The bot is a background worker: it needs **no public domain and no port**. Check **Deployments -> Logs**
   for `Logged in as ...`.

Railway's filesystem is temporary: `dm_log.txt` and scheduled announcements reset on every redeploy/restart.
