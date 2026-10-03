"""
dev_tools.py  -  Developer-only extension for Staff Architect Bot
-----------------------------------------------------------------
Put this file in the SAME folder as bot.py. It loads automatically.

EVERY command here is locked to the bot developer (the owner of the bot application in the
Developer Portal, or the IDs you put in DEV_IDS in the main file). Nobody else can run them.

Features
  DMs:           !dm  !dmusers  !dmrole  !dmhistory  !deletedm
  Announcements: !compose (popup form)  !devannounce  !say  !embed  !edit  !broadcast
  Scheduler:     !schedule  !schedules  !unschedule
  Extras:        !poll  !roleinfo  !userinfo  !rolemembers
  Bot control:   !botstats  !ping  !setstatus  !guilds  !leaveguild  !shutdown
  Help:          !devhelp
"""

import asyncio
import platform
import re
import time
import unicodedata
from collections import deque

import discord
from discord.ext import commands

# ───────────────────────────── CONFIG ─────────────────────────────
DM_DELAY = 2.0              # seconds between DMs (protects the bot from Discord rate limits/spam flags)
MAX_DM_RECIPIENTS = 250     # hard cap for one bulk DM
BROADCAST_DELAY = 1.0       # seconds between channel posts in !broadcast
MAX_BROADCAST_CHANNELS = 60
DM_LOG_FILE = "dm_log.txt"  # every DM the bot sends here is logged (who, when, success)
ACCENT = 0x6B2FBB
NUMBER_EMOJI = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]


# ───────────────────────────── HELPERS ────────────────────────────
def rounded(text: str) -> str:
    """Fredoka-style rounded Unicode font (Sans-Serif Bold)."""
    out = []
    for ch in text:
        if "A" <= ch <= "Z":
            out.append(chr(0x1D5D4 + ord(ch) - 65))
        elif "a" <= ch <= "z":
            out.append(chr(0x1D5EE + ord(ch) - 97))
        elif "0" <= ch <= "9":
            out.append(chr(0x1D7EC + ord(ch) - 48))
        else:
            out.append(ch)
    return "".join(out)


def norm(s: str) -> str:
    """Plain-text identity: ignores fancy fonts and emoji."""
    n = unicodedata.normalize("NFKC", s).casefold()
    n = "".join(c if (c.isalnum() or c in " -") else " " for c in n)
    return " ".join(n.split())


def parse_color(text: str, default: int = ACCENT) -> int:
    t = (text or "").strip().lower().replace("#", "").replace("0x", "")
    if re.fullmatch(r"[0-9a-f]{6}", t):
        return int(t, 16)
    return default


def parse_duration(text: str):
    m = re.fullmatch(r"(\d+)\s*([smhd])", text.strip().lower())
    if not m:
        return None
    return int(m.group(1)) * {"s": 1, "m": 60, "h": 3600, "d": 86400}[m.group(2)]


def split_args(args: str):
    """'role name | message'  or  'roleid message' -> (target, message)"""
    if "|" in args:
        a, b = args.split("|", 1)
        return a.strip(), b.strip()
    parts = args.split(None, 1)
    return (parts[0], parts[1].strip() if len(parts) > 1 else "") if parts else ("", "")


def find_role_fuzzy(guild: discord.Guild, text: str) -> discord.Role:
    """Find a role by mention, ID, exact name, or plain text (works with the fancy fonts)."""
    text = text.strip()
    m = re.fullmatch(r"<@&(\d+)>|(\d{15,21})", text)
    if m:
        role = guild.get_role(int(m.group(1) or m.group(2)))
        if role:
            return role
    exact = [r for r in guild.roles if r.name == text]
    if exact:
        return exact[0]
    key = norm(text)
    if not key:
        raise ValueError("No role given.")
    same = [r for r in guild.roles if norm(r.name) == key]
    if same:
        return max(same, key=lambda r: len(r.members))
    part = [r for r in guild.roles if key in norm(r.name)]
    if len(part) == 1:
        return part[0]
    if not part:
        raise ValueError(f"No role matches `{text}`.")
    names = ", ".join(f"`{norm(r.name)}`" for r in part[:10])
    raise ValueError(f"`{text}` matches several roles: {names}. Be more specific.")


def make_embed(title, description, color=ACCENT, footer=None):
    e = discord.Embed(title=title, description=description, color=color,
                      timestamp=discord.utils.utcnow())
    if footer:
        e.set_footer(text=footer)
    return e


# ───────────────────────────── UI PARTS ───────────────────────────
class ConfirmView(discord.ui.View):
    def __init__(self, author_id: int):
        super().__init__(timeout=60)
        self.author_id = author_id
        self.value = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("Only the person who ran the command can use this.",
                                                    ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Send", style=discord.ButtonStyle.success, emoji="✅")
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.value = True
        await interaction.response.defer()
        self.stop()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.danger, emoji="✖️")
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.value = False
        await interaction.response.defer()
        self.stop()


class AnnounceModal(discord.ui.Modal, title="📢 New Announcement"):
    a_title = discord.ui.TextInput(label="Title", max_length=100, placeholder="Big news!")
    a_body = discord.ui.TextInput(label="Message", style=discord.TextStyle.paragraph,
                                  max_length=3500, placeholder="Write your announcement here...")
    a_color = discord.ui.TextInput(label="Color HEX (optional)", required=False, max_length=7,
                                   placeholder="FFD700")
    a_ping = discord.ui.TextInput(label="Ping: everyone / here / none / role name", required=False,
                                  max_length=60, default="none")
    a_image = discord.ui.TextInput(label="Image URL (optional)", required=False, max_length=300)

    def __init__(self, channel: discord.TextChannel):
        super().__init__()
        self.channel = channel

    async def on_submit(self, interaction: discord.Interaction):
        ping = (self.a_ping.value or "none").strip()
        content, allowed = None, discord.AllowedMentions.none()
        if ping.lower() in ("everyone", "here"):
            content, allowed = f"@{ping.lower()}", discord.AllowedMentions(everyone=True)
        elif ping.lower() not in ("", "none", "no"):
            try:
                role = find_role_fuzzy(interaction.guild, ping)
            except ValueError as e:
                return await interaction.response.send_message(f"❌ {e}", ephemeral=True)
            content, allowed = role.mention, discord.AllowedMentions(roles=[role])

        embed = make_embed("📢 " + self.a_title.value, self.a_body.value,
                           parse_color(self.a_color.value),
                           footer=f"Announced by {interaction.user.display_name}")
        img = (self.a_image.value or "").strip()
        if img.startswith(("http://", "https://")):
            embed.set_image(url=img)
        await self.channel.send(content=content, embed=embed, allowed_mentions=allowed)
        await interaction.response.send_message(f"✅ Announcement posted in {self.channel.mention}!",
                                                ephemeral=True)


class ComposeView(discord.ui.View):
    def __init__(self, author_id: int, channel: discord.TextChannel):
        super().__init__(timeout=120)
        self.author_id, self.channel = author_id, channel

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("Not your form.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Write announcement", style=discord.ButtonStyle.primary, emoji="✍️")
    async def write(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(AnnounceModal(self.channel))


# ─────────────────────────────── COG ──────────────────────────────
class DevTools(commands.Cog, name="Developer Tools"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.started = time.time()
        self.dm_log = deque(maxlen=50)
        self.schedules = {}          # id -> dict(task, when, channel, text)
        self._next_id = 1

    # -- every command in this cog is developer-only --
    async def cog_check(self, ctx: commands.Context) -> bool:
        if await ctx.bot.is_owner(ctx.author):
            return True
        raise commands.CheckFailure("🔒 This command is for the bot developer only.")

    def cog_unload(self):
        for item in self.schedules.values():
            item["task"].cancel()

    async def _confirm(self, ctx, embed) -> bool:
        view = ConfirmView(ctx.author.id)
        msg = await ctx.send(embed=embed, view=view)
        await view.wait()
        for child in view.children:
            child.disabled = True
        try:
            await msg.edit(view=view)
        except discord.HTTPException:
            pass
        if view.value is None:
            await ctx.send("⌛ Timed out, nothing was sent.")
        return bool(view.value)

    # ═════════════════════════ DIRECT MESSAGES ═════════════════════
    def _dm_embed(self, guild, text):
        e = make_embed("📩 " + rounded("Message from Staff"), text)
        if guild:
            e.set_footer(text=guild.name, icon_url=guild.icon.url if guild.icon else None)
        return e

    def _log_dm(self, sender, target, ok):
        stamp = int(time.time())
        self.dm_log.append(f"<t:{stamp}:R> → **{target}** ({target.id}) {'✅' if ok else '❌'}")
        try:
            with open(DM_LOG_FILE, "a", encoding="utf-8") as f:
                f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} sender={sender.id} "
                        f"target={target.id} ok={ok}\n")
        except OSError:
            pass

    @staticmethod
    def _personalize(text, member, guild):
        return (text.replace("{name}", member.display_name)
                    .replace("{mention}", member.mention)
                    .replace("{server}", guild.name if guild else ""))

    async def _bulk_dm(self, ctx, members, text, label):
        members = list({m.id: m for m in members if not m.bot}.values())
        if not members:
            return await ctx.send("❌ No recipients found.")
        if not text:
            return await ctx.send("❌ Your message is empty.")
        if len(members) > MAX_DM_RECIPIENTS:
            return await ctx.send(f"❌ {len(members)} recipients is above the safety cap of {MAX_DM_RECIPIENTS}.")

        preview = make_embed("📨 Confirm bulk DM", text[:1500], ACCENT)
        preview.add_field(name="Recipients", value=f"**{len(members)}** members ({label})")
        preview.add_field(name="Estimated time", value=f"~{int(len(members) * DM_DELAY)}s")
        preview.set_footer(text="Placeholders: {name} {mention} {server}")
        if not await self._confirm(ctx, preview):
            return

        status = await ctx.send(f"📨 Sending to **{len(members)}** members...")
        sent, failed = 0, []
        for i, m in enumerate(members, 1):
            body = self._personalize(text, m, ctx.guild)
            try:
                await m.send(embed=self._dm_embed(ctx.guild, body))
                sent += 1
                self._log_dm(ctx.author, m, True)
            except (discord.Forbidden, discord.HTTPException):
                failed.append(m)
                self._log_dm(ctx.author, m, False)
            if i % 5 == 0:
                await status.edit(content=f"📨 Progress: **{i}/{len(members)}** (✅ {sent} · ❌ {len(failed)})")
            await asyncio.sleep(DM_DELAY)

        report = f"✅ Delivered **{sent}/{len(members)}**."
        if failed:
            report += (f"\n❌ Couldn't DM {len(failed)} (DMs closed): "
                       + ", ".join(m.mention for m in failed[:20])
                       + (" ..." if len(failed) > 20 else ""))
        await status.edit(content=report, allowed_mentions=discord.AllowedMentions.none())

    @commands.command(name="dm")
    async def dm(self, ctx, user: discord.User, *, message: str):
        """!dm @user your message  (works with a user ID too)"""
        guild_member = ctx.guild.get_member(user.id) if ctx.guild else None
        body = self._personalize(message, guild_member or user, ctx.guild)
        try:
            await user.send(embed=self._dm_embed(ctx.guild, body))
            self._log_dm(ctx.author, user, True)
            await ctx.message.add_reaction("✅")
        except (discord.Forbidden, discord.HTTPException):
            self._log_dm(ctx.author, user, False)
            await ctx.send(f"❌ Couldn't DM **{user}** (their DMs are closed).")

    @commands.command(name="dmusers")
    @commands.guild_only()
    async def dmusers(self, ctx, *, args: str):
        """!dmusers @a @b @c | message"""
        _, text = split_args(args) if "|" in args else ("", "")
        if "|" not in args:
            return await ctx.send("Usage: `!dmusers @user1 @user2 | your message`")
        await self._bulk_dm(ctx, list(ctx.message.mentions), text, f"{len(ctx.message.mentions)} mentioned users")

    @commands.command(name="dmrole")
    @commands.guild_only()
    async def dmrole(self, ctx, *, args: str):
        """!dmrole Head Admin | your message   (plain role names work, fonts ignored)"""
        target, text = split_args(args)
        try:
            role = find_role_fuzzy(ctx.guild, target)
        except ValueError as e:
            return await ctx.send(f"❌ {e}")
        if role.is_default():
            return await ctx.send("❌ DMing @everyone is blocked (it would violate Discord's spam rules).")
        await self._bulk_dm(ctx, list(role.members), text, f"role {role.name}")

    @commands.command(name="dmhistory")
    async def dmhistory(self, ctx):
        """Last DMs the bot sent."""
        text = "\n".join(reversed(self.dm_log)) or "*No DMs sent since the bot started.*"
        await ctx.send(embed=make_embed("📜 Recent DMs", text[:4000]),
                       allowed_mentions=discord.AllowedMentions.none())

    @commands.command(name="deletedm")
    async def deletedm(self, ctx, user: discord.User, count: int = 10):
        """!deletedm @user [count] - delete the bot's recent DMs to someone."""
        dm = user.dm_channel or await user.create_dm()
        removed = 0
        async for m in dm.history(limit=100):
            if m.author.id == self.bot.user.id:
                try:
                    await m.delete()
                    removed += 1
                except discord.HTTPException:
                    pass
                await asyncio.sleep(0.5)
                if removed >= count:
                    break
        await ctx.send(f"🗑️ Deleted **{removed}** of my messages in the DM with **{user}**.")

    # ═════════════════════════ ANNOUNCEMENTS ═══════════════════════
    @commands.command(name="compose")
    @commands.guild_only()
    async def compose(self, ctx, channel: discord.TextChannel = None):
        """!compose #channel - opens a popup form (title, text, color, ping, image)."""
        channel = channel or ctx.channel
        await ctx.send(f"✍️ Writing an announcement for {channel.mention}:",
                       view=ComposeView(ctx.author.id, channel))

    @commands.command(name="devannounce")
    @commands.guild_only()
    async def devannounce(self, ctx, channel: discord.TextChannel, ping: str, *, args: str):
        """!devannounce #channel <everyone|here|none|role> Title | Text"""
        title, _, text = args.partition("|")
        if not text.strip():
            return await ctx.send("Usage: `!devannounce #channel none Title | Text`")
        content, allowed = None, discord.AllowedMentions.none()
        if ping.lower() in ("everyone", "here"):
            content, allowed = f"@{ping.lower()}", discord.AllowedMentions(everyone=True)
        elif ping.lower() != "none":
            try:
                role = find_role_fuzzy(ctx.guild, ping)
            except ValueError as e:
                return await ctx.send(f"❌ {e}")
            content, allowed = role.mention, discord.AllowedMentions(roles=[role])
        embed = make_embed("📢 " + title.strip(), text.strip(), ACCENT,
                           footer=f"Announced by {ctx.author.display_name}")
        await channel.send(content=content, embed=embed, allowed_mentions=allowed)
        await ctx.message.add_reaction("✅")

    @commands.command(name="say")
    @commands.guild_only()
    async def say(self, ctx, channel: discord.TextChannel, *, text: str):
        """!say #channel text - the bot posts plain text (no pings)."""
        await channel.send(text, allowed_mentions=discord.AllowedMentions.none())
        await ctx.message.add_reaction("✅")

    @commands.command(name="embed")
    @commands.guild_only()
    async def embed_cmd(self, ctx, channel: discord.TextChannel, *, args: str):
        """!embed #channel Title | Description | FFD700(optional color)"""
        parts = [p.strip() for p in args.split("|")]
        if len(parts) < 2:
            return await ctx.send("Usage: `!embed #channel Title | Description | FFD700`")
        color = parse_color(parts[2]) if len(parts) > 2 else ACCENT
        await channel.send(embed=make_embed(parts[0], parts[1], color),
                           allowed_mentions=discord.AllowedMentions.none())
        await ctx.message.add_reaction("✅")

    @commands.command(name="edit")
    async def edit_cmd(self, ctx, message: discord.Message, *, text: str):
        """!edit <message link> new text - edit one of the bot's messages."""
        if message.author.id != self.bot.user.id:
            return await ctx.send("❌ I can only edit my own messages.")
        await message.edit(content=text, allowed_mentions=discord.AllowedMentions.none())
        await ctx.message.add_reaction("✅")

    @commands.command(name="broadcast")
    @commands.guild_only()
    async def broadcast(self, ctx, *, args: str):
        """!broadcast news | Title | Text  -> posts in EVERY channel whose name contains 'news'."""
        parts = [p.strip() for p in args.split("|")]
        if len(parts) < 3:
            return await ctx.send("Usage: `!broadcast <channel keyword> | Title | Text`")
        keyword, title, text = norm(parts[0]), parts[1], parts[2]
        channels = [c for c in ctx.guild.text_channels
                    if keyword in norm(c.name) and c.permissions_for(ctx.guild.me).send_messages]
        if not channels:
            return await ctx.send(f"❌ No channels contain `{keyword}`.")
        if len(channels) > MAX_BROADCAST_CHANNELS:
            return await ctx.send(f"❌ {len(channels)} channels match, above the cap of {MAX_BROADCAST_CHANNELS}.")
        preview = make_embed("📡 Confirm broadcast", f"**{title}**\n{text}"[:1500], ACCENT)
        preview.add_field(name="Channels", value=f"**{len(channels)}** channels containing `{keyword}`")
        if not await self._confirm(ctx, preview):
            return
        done = 0
        for ch in channels:
            try:
                await ch.send(embed=make_embed("📢 " + title, text, ACCENT,
                                               footer=f"Announced by {ctx.author.display_name}"),
                              allowed_mentions=discord.AllowedMentions.none())
                done += 1
            except discord.HTTPException:
                pass
            await asyncio.sleep(BROADCAST_DELAY)
        await ctx.send(f"✅ Broadcast sent to **{done}/{len(channels)}** channels.")

    # ═════════════════════════════ SCHEDULER ═══════════════════════
    async def _run_schedule(self, sid):
        item = self.schedules[sid]
        try:
            await asyncio.sleep(item["delay"])
            await item["channel"].send(
                embed=make_embed("📢 " + item["title"], item["text"], ACCENT, footer="Scheduled announcement"),
                allowed_mentions=discord.AllowedMentions.none())
        except asyncio.CancelledError:
            raise
        except discord.HTTPException:
            pass
        finally:
            self.schedules.pop(sid, None)

    @commands.command(name="schedule")
    @commands.guild_only()
    async def schedule(self, ctx, delay: str, channel: discord.TextChannel, *, args: str):
        """!schedule 30m #channel Title | Text   (units: s m h d)  - lost if the bot restarts."""
        seconds = parse_duration(delay)
        if not seconds or seconds > 30 * 86400:
            return await ctx.send("❌ Use a delay like `30s`, `10m`, `2h` or `1d` (max 30d).")
        title, _, text = args.partition("|")
        if not text.strip():
            return await ctx.send("Usage: `!schedule 30m #channel Title | Text`")
        sid = self._next_id
        self._next_id += 1
        self.schedules[sid] = dict(
            delay=seconds, when=int(time.time()) + seconds, channel=channel,
            title=title.strip(), text=text.strip(),
            task=asyncio.create_task(self._run_schedule(sid)))
        await ctx.send(f"⏰ Scheduled **#{sid}** for <t:{self.schedules[sid]['when']}:R> in {channel.mention}.")

    @commands.command(name="schedules")
    async def schedules_cmd(self, ctx):
        """List pending scheduled announcements."""
        if not self.schedules:
            return await ctx.send("📭 Nothing scheduled.")
        lines = [f"**#{sid}** · <t:{s['when']}:R> · {s['channel'].mention} · {s['title'][:40]}"
                 for sid, s in self.schedules.items()]
        await ctx.send(embed=make_embed("⏰ Scheduled announcements", "\n".join(lines)))

    @commands.command(name="unschedule")
    async def unschedule(self, ctx, sid: int):
        """!unschedule <id> - cancel a scheduled announcement."""
        item = self.schedules.pop(sid, None)
        if not item:
            return await ctx.send("❌ No schedule with that ID.")
        item["task"].cancel()
        await ctx.send(f"🗑️ Cancelled schedule **#{sid}**.")

    # ═════════════════════════════ EXTRAS ══════════════════════════
    @commands.command(name="poll")
    @commands.guild_only()
    async def poll(self, ctx, *, args: str):
        """!poll Question | Option 1 | Option 2 | ... (up to 10)"""
        parts = [p.strip() for p in args.split("|") if p.strip()]
        if len(parts) < 3 or len(parts) > 11:
            return await ctx.send("Usage: `!poll Question | Option 1 | Option 2` (2-10 options)")
        question, options = parts[0], parts[1:]
        desc = "\n".join(f"{NUMBER_EMOJI[i]} {o}" for i, o in enumerate(options))
        msg = await ctx.send(embed=make_embed("📊 " + question, desc, ACCENT,
                                              footer=f"Poll by {ctx.author.display_name}"))
        for i in range(len(options)):
            await msg.add_reaction(NUMBER_EMOJI[i])

    @commands.command(name="roleinfo")
    @commands.guild_only()
    async def roleinfo(self, ctx, *, role: str):
        """!roleinfo Head Admin"""
        try:
            r = find_role_fuzzy(ctx.guild, role)
        except ValueError as e:
            return await ctx.send(f"❌ {e}")
        perms = [n.replace("_", " ").title() for n, v in r.permissions if v]
        if r.permissions.administrator:
            perms = ["Administrator (everything)"]
        e = make_embed(f"🎭 {r.name}", f"ID: `{r.id}`", r.colour.value or ACCENT)
        e.add_field(name="Members", value=len(r.members))
        e.add_field(name="Position", value=r.position)
        e.add_field(name="Color", value=f"#{r.colour.value:06X}")
        e.add_field(name="Hoisted", value="Yes" if r.hoist else "No")
        e.add_field(name="Mentionable", value="Yes" if r.mentionable else "No")
        e.add_field(name="Created", value=discord.utils.format_dt(r.created_at, "D"))
        e.add_field(name="Permissions", value=(", ".join(perms) or "None")[:1000], inline=False)
        await ctx.send(embed=e)

    @commands.command(name="userinfo")
    async def userinfo(self, ctx, user: discord.User):
        """!userinfo @user"""
        member = ctx.guild.get_member(user.id) if ctx.guild else None
        e = make_embed(f"👤 {user}", f"ID: `{user.id}`", ACCENT)
        e.set_thumbnail(url=user.display_avatar.url)
        e.add_field(name="Account created", value=discord.utils.format_dt(user.created_at, "D"))
        e.add_field(name="Bot", value="Yes" if user.bot else "No")
        if member:
            e.add_field(name="Joined server", value=discord.utils.format_dt(member.joined_at, "D")
                        if member.joined_at else "?")
            e.add_field(name="Top role", value=member.top_role.mention)
            e.add_field(name="Roles", value=len(member.roles) - 1)
        await ctx.send(embed=e)

    @commands.command(name="rolemembers")
    @commands.guild_only()
    async def rolemembers(self, ctx, *, role: str):
        """!rolemembers Head Admin - list everyone with a role."""
        try:
            r = find_role_fuzzy(ctx.guild, role)
        except ValueError as e:
            return await ctx.send(f"❌ {e}")
        text = ", ".join(m.mention for m in r.members) or "*Nobody has this role.*"
        if len(text) > 4000:
            text = text[:3990] + "..."
        await ctx.send(embed=make_embed(f"👥 {r.name} ({len(r.members)})", text, r.colour.value or ACCENT),
                       allowed_mentions=discord.AllowedMentions.none())

    # ═════════════════════════════ BOT CONTROL ═════════════════════
    @commands.command(name="botstats")
    async def botstats(self, ctx):
        """Bot health and numbers."""
        up = int(time.time() - self.started)
        d, rem = divmod(up, 86400)
        h, rem = divmod(rem, 3600)
        m, s = divmod(rem, 60)
        e = make_embed("🤖 " + rounded("Bot Stats"), "", ACCENT)
        e.add_field(name="Latency", value=f"{self.bot.latency * 1000:.0f} ms")
        e.add_field(name="Uptime", value=f"{d}d {h}h {m}m {s}s")
        e.add_field(name="Servers", value=len(self.bot.guilds))
        e.add_field(name="Users", value=sum(g.member_count or 0 for g in self.bot.guilds))
        e.add_field(name="Commands", value=len(self.bot.commands))
        e.add_field(name="Pending schedules", value=len(self.schedules))
        e.add_field(name="Versions", value=f"Python {platform.python_version()} · discord.py {discord.__version__}",
                    inline=False)
        await ctx.send(embed=e)

    @commands.command(name="ping")
    async def ping(self, ctx):
        await ctx.send(f"🏓 Pong! `{self.bot.latency * 1000:.0f} ms`")

    @commands.command(name="setstatus")
    async def setstatus(self, ctx, kind: str, *, text: str = ""):
        """!setstatus playing|watching|listening|competing <text>   or   !setstatus reset"""
        kind = kind.lower()
        if kind == "reset":
            await self.bot.change_presence(activity=discord.Game(name=f"🎮 {ctx.prefix}staffhelp"))
            return await ctx.send("✅ Status reset.")
        types = {"playing": discord.ActivityType.playing, "watching": discord.ActivityType.watching,
                 "listening": discord.ActivityType.listening, "competing": discord.ActivityType.competing}
        if kind not in types or not text:
            return await ctx.send("Usage: `!setstatus playing|watching|listening|competing <text>`")
        await self.bot.change_presence(activity=discord.Activity(type=types[kind], name=text))
        await ctx.send(f"✅ Status set to **{kind} {text}**.")

    @commands.command(name="guilds")
    async def guilds_cmd(self, ctx):
        """List every server the bot is in."""
        lines = [f"**{g.name}** · `{g.id}` · {g.member_count} members" for g in self.bot.guilds]
        await ctx.send(embed=make_embed(f"🌐 Servers ({len(lines)})", "\n".join(lines)[:4000]))

    @commands.command(name="leaveguild")
    async def leaveguild(self, ctx, guild_id: int, confirm: str = ""):
        """!leaveguild <id> confirm"""
        guild = self.bot.get_guild(guild_id)
        if not guild:
            return await ctx.send("❌ I'm not in a server with that ID.")
        if confirm.lower() != "confirm":
            return await ctx.send(f"⚠️ This makes me leave **{guild.name}**. Run `!leaveguild {guild_id} confirm`.")
        await guild.leave()
        await ctx.send(f"👋 Left **{guild.name}**.")

    @commands.command(name="shutdown")
    async def shutdown(self, ctx, confirm: str = ""):
        """!shutdown confirm - stop the bot."""
        if confirm.lower() != "confirm":
            return await ctx.send("⚠️ This stops the bot. Run `!shutdown confirm`.")
        await ctx.send("👋 Shutting down...")
        await self.bot.close()

    @commands.command(name="devhelp")
    async def devhelp(self, ctx):
        """Show all developer commands."""
        e = make_embed("🔧 " + rounded("Developer Tools"), "All of these are **developer-only**.", ACCENT)
        e.add_field(name="📩 Direct messages", value=(
            "`!dm @user text` – DM one person (or by ID)\n"
            "`!dmusers @a @b | text` – DM several people\n"
            "`!dmrole Head Admin | text` – DM everyone with a role\n"
            "`!dmhistory` · `!deletedm @user [n]`\n"
            "Placeholders: `{name}` `{mention}` `{server}`"), inline=False)
        e.add_field(name="📢 Announcements", value=(
            "`!compose #channel` – popup form (title, text, color, ping, image)\n"
            "`!devannounce #channel <ping> Title | Text`\n"
            "`!say #channel text` · `!embed #channel Title | Text | HEX`\n"
            "`!edit <message link> text`\n"
            "`!broadcast news | Title | Text` – post in every channel containing a keyword"), inline=False)
        e.add_field(name="⏰ Scheduler", value=(
            "`!schedule 30m #channel Title | Text` · `!schedules` · `!unschedule <id>`"), inline=False)
        e.add_field(name="🧰 Extras", value=(
            "`!poll Question | A | B` · `!roleinfo <role>` · `!userinfo @user` · `!rolemembers <role>`"),
            inline=False)
        e.add_field(name="🤖 Bot control", value=(
            "`!botstats` · `!ping` · `!setstatus <type> <text>` · `!guilds`\n"
            "`!leaveguild <id> confirm` · `!shutdown confirm`"), inline=False)
        await ctx.send(embed=e)


async def setup(bot: commands.Bot):
    await bot.add_cog(DevTools(bot))
