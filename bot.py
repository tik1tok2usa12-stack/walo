"""
Staff Architect Bot v5  -  discord.py 2.x
-----------------------------------------
* 116 staff roles (+4 tier badges) in a rounded Fredoka-style font, unique HEX colors,
  unique emojis, no overlapping/duplicate role titles
* !makeroles NEVER duplicates: it recognises roles from older versions (script font,
  old emojis) and renames/updates them in place instead of creating new ones
* !cleanroles removes duplicate / leftover roles from older runs
* Among Us STAFF channels + 32 GAME hubs, all with per-role permissions
* Self-role game picker dropdown
* Developer-only tools (DMs by user/role, announcements, scheduler, polls...)
  live in dev_tools.py - keep it in the SAME folder; it loads automatically

Setup:
  pip install -U discord.py
  Set env var DISCORD_TOKEN (or paste the token below).
  Developer Portal -> enable SERVER MEMBERS INTENT + MESSAGE CONTENT INTENT.
  Invite the bot with Administrator and drag its role to the TOP of the role list.

Order of use:
  !makeroles  ->  !cleanroles  ->  !makechannels  ->  !makegames all  ->  !giveallroles @you
"""

import asyncio
import os
import unicodedata
from functools import lru_cache

import discord
from discord.ext import commands

try:                                   # optional: lets you keep the token in a local .env file
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# ───────────────────────────── CONFIG ─────────────────────────────
TOKEN = os.getenv("DISCORD_TOKEN", "YOUR_BOT_TOKEN_HERE")
PREFIX = "!"
DELAY = 1.5                 # seconds between role creations/edits (rate-limit safety)
HOIST = True                # show staff roles separately in the member list
EXTRA_ALLOWED_IDS = {1421599187950370816}   # extra user IDs allowed to run owner-only commands
# Developer-only commands (dev_tools.py). Leave empty to use the bot application's owner from the
# Developer Portal, or list user IDs, e.g. {123456789012345678}
DEV_IDS = set(1421599187950370816)

# "role"   -> a game's channels are only visible to members who picked that game role
# "public" -> everyone can see every game's channels (game role is just for pings)
GAME_ACCESS = "role"

intents = discord.Intents.default()
intents.members = True
intents.message_content = True


class StaffBot(commands.Bot):
    async def setup_hook(self):
        # Re-register the persistent game-picker dropdowns after restarts
        for idx, chunk in enumerate(chunked(GAMES, 25)):
            self.add_view(GamePanel(idx, chunk))
        try:
            await self.load_extension("dev_tools")
            print("🔧 Developer tools loaded (!devhelp)")
        except commands.ExtensionNotFound:
            print("ℹ️ dev_tools.py not found next to this file - developer tools disabled")
        except Exception as e:                       # keep the main bot alive if the add-on breaks
            print(f"⚠️ Could not load dev_tools: {e!r}")


bot = StaffBot(command_prefix=PREFIX, intents=intents, help_command=None, owner_ids=DEV_IDS)


def chunked(seq, n):
    return [seq[i:i + n] for i in range(0, len(seq), n)]


# ─────────────────────────── FONT HELPERS ─────────────────────────
def fancy(text: str) -> str:
    """Bold Script (𝓐𝓫𝓬) - only used by the !script command now."""
    out = []
    for ch in text:
        if "A" <= ch <= "Z":
            out.append(chr(0x1D4D0 + ord(ch) - 65))
        elif "a" <= ch <= "z":
            out.append(chr(0x1D4EA + ord(ch) - 97))
        elif "0" <= ch <= "9":
            out.append(chr(0x1D7CE + ord(ch) - 48))
        else:
            out.append(ch)
    return "".join(out)


def rounded(text: str) -> str:
    """Sans-Serif Bold (𝗔𝗯𝗰) - closest Unicode to Fredoka One. Used for ROLES and CHANNELS."""
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


# ─────────────────── ROLE IDENTITY (anti-duplicate) ───────────────
def has_math_font(s: str) -> bool:
    """True if the name uses a Unicode math font -> it was created by this bot."""
    return any(0x1D400 <= ord(c) <= 0x1D7FF for c in s)


@lru_cache(maxsize=8192)
def role_key(name: str) -> str:
    """
    Identity of a role = its plain letters only. Ignores font AND emoji, so
    '⚔️ 𝓛𝓮𝓪𝓭 𝓜𝓸𝓭' (old) and '🎯 𝗟𝗲𝗮𝗱 𝗠𝗼𝗱𝗲𝗿𝗮𝘁𝗼𝗿' (new) compare by text only.
    """
    n = unicodedata.normalize("NFKC", name).casefold()
    n = "".join(c if (c.isalnum() or c in " -") else " " for c in n)
    return " ".join(n.split())


# Roles that existed in earlier versions and were renamed / removed to avoid overlap
LEGACY_RENAMES = {            # old key -> new key (renamed in place, members keep it)
    "lead mod": "lead moderator",
    "junior mod": "junior moderator",
    "trial mod": "trial moderator",
    "lead builder": "builder",
}
LEGACY_REMOVED = {            # no replacement; deleted by !cleanroles
    "senior mod", "probationary moderator", "head developer", "lead designer",
}


def find_role_by_key(guild, key):
    best = None
    for r in guild.roles:
        if r.managed or r.is_default() or not has_math_font(r.name):
            continue
        if role_key(r.name) == key and (best is None or r.position > best.position):
            best = r
    return best


def find_role(guild, name):
    return find_role_by_key(guild, role_key(name))


# ───────────────────────── COLOR GRADIENTS ────────────────────────
def hex_to_rgb(h: str):
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def gradient(stops, n):
    rgb = [hex_to_rgb(s) for s in stops]
    if n == 1:
        return [(rgb[0][0] << 16) | (rgb[0][1] << 8) | rgb[0][2]]
    segs = len(rgb) - 1
    out = []
    for i in range(n):
        t = i / (n - 1) * segs
        s = min(int(t), segs - 1)
        f = t - s
        a, b = rgb[s], rgb[s + 1]
        r, g, bl = (round(a[k] + (b[k] - a[k]) * f) for k in range(3))
        out.append((r << 16) | (g << 8) | bl)
    return out


# Color palette: name -> (embed HEX, dot emoji used in channel names)
CREW = {
    "red":    (0xC51111, "🔴"), "blue":   (0x132ED1, "🔵"), "green":  (0x117F2D, "🟢"),
    "pink":   (0xED54BA, "🩷"), "orange": (0xEF7D0E, "🟠"), "yellow": (0xF5F557, "🟡"),
    "black":  (0x3F474E, "⚫"), "white":  (0xD6E0F0, "⚪"), "purple": (0x6B2FBB, "🟣"),
    "brown":  (0x71491E, "🟤"), "cyan":   (0x38FEDC, "🩵"), "lime":   (0x50EF39, "💚"),
}

# ───────────────────────── PERMISSION SETS ────────────────────────
P = discord.Permissions
OWNER_PERMS = P(administrator=True)
ADMIN_PERMS = P(
    view_channel=True, manage_channels=True, manage_roles=True, manage_messages=True,
    kick_members=True, ban_members=True, moderate_members=True, manage_nicknames=True,
    view_audit_log=True, mention_everyone=True, manage_events=True,
    create_instant_invite=True, mute_members=True, deafen_members=True, move_members=True,
)
MOD_PERMS = P(
    view_channel=True, manage_messages=True, kick_members=True, ban_members=True,
    moderate_members=True, manage_nicknames=True, view_audit_log=True,
    mute_members=True, deafen_members=True, move_members=True,
)
OPS_PERMS = P(
    view_channel=True, manage_messages=True, manage_events=True,
    create_instant_invite=True, use_external_emojis=True, view_audit_log=True,
)

# ─────────────────────────── ROLE TABLES ──────────────────────────
# (emoji, plain English name, optional fixed HEX color)  -  every title and emoji is unique
TIERS = {
    "owner": dict(
        label="Ownership", emoji="👑", perms=OWNER_PERMS,
        stops=["FFD700", "FF8C00", "DC143C", "8B0000", "6A0DAD"],
        roles=[
            ("🐱", "Qattos", 0xFF2D95),           # unique top-tier owner
            ("🐾", "9attos", 0x00FFC8),           # the only non-English-style name
            ("👑", "Supreme Leader"), ("🏛️", "Server Creator"), ("🌟", "Founding Father"),
            ("🪙", "Chairman"), ("🌌", "Grand Overseer"), ("🏆", "Chief Executive Officer"),
            ("💼", "Board Member"), ("🦁", "Head Owner"), ("💎", "Executive Owner"),
            ("🏰", "Owner"), ("📜", "Managing Owner"), ("⚜️", "Head Co-Owner"),
            ("🥇", "Co-Owner Tier I"), ("🥈", "Co-Owner Tier II"), ("🥉", "Co-Owner Tier III"),
        ],
    ),
    "admin": dict(
        label="Administration", emoji="🛡️", perms=ADMIN_PERMS,
        stops=["B00020", "C2185B", "7B1FA2", "512DA8", "1E40FF"],
        roles=[
            ("🛡️", "Chief Administrator"), ("🏯", "Deputy Administrator"), ("🚩", "Lead Admin"),
            ("🎗️", "Head Admin"), ("🏵️", "Senior Admin"), ("🔮", "Admin"),
            ("🌀", "Junior Admin"), ("🧪", "Trial Admin"), ("🖥️", "Systems Admin"),
            ("🌐", "Network Admin"), ("🔐", "Security Admin"), ("🗄️", "Database Admin"),
            ("🤖", "Bot Admin"), ("📊", "Operations Director"), ("📋", "Staff Director"),
            ("💠", "Executive Director"), ("🏢", "Managing Director"), ("🔒", "Security Director"),
            ("⚖️", "Moderation Director"), ("🧠", "Technical Director"), ("🧭", "Strategy Director"),
            ("📑", "Compliance Director"), ("🗂️", "Administration Director"),
            ("🔷", "Assistant Director"), ("🔹", "Associate Director"), ("🔸", "Deputy Director"),
            ("🎖️", "Executive Administrator"), ("🏅", "Senior Executive"), ("💫", "Executive"),
            ("📎", "Executive Assistant"), ("🪪", "Head of Staff"), ("🗝️", "Chief of Staff"),
            ("⚙️", "Chief Operating Officer"),
        ],
    ),
    "mod": dict(
        label="Moderation", emoji="⚔️", perms=MOD_PERMS,
        stops=["00B8FF", "00E5FF", "00FFA3", "39FF14"],
        roles=[
            ("⚔️", "Chief Moderator"), ("🗡️", "Head Moderator"), ("🎩", "Executive Moderator"),
            ("🎯", "Lead Moderator"), ("🌍", "Global Moderator"), ("🧿", "Senior Moderator"),
            ("🥋", "Deputy Moderator"), ("🔨", "Moderator"), ("🪖", "Associate Moderator"),
            ("🌱", "Junior Moderator"), ("🔰", "Trial Moderator"), ("💬", "Chat Moderator"),
            ("🎙️", "Voice Moderator"), ("🎫", "Ticket Moderator"), ("🎞️", "Media Moderator"),
            ("🎉", "Event Moderator"), ("🚨", "Security Lead"), ("👮", "Enforcement Officer"),
            ("📕", "Discipline Manager"), ("📨", "Appeals Officer"), ("📬", "Appeals Manager"),
            ("⚒️", "Ban Review Officer"), ("🦺", "Safety Officer"), ("🕊️", "Trust and Safety Lead"),
            ("🚓", "Patrol Supervisor"), ("💭", "Chat Supervisor"), ("🔊", "Voice Supervisor"),
            ("⏱️", "Shift Supervisor"), ("🏹", "Senior Supervisor"), ("🦉", "Head Supervisor"),
            ("🗼", "Watch Captain"), ("⛓️", "Warden"), ("🦅", "Sentinel"),
            ("🐺", "Guardian Lead"), ("📥", "Report Handler"), ("🚧", "Raid Defense Lead"),
            ("⚠️", "Warning Officer"),
        ],
    ),
    "ops": dict(
        label="Special Operations", emoji="✨", perms=OPS_PERMS,
        stops=["FF00FF", "FF6EC7", "FFAA00", "FFEA00", "00E676", "00BFA5"],
        roles=[
            ("💻", "Lead Developer"), ("👾", "Bot Developer"), ("🛠️", "Automation Engineer"),
            ("⌨️", "Developer"), ("🔧", "Junior Developer"), ("🎨", "Head Designer"),
            ("🖌️", "Graphic Designer"), ("📐", "UI Designer"), ("🏗️", "Head Builder"),
            ("🧱", "Builder"), ("🎪", "Event Director"), ("🎊", "Event Manager"),
            ("🎤", "Event Host"), ("🎧", "Support Lead"), ("📞", "Support Manager"),
            ("💁", "Support Agent"), ("🏘️", "Community Director"), ("🤝", "Community Manager"),
            ("🍀", "Community Helper"), ("📣", "Staff Recruiter"), ("🧲", "Head Recruiter"),
            ("🎓", "Staff Trainer"), ("✳️", "Trial Staff"), ("⭐", "Staff Member"),
            ("🌠", "Senior Staff"), ("📝", "Content Manager"), ("🤵", "Partnership Manager"),
            ("📰", "Public Relations Manager"), ("📱", "Social Media Manager"),
        ],
    ),
}
TIER_ORDER = ["owner", "admin", "mod", "ops"]

ROLE_SPECS = []        # every staff role, top of hierarchy -> bottom
BADGE_NAMES = {}       # tier key -> badge role name
_used = set()          # colors in use
_emoji_used = set()    # emojis in use
_SPARE_EMOJI = ["🌙", "☀️", "🌊", "🍁", "🪐", "🔭", "🧬", "🎲", "🎡", "🛸", "🪄", "🧩",
                "🎸", "🥂", "🪁", "🧊", "🌋", "🏔️", "🦄", "🐉", "🦋", "🐬", "🌸", "🍉"]

for _t in TIERS.values():                       # reserve fixed colors first
    for _r in _t["roles"]:
        if len(_r) == 3:
            _used.add(_r[2])


def _unique(c: int) -> int:
    while c in _used or c == 0:
        c += 1
    _used.add(c)
    return c


def _unique_emoji(e: str) -> str:
    """Guarantee no two roles share an emoji (falls back to a spare one)."""
    if e in _emoji_used:
        e = next(s for s in _SPARE_EMOJI if s not in _emoji_used)
    _emoji_used.add(e)
    return e


for _key in TIER_ORDER:
    _t = TIERS[_key]
    _badge = f"━━ {_t['emoji']} {rounded(_t['label'])} ━━"
    _emoji_used.add(_t["emoji"])
    BADGE_NAMES[_key] = _badge
    ROLE_SPECS.append(dict(
        name=_badge, plain=f"{_t['label']} Team", color=_unique(gradient(_t["stops"], 2)[0]),
        perms=_t["perms"], tier=_key, badge=True,
    ))
    _cols = gradient(_t["stops"], len(_t["roles"]))
    for _r, _c in zip(_t["roles"], _cols):
        emoji, plain = _unique_emoji(_r[0]), _r[1]
        color = _r[2] if len(_r) == 3 else _unique(_c)
        ROLE_SPECS.append(dict(
            name=f"{emoji} {rounded(plain)}", plain=plain, color=color,
            perms=_t["perms"], tier=_key, badge=False,
        ))

# Safety net: no two specs may share an identity (plain text)
assert len({role_key(s["name"]) for s in ROLE_SPECS}) == len(ROLE_SPECS), "duplicate role titles in TIERS"
STAFF_SPECS = [s for s in ROLE_SPECS if not s["badge"]]


# ───────────────────────────── HELPERS ────────────────────────────
def guild_owner_only():
    async def predicate(ctx):
        if ctx.guild is None:
            return False
        if ctx.author.id == ctx.guild.owner_id or ctx.author.id in EXTRA_ALLOWED_IDS:
            return True
        raise commands.CheckFailure("Only the server owner can use this command.")
    return commands.check(predicate)


def get_role(guild, spec):
    return find_role(guild, spec["name"])


def badge_role(guild, key):
    return find_role(guild, BADGE_NAMES[key])


async def sort_roles(guild):
    """Re-order our staff roles so the hierarchy matches ROLE_SPECS (top -> bottom)."""
    me_top = guild.me.top_role
    ordered = [r for r in (get_role(guild, s) for s in ROLE_SPECS) if r and r < me_top]
    if len(ordered) < 2:
        return
    slots = sorted((r.position for r in ordered), reverse=True)
    await guild.edit_role_positions(dict(zip(ordered, slots)))


def find_spec(query: str):
    q = query.lower().strip()
    exact = [s for s in ROLE_SPECS if s["plain"].lower() == q]
    if exact:
        return exact
    return [s for s in ROLE_SPECS if q in s["plain"].lower()]


def duplicate_groups(guild):
    """key -> [roles] for every identity that appears more than once among OUR roles."""
    groups = {}
    for r in guild.roles:
        if r.managed or r.is_default() or not has_math_font(r.name):
            continue
        groups.setdefault(role_key(r.name), []).append(r)
    return {k: v for k, v in groups.items() if len(v) > 1}


_role_locks = {}


# ─────────────────────────── ROLE COMMANDS ────────────────────────
@bot.command(name="makeroles")
@commands.guild_only()
@guild_owner_only()
async def makeroles(ctx):
    """Create / update every staff role. Never duplicates: existing roles are updated in place."""
    guild = ctx.guild
    lock = _role_locks.setdefault(guild.id, asyncio.Lock())
    if lock.locked():
        return await ctx.send("⏳ The role builder is already running here. Please wait for it to finish.")

    async with lock:
        me_top = guild.me.top_role
        creates, edits, skipped = [], [], 0
        for spec in ROLE_SPECS:
            key = role_key(spec["name"])
            role = find_role_by_key(guild, key)
            if role is None:                                   # adopt a legacy-named role
                for old, new in LEGACY_RENAMES.items():
                    if new == key:
                        role = find_role_by_key(guild, old)
                        break
            if role is None:
                creates.append(spec)
            elif role >= me_top:
                skipped += 1
            elif (role.name != spec["name"] or role.colour.value != spec["color"]
                  or role.permissions != spec["perms"] or role.hoist != HOIST):
                edits.append((role, spec))

        if not creates and not edits:
            msg = "✅ All staff roles already exist and are up to date. Nothing duplicated."
            if duplicate_groups(guild):
                msg += "\n⚠️ Duplicate roles from older runs were found — run `!cleanroles`."
            return await ctx.send(msg)
        if len(guild.roles) + len(creates) > 250:
            return await ctx.send("❌ That would exceed Discord's 250-role limit.")

        total = len(creates) + len(edits)
        status = await ctx.send(
            f"🛠️ **{len(edits)}** existing roles to update (font/color/perms), "
            f"**{len(creates)}** new roles to create. (~{int(total * DELAY)}s)")

        done, updated, created, failed = 0, 0, 0, []
        for role, spec in edits:                               # update in place (no duplicates)
            try:
                await role.edit(
                    name=spec["name"], colour=discord.Colour(spec["color"]),
                    permissions=spec["perms"], hoist=HOIST, reason=f"!makeroles by {ctx.author}")
                updated += 1
            except discord.HTTPException as e:
                failed.append(f"{spec['plain']} ({e.status})")
            done += 1
            if done % 10 == 0:
                await status.edit(content=f"🛠️ Progress: **{done}/{total}**")
            await asyncio.sleep(DELAY)

        for spec in creates:
            if find_role(guild, spec["name"]):                 # last-second duplicate guard
                continue
            try:
                await guild.create_role(
                    name=spec["name"], colour=discord.Colour(spec["color"]),
                    permissions=spec["perms"], hoist=HOIST, mentionable=False,
                    reason=f"!makeroles by {ctx.author}")
                created += 1
            except discord.HTTPException as e:
                failed.append(f"{spec['plain']} ({e.status})")
            done += 1
            if done % 10 == 0:
                await status.edit(content=f"🛠️ Progress: **{done}/{total}**")
            await asyncio.sleep(DELAY)

        try:
            await sort_roles(guild)
        except discord.HTTPException:
            pass

        msg = f"✅ Updated **{updated}** roles in place, created **{created}** new ones."
        if skipped:
            msg += f"\n⚠️ Skipped {skipped} roles above my highest role — move my role to the top."
        if failed:
            msg += f"\n⚠️ Failed: {', '.join(failed[:15])}"
        dups = duplicate_groups(guild)
        legacy = [r for r in guild.roles if has_math_font(r.name) and role_key(r.name) in LEGACY_REMOVED]
        if dups or legacy:
            msg += (f"\n🧹 Found {sum(len(v) - 1 for v in dups.values())} duplicate and "
                    f"{len(legacy)} leftover roles from older versions — run `!cleanroles`.")
        await status.edit(content=msg)


@bot.command(name="cleanroles")
@commands.guild_only()
@guild_owner_only()
async def cleanroles(ctx, confirm: str = ""):
    """Remove duplicate + leftover roles from older runs. Preview first; add `confirm` to delete."""
    guild = ctx.guild
    me_top = guild.me.top_role
    extras = []                                               # (role, role_to_keep)
    for key, lst in duplicate_groups(guild).items():
        lst.sort(key=lambda r: (len(r.members), r.position), reverse=True)
        keep = lst[0]
        extras += [(r, keep) for r in lst[1:]]
    for r in guild.roles:
        if has_math_font(r.name) and role_key(r.name) in LEGACY_REMOVED and not r.managed:
            extras.append((r, None))

    if not extras:
        return await ctx.send("✅ No duplicate or leftover roles found.")

    if confirm.lower() != "confirm":
        lines = [f"• {r.name} ({len(r.members)} members)" + (" → merged into the kept copy" if k else " → removed")
                 for r, k in extras[:25]]
        more = f"\n…and {len(extras) - 25} more" if len(extras) > 25 else ""
        return await ctx.send(
            f"🧹 **{len(extras)}** roles would be removed (members of duplicates are moved to the kept role):\n"
            + "\n".join(lines) + more + "\n\nRun `!cleanroles confirm` to proceed.")

    status = await ctx.send(f"🧹 Cleaning {len(extras)} roles...")
    removed = 0
    for r, keep in extras:
        if r >= me_top:
            continue
        try:
            if keep and keep < me_top:
                for m in list(r.members):
                    if keep not in m.roles:
                        await m.add_roles(keep, reason="Merging duplicate role")
                        await asyncio.sleep(0.3)
            await r.delete(reason=f"!cleanroles by {ctx.author}")
            removed += 1
        except discord.HTTPException:
            pass
        await asyncio.sleep(DELAY)
    await status.edit(content=f"✅ Removed **{removed}** duplicate/leftover roles.")


@bot.command(name="giveallroles")
@commands.guild_only()
@guild_owner_only()
async def giveallroles(ctx, member: discord.Member):
    """Give every staff role to a member in one go."""
    guild = ctx.guild
    me_top = guild.me.top_role
    roles = [r for r in (get_role(guild, s) for s in ROLE_SPECS) if r and r < me_top]
    if not roles:
        return await ctx.send("❌ No assignable roles found. Run `!makeroles` first.")
    try:
        await member.add_roles(*roles, reason=f"!giveallroles by {ctx.author}")
    except discord.HTTPException:
        for i in range(0, len(roles), 20):                 # fallback: chunked
            await member.add_roles(*roles[i:i + 20])
            await asyncio.sleep(1)
    await ctx.send(f"👑 Gave **{len(roles)}** staff roles to {member.mention}.")


@bot.command(name="removeallroles")
@commands.guild_only()
@guild_owner_only()
async def removeallroles(ctx, member: discord.Member):
    """Strip every staff role from a member."""
    ours = {get_role(ctx.guild, s) for s in ROLE_SPECS}
    roles = [r for r in member.roles if r in ours]
    if roles:
        await member.remove_roles(*roles, reason=f"!removeallroles by {ctx.author}")
    await ctx.send(f"🧹 Removed **{len(roles)}** staff roles from {member.mention}.")


@bot.command(name="giverole")
@commands.guild_only()
@commands.has_permissions(manage_roles=True)
async def giverole(ctx, member: discord.Member, *, name: str):
    """!giverole @user Head Admin  (also adds the tier badge for channel access)"""
    await _change_role(ctx, member, name, add=True)


@bot.command(name="takerole")
@commands.guild_only()
@commands.has_permissions(manage_roles=True)
async def takerole(ctx, member: discord.Member, *, name: str):
    """!takerole @user Head Admin"""
    await _change_role(ctx, member, name, add=False)


async def _change_role(ctx, member, name, add):
    matches = find_spec(name)
    if not matches:
        return await ctx.send("❌ No staff role matches that name. See `!rolelist`.")
    if len(matches) > 1:
        names = ", ".join(f"`{m['plain']}`" for m in matches[:15])
        return await ctx.send(f"🤔 Multiple matches, be more specific: {names}")
    spec = matches[0]
    role = get_role(ctx.guild, spec)
    if not role:
        return await ctx.send("❌ That role doesn't exist yet. Run `!makeroles`.")
    if role >= ctx.guild.me.top_role:
        return await ctx.send("❌ That role is above my highest role.")
    if ctx.author.id != ctx.guild.owner_id and role >= ctx.author.top_role:
        return await ctx.send("❌ You can't manage a role equal to/above your own.")
    if add:
        to_add = [role]
        badge = badge_role(ctx.guild, spec["tier"])
        if badge and badge not in member.roles and badge < ctx.guild.me.top_role:
            to_add.append(badge)
        await member.add_roles(*to_add)
        await ctx.send(f"✅ Gave {role.mention} to {member.mention}.")
    else:
        await member.remove_roles(role)
        await ctx.send(f"✅ Removed {role.mention} from {member.mention}.")


@bot.command(name="sortroles")
@commands.guild_only()
@guild_owner_only()
async def sortroles_cmd(ctx):
    """Re-order staff roles into the correct hierarchy."""
    await sort_roles(ctx.guild)
    await ctx.send("✅ Staff roles re-ordered.")


@bot.command(name="deleteroles")
@commands.guild_only()
@guild_owner_only()
async def deleteroles(ctx, confirm: str = ""):
    """Delete ALL generated staff roles. Usage: !deleteroles confirm"""
    if confirm.lower() != "confirm":
        return await ctx.send("⚠️ This deletes every generated staff role. Run `!deleteroles confirm` to proceed.")
    roles = [r for r in (get_role(ctx.guild, s) for s in ROLE_SPECS) if r]
    status = await ctx.send(f"🗑️ Deleting {len(roles)} roles...")
    done = 0
    for r in roles:
        try:
            await r.delete(reason=f"!deleteroles by {ctx.author}")
            done += 1
        except discord.HTTPException:
            pass
        await asyncio.sleep(DELAY)
    await status.edit(content=f"🗑️ Deleted **{done}/{len(roles)}** roles.")


@bot.command(name="rolelist")
@commands.guild_only()
async def rolelist(ctx):
    """Show all generated staff roles with member counts."""
    embed = discord.Embed(title="📜 Staff Role Hierarchy", color=0x9B59B6)
    for key in TIER_ORDER:
        lines = []
        for s in ROLE_SPECS:
            if s["tier"] == key and not s["badge"]:
                r = get_role(ctx.guild, s)
                lines.append(f"{r.mention if r else '`missing`'} · {len(r.members) if r else 0}")
        chunks, cur = [], ""
        for line in lines:
            if len(cur) + len(line) + 1 > 1000:
                chunks.append(cur)
                cur = ""
            cur += line + "\n"
        chunks.append(cur)
        for idx, ch in enumerate(chunks):
            embed.add_field(
                name=f"{TIERS[key]['emoji']} {TIERS[key]['label']}" + (" (cont.)" if idx else ""),
                value=ch or "—", inline=False)
    await ctx.send(embed=embed)


# ──────────────────────── STAFF DIRECTORY ─────────────────────────
def build_directory_pages(guild):
    order = [r for r in (get_role(guild, s) for s in STAFF_SPECS) if r]
    rank = {r.id: i for i, r in enumerate(order)}
    groups = {}
    for m in guild.members:
        if m.bot:
            continue
        held = [rank[r.id] for r in m.roles if r.id in rank]
        if held:
            groups.setdefault(min(held), []).append(m)       # highest rank only
    lines = [f"{order[i].mention} — " + ", ".join(m.mention for m in groups[i]) for i in sorted(groups)]
    if not lines:
        lines = ["*No crewmates found yet.*"]
    pages, cur = [], ""
    for line in lines:
        if len(cur) + len(line) + 2 > 3800:
            pages.append(cur)
            cur = ""
        cur += line + "\n\n"
    pages.append(cur)
    return [discord.Embed(
        title="📇 " + rounded("Crew Roster") + (f" ({i + 1}/{len(pages)})" if len(pages) > 1 else ""),
        description=p, color=CREW["yellow"][0]) for i, p in enumerate(pages)]


@bot.command(name="staffdirectory", aliases=["staff", "directory"])
@commands.guild_only()
async def staffdirectory(ctx):
    """Show every staff member grouped by their highest rank."""
    for e in build_directory_pages(ctx.guild):
        await ctx.send(embed=e)


# ═══════════════════ AMONG US STAFF CHANNEL BUILDER ═══════════════
# Permission tokens: a tier key ("owner","admin","mod","ops" -> tier badge role)
#                    or an exact plain role name ("Lead Developer", ...).
ALL = ["owner", "admin", "mod", "ops"]
MOD_UP = ["owner", "admin", "mod"]
ADMIN_UP = ["owner", "admin"]
OWNER = ["owner"]

DEVS = ["Lead Developer", "Bot Developer", "Automation Engineer", "Developer", "Junior Developer"]
DESIGNERS = ["Head Designer", "Graphic Designer", "UI Designer", "Head Builder", "Builder"]
SUPPORT = ["Support Lead", "Support Manager", "Support Agent",
           "Community Director", "Community Manager", "Community Helper"]
EVENTS = ["Event Director", "Event Manager", "Event Host"]
RECRUIT = ["Staff Recruiter", "Head Recruiter", "Staff Trainer"]
MEDIA = ["Content Manager", "Partnership Manager", "Public Relations Manager", "Social Media Manager"]

# channel tuple: (kind, color, room_emoji, name, can_see, can_write, topic, key)
LAYOUT = [
    ("Lobby", "🚀", "cyan", [
        ("text", "cyan", "🚀", "lobby rules", ALL, OWNER,
         "Rules every crewmate must follow.", "rules"),
        ("text", "red", "📢", "emergency broadcast", ALL, ADMIN_UP,
         "Official staff announcements.", None),
        ("text", "yellow", "📇", "crew roster", ALL, ADMIN_UP,
         "Who is who on the ship.", "directory"),
        ("text", "lime", "🆕", "task updates", ALL, MOD_UP,
         "Policy changes and new procedures.", None),
    ]),
    ("Cafeteria", "🍽️", "yellow", [
        ("text", "yellow", "🍽️", "cafeteria", ALL, ALL,
         "Hang out with the whole crew.", None),
        ("text", "white", "📡", "comms room", ALL, ALL,
         "Bot commands for staff.", None),
        ("text", "pink", "💡", "suggestion box", ALL, ALL,
         "Ideas to make the ship better.", None),
        ("text", "orange", "🎮", "game night", ALL, ALL,
         "Plan staff game nights.", None),
    ]),
    ("Medbay", "🩺", "green", [
        ("text", "green", "🩺", "medbay", MOD_UP + SUPPORT, ADMIN_UP + SUPPORT,
         "Support and community care team.", None),
        ("text", "lime", "🧪", "medbay scan", MOD_UP + SUPPORT, ADMIN_UP + SUPPORT,
         "Ticket reviews and member issue tracking.", None),
    ]),
    ("Electrical", "⚡", "orange", [
        ("text", "orange", "⚡", "electrical", ADMIN_UP + DEVS, ADMIN_UP + DEVS,
         "Developer HQ: bots, code and automation.", None),
        ("text", "brown", "🔧", "engine room", ADMIN_UP + DEVS, ADMIN_UP + DEVS,
         "Bot configs, deployments and bug reports.", None),
        ("text", "purple", "🎨", "storage design", ADMIN_UP + DESIGNERS, ADMIN_UP + DESIGNERS,
         "Designers and builders workshop.", None),
    ]),
    ("Security", "📹", "blue", [
        ("text", "blue", "📹", "security cams", MOD_UP, MOD_UP,
         "Moderation action logs.", None),
        ("text", "red", "🚨", "emergency reports", MOD_UP, MOD_UP,
         "User reports to review.", None),
        ("text", "purple", "⚖️", "ejection appeals", MOD_UP, MOD_UP,
         "Review ban appeals fairly.", None),
        ("text", "black", "🗃️", "evidence storage", MOD_UP, MOD_UP,
         "Evidence for cases.", None),
        ("text", "cyan", "🎓", "navigation training", MOD_UP + RECRUIT, ADMIN_UP + RECRUIT,
         "Guides and mod training material.", None),
    ]),
    ("Admin Room", "🛰️", "purple", [
        ("text", "purple", "🛡️", "admin room", ADMIN_UP, ADMIN_UP,
         "Admin discussion.", None),
        ("text", "pink", "📑", "admin logs", ADMIN_UP, ADMIN_UP,
         "Admin action logs.", None),
        ("text", "white", "⚖️", "crew votes", ADMIN_UP, ADMIN_UP,
         "Promotions, demotions and staff votes.", None),
        ("text", "black", "🔧", "server config", ADMIN_UP, ADMIN_UP,
         "Server settings and configuration.", None),
    ]),
    ("Event Deck", "🎪", "pink", [
        ("text", "pink", "🎪", "event deck", ADMIN_UP + EVENTS + ["mod"], ADMIN_UP + EVENTS,
         "Plan and run server events.", None),
        ("text", "yellow", "📣", "recruitment bay", ADMIN_UP + RECRUIT, ADMIN_UP + RECRUIT,
         "Recruit and train new crewmates.", None),
        ("text", "green", "🤝", "community hub", ADMIN_UP + SUPPORT, ADMIN_UP + SUPPORT,
         "Community managers and helpers.", None),
        ("text", "orange", "📝", "content lab", ADMIN_UP + MEDIA, ADMIN_UP + MEDIA,
         "Content, partnerships, PR and socials.", None),
    ]),
    ("Reactor", "☢️", "red", [
        ("text", "red", "👑", "reactor core", OWNER, OWNER,
         "Owners only.", None),
        ("text", "black", "🗝️", "owner logs", OWNER, OWNER,
         "Top-level logs.", None),
        ("text", "blue", "🧭", "navigation planning", OWNER, OWNER,
         "Long-term roadmap and strategy.", None),
        ("text", "black", "🥷", "impostor vent", OWNER, OWNER,
         "Shhh... secret owner chat.", None),
    ]),
    ("Voice Deck", "🎙️", "lime", [
        ("voice", "red", "🚨", "Emergency Meeting", ALL, ALL, None, None),
        ("voice", "yellow", "🍽️", "Cafeteria Chat", ALL, ALL, None, None),
        ("voice", "blue", "📹", "Security Office", MOD_UP, MOD_UP, None, None),
        ("voice", "purple", "🛰️", "Admin Room VC", ADMIN_UP, ADMIN_UP, None, None),
        ("voice", "orange", "⚡", "Electrical VC", ADMIN_UP + DEVS, ADMIN_UP + DEVS, None, None),
        ("voice", "red", "☢️", "Reactor VC", OWNER, OWNER, None, None),
    ]),
]


def text_channel_name(color, emoji, name):
    return f"{CREW[color][1]}{emoji}┃{rounded(name.replace(' ', '-'))}"


def voice_channel_name(color, emoji, name):
    return f"{CREW[color][1]} {emoji} {rounded(name)}"


def category_name(emoji, label):
    return f"━━ {emoji} {rounded(label.upper())} ━━"


CHANNEL_NAMES = {}       # key -> final channel name (rules, directory)
for _label, _emoji, _col, _chs in LAYOUT:
    for _c in _chs:
        if _c[7]:
            CHANNEL_NAMES[_c[7]] = text_channel_name(_c[1], _c[2], _c[3])

STAFF_RULES = [
    "**1. Respect every crewmate.** Staff set the example. No abuse of power, ever.",
    "**2. Stay professional.** Keep disputes in staff channels, not in public chat.",
    "**3. Log your actions.** Every warn/mute/kick/ban goes in security-cams with a reason.",
    "**4. Evidence first.** Collect proof before punishing. Appeals are reviewed fairly.",
    "**5. Nothing leaves the ship.** Never leak staff chats, evidence or decisions.",
    "**6. Follow the chain of command.** Escalate to the next rank up when unsure.",
    "**7. Stay active.** Tell the Staff Director before long absences.",
    "**8. No sus behavior.** Sabotaging the server = instant ejection. 🚀",
]


def resolve_roles(guild, tokens):
    """Tier keys -> badge roles, plain names -> that exact staff role."""
    roles = []
    for t in tokens:
        if t in BADGE_NAMES:
            r = badge_role(guild, t)
        else:
            specs = [s for s in STAFF_SPECS if s["plain"].lower() == t.lower()]
            r = get_role(guild, specs[0]) if specs else None
        if r and r not in roles:
            roles.append(r)
    return roles


def build_overwrites(guild, can_see, can_write, voice=False):
    writers = resolve_roles(guild, can_write)
    viewers = resolve_roles(guild, can_see)
    for r in writers:
        if r not in viewers:
            viewers.append(r)
    ov = {guild.default_role: discord.PermissionOverwrite(view_channel=False)}
    for r in viewers:
        w = r in writers
        if voice:
            ov[r] = discord.PermissionOverwrite(view_channel=True, connect=True, speak=w, stream=w)
        else:
            ov[r] = discord.PermissionOverwrite(
                view_channel=True, read_message_history=True, add_reactions=True,
                send_messages=w, attach_files=w, embed_links=w)
    ov[guild.me] = discord.PermissionOverwrite(
        view_channel=True, send_messages=True, manage_channels=True, connect=True, speak=True)
    return ov


def mentions(roles):
    text = " ".join(r.mention for r in roles) or "—"
    return text if len(text) <= 1024 else text[:1020] + "..."


async def ensure_category(guild, name, overwrites):
    cat = discord.utils.get(guild.categories, name=name)
    if cat:
        return cat
    cat = await guild.create_category(name, overwrites=overwrites)
    await asyncio.sleep(0.8)
    return cat


async def ensure_channel(guild, kind, name, category, overwrites,
                         topic=None, slowmode=0, user_limit=0):
    """Create a text/voice channel unless it exists. Returns (channel, created)."""
    ch = discord.utils.get(guild.channels, name=name)
    if ch:
        return ch, False
    if kind == "voice":
        ch = await guild.create_voice_channel(
            name, category=category, overwrites=overwrites, user_limit=user_limit)
    else:
        ch = await guild.create_text_channel(
            name, category=category, overwrites=overwrites, topic=topic, slowmode_delay=slowmode)
    await asyncio.sleep(0.8)
    return ch, True


@bot.command(name="makechannels")
@commands.guild_only()
@guild_owner_only()
async def makechannels(ctx):
    """Build the Among Us themed STAFF channels with per-role permissions."""
    guild = ctx.guild
    if not all(badge_role(guild, k) for k in TIER_ORDER):
        return await ctx.send("❌ Run `!makeroles` first (the roles are needed for permissions).")

    status = await ctx.send("🚀 Building the ship...")
    made = 0
    for cat_label, cat_emoji, cat_color, channels in LAYOUT:
        union = []
        for c in channels:
            for t in c[4] + c[5]:
                if t not in union:
                    union.append(t)
        cat_ov = {guild.default_role: discord.PermissionOverwrite(view_channel=False),
                  guild.me: discord.PermissionOverwrite(view_channel=True, manage_channels=True)}
        for r in resolve_roles(guild, union):
            cat_ov[r] = discord.PermissionOverwrite(view_channel=True)
        category = await ensure_category(guild, category_name(cat_emoji, cat_label), cat_ov)

        for kind, color, emoji, name, see, write, topic, key in channels:
            full = (text_channel_name(color, emoji, name) if kind == "text"
                    else voice_channel_name(color, emoji, name))
            ov = build_overwrites(guild, see, write, voice=(kind == "voice"))
            ch, created = await ensure_channel(guild, kind, full, category, ov, topic=topic)
            if not created:
                continue
            made += 1
            if kind == "text":
                embed = discord.Embed(
                    title=f"{emoji} {rounded(name.title())}", description=topic, color=CREW[color][0])
                viewers = resolve_roles(guild, see + [t for t in write if t not in see])
                embed.add_field(name="👀 Can see", value=mentions(viewers), inline=False)
                embed.add_field(name="✍️ Can write", value=mentions(resolve_roles(guild, write)), inline=False)
                embed.set_footer(text="Permissions are set per role for this channel.")
                try:
                    msg = await ch.send(embed=embed)
                    await msg.pin()
                except discord.HTTPException:
                    pass

    rules_ch = discord.utils.get(guild.text_channels, name=CHANNEL_NAMES["rules"])
    if rules_ch:
        await rules_ch.send(embed=discord.Embed(
            title="🚀 " + rounded("Crewmate Rules"), description="\n\n".join(STAFF_RULES),
            color=CREW["red"][0]))
    dir_ch = discord.utils.get(guild.text_channels, name=CHANNEL_NAMES["directory"])
    if dir_ch:
        for e in build_directory_pages(guild):
            await dir_ch.send(embed=e)

    await status.edit(content=f"✅ Ship built! Created **{made}** staff channels with per-role permissions. "
                              f"Use `!access #channel` to inspect any of them.")


@bot.command(name="deletechannels")
@commands.guild_only()
@guild_owner_only()
async def deletechannels(ctx, confirm: str = ""):
    """Delete every generated STAFF channel + category. Usage: !deletechannels confirm"""
    if confirm.lower() != "confirm":
        return await ctx.send("⚠️ This deletes all generated staff channels. Run `!deletechannels confirm`.")
    count = 0
    for cat_label, cat_emoji, _c, channels in LAYOUT:
        for kind, color, emoji, name, *_ in channels:
            full = (text_channel_name(color, emoji, name) if kind == "text"
                    else voice_channel_name(color, emoji, name))
            ch = discord.utils.get(ctx.guild.channels, name=full)
            if ch:
                try:
                    await ch.delete()
                    count += 1
                except discord.HTTPException:
                    pass
                await asyncio.sleep(0.6)
        cat = discord.utils.get(ctx.guild.categories, name=category_name(cat_emoji, cat_label))
        if cat:
            try:
                await cat.delete()
            except discord.HTTPException:
                pass
            await asyncio.sleep(0.6)
    try:
        await ctx.send(f"🗑️ Deleted **{count}** channels.")
    except discord.HTTPException:
        pass


@bot.command(name="access")
@commands.guild_only()
async def access(ctx, channel: discord.abc.GuildChannel = None):
    """!access #channel - see which roles can view/write there."""
    channel = channel or ctx.channel
    lines = []
    for target, ow in channel.overwrites.items():
        if not isinstance(target, discord.Role) or target == ctx.guild.default_role:
            continue
        if ow.view_channel:
            can_write = ow.send_messages if not isinstance(channel, discord.VoiceChannel) else ow.speak
            lines.append(f"{target.mention} — 👀{' ✍️' if can_write else ''}")
    text = "\n".join(lines) or "*No role-specific overwrites (inherits server defaults).*"
    if len(text) > 4000:
        text = text[:3990] + "\n..."
    await ctx.send(embed=discord.Embed(
        title=f"🔐 Access: {channel.name}", description=text, color=CREW["cyan"][0]))


# ═════════════════════════ GAME HUBS ══════════════════════════════
# squad = voice user limit (0 = unlimited). dot = color dot used in channel names.
GAMES = [
    dict(key="valorant",     name="Valorant",          emoji="🔫", color=0xFD4556, dot="red",    squad=5),
    dict(key="freefire",     name="Free Fire",         emoji="🔥", color=0xFF8C00, dot="orange", squad=4),
    dict(key="amongus",      name="Among Us",          emoji="🚀", color=0xC51111, dot="red",    squad=10),
    dict(key="minecraft",    name="Minecraft",         emoji="⛏️", color=0x5DB43F, dot="lime",   squad=0),
    dict(key="fortnite",     name="Fortnite",          emoji="🪂", color=0x9D4DFF, dot="purple", squad=4),
    dict(key="pubgm",        name="PUBG Mobile",       emoji="🍳", color=0xF2A900, dot="yellow", squad=4),
    dict(key="cod",          name="Call of Duty",      emoji="🎖️", color=0x4F6F3A, dot="black",  squad=4),
    dict(key="cs2",          name="CS2",               emoji="💣", color=0xDE9B35, dot="orange", squad=5),
    dict(key="lol",          name="League of Legends", emoji="⚔️", color=0xC89B3C, dot="yellow", squad=5),
    dict(key="roblox",       name="Roblox",            emoji="🧱", color=0xE2231A, dot="red",    squad=0),
    dict(key="gta",          name="GTA V",             emoji="🚗", color=0x3DA35D, dot="green",  squad=0),
    dict(key="apex",         name="Apex Legends",      emoji="🦊", color=0xDA292A, dot="red",    squad=3),
    dict(key="genshin",      name="Genshin Impact",    emoji="🌸", color=0x5AC8FA, dot="cyan",   squad=4),
    dict(key="brawlstars",   name="Brawl Stars",       emoji="💥", color=0xFFC400, dot="yellow", squad=3),
    dict(key="coc",          name="Clash of Clans",    emoji="🏰", color=0xF7931E, dot="orange", squad=0),
    dict(key="clashroyale",  name="Clash Royale",      emoji="👑", color=0x3D7BF7, dot="blue",   squad=0),
    dict(key="rocketleague", name="Rocket League",     emoji="🚙", color=0x0089FF, dot="blue",   squad=3),
    dict(key="eafc",         name="EA FC",             emoji="⚽", color=0x00C853, dot="green",  squad=0),
    dict(key="overwatch",    name="Overwatch 2",       emoji="🛡️", color=0xF99E1A, dot="orange", squad=5),
    dict(key="mlbb",         name="Mobile Legends",    emoji="🗡️", color=0x2E6FF2, dot="blue",   squad=5),
    dict(key="dota2",        name="Dota 2",            emoji="🩸", color=0xA22E1D, dot="red",    squad=5),
    dict(key="r6",           name="Rainbow Six Siege", emoji="🎯", color=0x00A3E0, dot="cyan",   squad=5),
    dict(key="fallguys",     name="Fall Guys",         emoji="🫘", color=0xFF5CA8, dot="pink",   squad=4),
    dict(key="stumbleguys",  name="Stumble Guys",      emoji="🏃", color=0xFF7A00, dot="orange", squad=0),
    dict(key="pokemon",      name="Pokemon",           emoji="🎴", color=0xFFCB05, dot="yellow", squad=0),
    dict(key="terraria",     name="Terraria",          emoji="🌳", color=0x4CAF50, dot="green",  squad=0),
    dict(key="hsr",          name="Honkai Star Rail",  emoji="🚂", color=0x7B68EE, dot="purple", squad=4),
    dict(key="fighting",     name="Fighting Games",    emoji="🥊", color=0xE53935, dot="red",    squad=0),
    dict(key="phasmo",       name="Phasmophobia",      emoji="👻", color=0x9575CD, dot="purple", squad=4),
    dict(key="sot",          name="Sea of Thieves",    emoji="⚓", color=0x00BCD4, dot="cyan",   squad=4),
    dict(key="chess",        name="Chess",             emoji="♟️", color=0x769656, dot="green",  squad=0),
    dict(key="other",        name="Other Games",       emoji="🕹️", color=0x9AA0A6, dot="white",  squad=0),
]

# Public hub: (kind, color, emoji, name, mode, writer_tokens, topic)
#   mode "open" = everyone can chat, "readonly" = only writer_tokens (+ mods) can write
HUB = ("Game Hub", "🎮", "yellow", [
    ("text", "yellow", "📜", "choose your games", "readonly", OWNER,
     "Pick your games from the dropdown to unlock their channels."),
    ("text", "red", "📢", "game announcements", "readonly", ADMIN_UP + EVENTS + MEDIA,
     "Game news and server gaming announcements."),
    ("text", "orange", "🏆", "tournaments", "readonly", ADMIN_UP + EVENTS,
     "Tournaments, brackets and prizes."),
    ("text", "lime", "🎮", "gaming lounge", "open", [],
     "General gaming chat for everyone."),
    ("text", "cyan", "🔎", "find teammates", "open", [],
     "Looking for a team in any game? Ask here."),
    ("voice", "yellow", "🎧", "Gaming Lounge 1", "open", [], None),
    ("voice", "cyan", "🎧", "Gaming Lounge 2", "open", [], None),
])
HUB_CHOOSE = text_channel_name("yellow", "📜", "choose your games")


def game_role_name(g):
    return f"{g['emoji']} {rounded(g['name'])}"


def game_role(guild, g):
    return find_role(guild, game_role_name(g))


def pick_games(query):
    out = []
    for part in query.split(","):
        q = part.strip().lower()
        if not q:
            continue
        for g in GAMES:
            if q == g["key"] or q in g["name"].lower() or q in g["key"]:
                if g not in out:
                    out.append(g)
    return out


def game_overwrites(guild, g, kind):
    """Per-role permissions for one game channel. kind: chat|lfg|clips|news|voice"""
    role = game_role(guild, g)
    public = GAME_ACCESS == "public"
    ov = {}
    if kind == "voice":
        ov[guild.default_role] = discord.PermissionOverwrite(view_channel=public, connect=public, speak=public)
        if role:
            ov[role] = discord.PermissionOverwrite(view_channel=True, connect=True, speak=True, stream=True)
        for r in resolve_roles(guild, MOD_UP):
            ov[r] = discord.PermissionOverwrite(
                view_channel=True, connect=True, speak=True,
                mute_members=True, deafen_members=True, move_members=True)
    elif kind == "news":
        read = dict(read_message_history=True, add_reactions=True, send_messages=False)
        ov[guild.default_role] = discord.PermissionOverwrite(view_channel=public, **read)
        if role:
            ov[role] = discord.PermissionOverwrite(view_channel=True, **read)
        for r in resolve_roles(guild, ADMIN_UP + EVENTS + MEDIA):
            ov[r] = discord.PermissionOverwrite(
                view_channel=True, send_messages=True, embed_links=True, attach_files=True)
        for r in resolve_roles(guild, MOD_UP):
            ov[r] = discord.PermissionOverwrite(
                view_channel=True, send_messages=True, manage_messages=True,
                embed_links=True, attach_files=True)
    else:
        ov[guild.default_role] = discord.PermissionOverwrite(
            view_channel=public, send_messages=public, read_message_history=public, add_reactions=public)
        if role:
            ov[role] = discord.PermissionOverwrite(
                view_channel=True, send_messages=True, read_message_history=True,
                add_reactions=True, attach_files=True, embed_links=True)
        for r in resolve_roles(guild, MOD_UP):
            ov[r] = discord.PermissionOverwrite(
                view_channel=True, send_messages=True, manage_messages=True,
                read_message_history=True, embed_links=True, attach_files=True)
    ov[guild.me] = discord.PermissionOverwrite(
        view_channel=True, send_messages=True, manage_channels=True, connect=True, speak=True)
    return ov


def hub_overwrites(guild, mode, writers, voice=False):
    ov = {}
    if voice:
        ov[guild.default_role] = discord.PermissionOverwrite(view_channel=True, connect=True, speak=True)
        for r in resolve_roles(guild, MOD_UP):
            ov[r] = discord.PermissionOverwrite(
                view_channel=True, connect=True, speak=True,
                mute_members=True, deafen_members=True, move_members=True)
    elif mode == "open":
        ov[guild.default_role] = discord.PermissionOverwrite(
            view_channel=True, send_messages=True, read_message_history=True,
            add_reactions=True, attach_files=True, embed_links=True)
        for r in resolve_roles(guild, MOD_UP):
            ov[r] = discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_messages=True)
    else:
        ov[guild.default_role] = discord.PermissionOverwrite(
            view_channel=True, send_messages=False, read_message_history=True, add_reactions=True)
        for r in resolve_roles(guild, writers):
            ov[r] = discord.PermissionOverwrite(
                view_channel=True, send_messages=True, embed_links=True, attach_files=True)
        for r in resolve_roles(guild, MOD_UP):
            ov[r] = discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_messages=True)
    ov[guild.me] = discord.PermissionOverwrite(
        view_channel=True, send_messages=True, manage_channels=True, connect=True, speak=True)
    return ov


# ───────────── Game picker dropdown (persistent) ─────────────
class GameSelect(discord.ui.Select):
    def __init__(self, chunk_idx, games):
        options = [discord.SelectOption(label=g["name"], value=g["key"], emoji=g["emoji"]) for g in games]
        super().__init__(
            custom_id=f"gamepanel:{chunk_idx}",
            placeholder=f"🎮 Pick your games (set {chunk_idx + 1})",
            min_values=0, max_values=len(options), options=options)
        self.games = games

    async def callback(self, interaction: discord.Interaction):
        chosen = set(self.values)
        member, guild = interaction.user, interaction.guild
        add, remove = [], []
        for g in self.games:
            role = game_role(guild, g)
            if not role:
                continue
            if g["key"] in chosen and role not in member.roles:
                add.append(role)
            elif g["key"] not in chosen and role in member.roles:
                remove.append(role)
        if add:
            await member.add_roles(*add, reason="Game panel")
        if remove:
            await member.remove_roles(*remove, reason="Game panel")
        await interaction.response.send_message(
            f"✅ Updated your games! (+{len(add)} / -{len(remove)})", ephemeral=True)


class GamePanel(discord.ui.View):
    def __init__(self, chunk_idx, games):
        super().__init__(timeout=None)
        self.add_item(GameSelect(chunk_idx, games))


async def refresh_panels(channel):
    """Delete old panels and post fresh ones listing every existing game role."""
    guild = channel.guild
    async for m in channel.history(limit=50):
        if m.author.id == bot.user.id and m.components:
            try:
                await m.delete()
            except discord.HTTPException:
                pass
    posted = 0
    for idx, chunk in enumerate(chunked(GAMES, 25)):
        games = [g for g in chunk if game_role(guild, g)]
        if not games:
            continue
        desc = "\n".join(f"{g['emoji']} **{g['name']}** — {game_role(guild, g).mention}" for g in games)
        embed = discord.Embed(
            title="🎮 " + rounded("Choose Your Games"),
            description="Select the games you play to unlock their channels.\n"
                        "Deselect a game to leave it.\n\n" + desc,
            color=CREW["yellow"][0])
        await channel.send(embed=embed, view=GamePanel(idx, games))
        posted += 1
    return posted


@bot.command(name="games")
@commands.guild_only()
async def games_cmd(ctx):
    """List all game hubs you can build."""
    lines = [f"{g['emoji']} **{g['name']}** — `{g['key']}`" for g in GAMES]
    pages = chunked(lines, 20)
    for i, p in enumerate(pages):
        await ctx.send(embed=discord.Embed(
            title="🎮 " + rounded("Game Hubs") + f" ({i + 1}/{len(pages)})",
            description="\n".join(p), color=CREW["purple"][0]))
    await ctx.send("Build them with `!makegames all` or `!makegames valorant, free fire, minecraft`.")


@bot.command(name="makegames")
@commands.guild_only()
@guild_owner_only()
async def makegames(ctx, *, selection: str = ""):
    """!makegames all  |  !makegames valorant, free fire, minecraft"""
    guild = ctx.guild
    if not selection.strip():
        return await ctx.send(
            "🎮 Usage: `!makegames all` or `!makegames valorant, free fire, minecraft`\n"
            "See every option with `!games`.")
    if not all(badge_role(guild, k) for k in TIER_ORDER):
        return await ctx.send("❌ Run `!makeroles` first (staff roles are needed for permissions).")

    chosen = GAMES if selection.strip().lower() == "all" else pick_games(selection)
    if not chosen:
        return await ctx.send("❌ No matching games. See `!games`.")

    need_channels = len(chosen) * 7 + 8
    if len(guild.channels) + need_channels > 500:
        return await ctx.send(f"❌ This needs ~{need_channels} channels but the server limit is 500 "
                              f"(you have {len(guild.channels)}). Pick fewer games.")
    if len(guild.roles) + len(chosen) > 250:
        return await ctx.send("❌ That would exceed Discord's 250-role limit.")

    status = await ctx.send(f"🎮 Building **{len(chosen)}** game hubs... this takes a few minutes.")

    # 1) game roles (skipped if they already exist)
    for g in chosen:
        if not game_role(guild, g):
            await guild.create_role(
                name=game_role_name(g), colour=discord.Colour(g["color"]),
                permissions=discord.Permissions.none(), hoist=False, mentionable=True,
                reason=f"!makegames by {ctx.author}")
            await asyncio.sleep(1.0)

    # 2) public hub
    hub_label, hub_emoji, _hc, hub_channels = HUB
    hub_cat_ov = {guild.default_role: discord.PermissionOverwrite(view_channel=True),
                  guild.me: discord.PermissionOverwrite(view_channel=True, manage_channels=True)}
    hub_cat = await ensure_category(guild, category_name(hub_emoji, hub_label), hub_cat_ov)
    for kind, color, emoji, name, mode, writers, topic in hub_channels:
        full = (text_channel_name(color, emoji, name) if kind == "text"
                else voice_channel_name(color, emoji, name))
        await ensure_channel(guild, kind, full, hub_cat,
                             hub_overwrites(guild, mode, writers, voice=(kind == "voice")), topic=topic)

    # 3) one category per game
    made = 0
    for n, g in enumerate(chosen, 1):
        role = game_role(guild, g)
        gname, dot = g["name"], g["dot"]
        cat_ov = {guild.default_role: discord.PermissionOverwrite(view_channel=(GAME_ACCESS == "public")),
                  guild.me: discord.PermissionOverwrite(view_channel=True, manage_channels=True)}
        if role:
            cat_ov[role] = discord.PermissionOverwrite(view_channel=True)
        for r in resolve_roles(guild, MOD_UP):
            cat_ov[r] = discord.PermissionOverwrite(view_channel=True)
        category = await ensure_category(guild, category_name(g["emoji"], gname), cat_ov)

        specs = [
            ("chat", "💬", f"{gname} chat", f"Talk about {gname} with other players.", 0),
            ("lfg", "🎯", f"{gname} lfg", f"Looking for a squad? Ping {gname} players here.", 30),
            ("clips", "🎬", f"{gname} clips", f"Share your best {gname} clips and screenshots.", 5),
            ("news", "📰", f"{gname} news", f"{gname} updates, patch notes and events.", 0),
        ]
        created_text = {}
        for kind, emoji, name, topic, slow in specs:
            full = text_channel_name(dot, emoji, name)
            ch, created = await ensure_channel(
                guild, "text", full, category, game_overwrites(guild, g, kind), topic=topic, slowmode=slow)
            created_text[kind] = ch
            made += created
        for i in (1, 2):
            full = voice_channel_name(dot, g["emoji"], f"{gname} Squad {i}")
            _, created = await ensure_channel(
                guild, "voice", full, category, game_overwrites(guild, g, "voice"), user_limit=g["squad"])
            made += created

        # welcome embed in the chat channel (only the first time)
        chat = created_text["chat"]
        try:
            pins = await chat.pins()
        except discord.HTTPException:
            pins = []
        if not any(m.author.id == bot.user.id for m in pins):
            embed = discord.Embed(
                title=f"{g['emoji']} {rounded(gname)}",
                description=f"Welcome to the **{gname}** hub! {role.mention if role else ''}",
                color=g["color"])
            embed.add_field(name="📋 Channels", value=(
                f"{created_text['chat'].mention} — chat\n"
                f"{created_text['lfg'].mention} — find a squad\n"
                f"{created_text['clips'].mention} — clips\n"
                f"{created_text['news'].mention} — news (read-only)"), inline=False)
            embed.add_field(name="🔊 Voice", value="Squad 1 & Squad 2" +
                            (f" (max {g['squad']} players)" if g["squad"] else ""), inline=False)
            embed.add_field(
                name="🔐 Access",
                value=("Visible to everyone." if GAME_ACCESS == "public"
                       else f"Pick the {gname} role in the choose-your-games channel."), inline=False)
            embed.set_footer(text="Mods and staff can manage every game channel.")
            try:
                msg = await chat.send(embed=embed)
                await msg.pin()
            except discord.HTTPException:
                pass

        if n % 3 == 0 or n == len(chosen):
            await status.edit(content=f"🎮 Progress: **{n}/{len(chosen)}** game hubs built...")

    # 4) refresh the dropdown panel(s) in the hub
    choose = discord.utils.get(guild.text_channels, name=HUB_CHOOSE)
    panels = await refresh_panels(choose) if choose else 0
    await status.edit(content=(
        f"✅ Built **{len(chosen)}** game hubs ({made} new channels).\n"
        f"📜 Posted {panels} game-picker panel(s) in {choose.mention if choose else 'the hub'}.\n"
        f"🔐 Access mode: `{GAME_ACCESS}`."))


@bot.command(name="gamepanel")
@commands.guild_only()
@commands.has_permissions(manage_roles=True)
async def gamepanel(ctx):
    """Re-post the game picker dropdowns in this channel."""
    n = await refresh_panels(ctx.channel)
    if not n:
        await ctx.send("❌ No game roles exist yet. Run `!makegames` first.")


@bot.command(name="deletegames")
@commands.guild_only()
@guild_owner_only()
async def deletegames(ctx, confirm: str = ""):
    """Delete ALL game hubs, game roles and the hub. Usage: !deletegames confirm"""
    guild = ctx.guild
    if confirm.lower() != "confirm":
        return await ctx.send("⚠️ This deletes every game hub, game role and the Game Hub category. "
                              "Run `!deletegames confirm`.")
    status = await ctx.send("🗑️ Deleting game hubs...")

    async def kill(obj):
        if obj:
            try:
                await obj.delete()
            except discord.HTTPException:
                pass
            await asyncio.sleep(0.6)

    for g in GAMES:
        gname, dot = g["name"], g["dot"]
        for emoji, name in (("💬", f"{gname} chat"), ("🎯", f"{gname} lfg"),
                            ("🎬", f"{gname} clips"), ("📰", f"{gname} news")):
            await kill(discord.utils.get(guild.channels, name=text_channel_name(dot, emoji, name)))
        for i in (1, 2):
            await kill(discord.utils.get(guild.channels, name=voice_channel_name(dot, g["emoji"], f"{gname} Squad {i}")))
        await kill(discord.utils.get(guild.categories, name=category_name(g["emoji"], gname)))
        await kill(game_role(guild, g))

    hub_label, hub_emoji, _hc, hub_channels = HUB
    for kind, color, emoji, name, *_ in hub_channels:
        full = (text_channel_name(color, emoji, name) if kind == "text"
                else voice_channel_name(color, emoji, name))
        await kill(discord.utils.get(guild.channels, name=full))
    await kill(discord.utils.get(guild.categories, name=category_name(hub_emoji, hub_label)))
    await status.edit(content="🗑️ All game hubs deleted.")


# ──────────────────────── UTILITY / MOD COMMANDS ──────────────────
@bot.command(name="purge", aliases=["clear"])
@commands.guild_only()
@commands.has_permissions(manage_messages=True)
async def purge(ctx, amount: int):
    """!purge 50 - delete recent messages (1-500)."""
    amount = max(1, min(amount, 500))
    deleted = await ctx.channel.purge(limit=amount + 1)
    await ctx.send(f"🧹 Deleted {len(deleted) - 1} messages.", delete_after=4)


@bot.command(name="slowmode")
@commands.guild_only()
@commands.has_permissions(manage_channels=True)
async def slowmode(ctx, seconds: int = 0):
    """!slowmode 10 - set slowmode (0 to disable)."""
    seconds = max(0, min(seconds, 21600))
    await ctx.channel.edit(slowmode_delay=seconds)
    await ctx.send(f"🐌 Slowmode set to **{seconds}s**." if seconds else "🐇 Slowmode disabled.")


@bot.command(name="lockdown")
@commands.guild_only()
@commands.has_permissions(manage_channels=True)
async def lockdown(ctx):
    """Emergency meeting! Stop @everyone from sending in every public text channel."""
    count = 0
    for ch in ctx.guild.text_channels:
        ov = ch.overwrites_for(ctx.guild.default_role)
        if ch.permissions_for(ctx.guild.default_role).view_channel and ov.send_messages is not False:
            ov.send_messages = False
            await ch.set_permissions(ctx.guild.default_role, overwrite=ov, reason="Lockdown")
            count += 1
            await asyncio.sleep(0.4)
    await ctx.send(f"🚨 Emergency meeting! Locked **{count}** channels. Use `!unlock` to reverse.")


@bot.command(name="unlock")
@commands.guild_only()
@commands.has_permissions(manage_channels=True)
async def unlock(ctx):
    """Undo !lockdown."""
    count = 0
    for ch in ctx.guild.text_channels:
        ov = ch.overwrites_for(ctx.guild.default_role)
        if ov.send_messages is False and ch.permissions_for(ctx.guild.default_role).view_channel:
            ov.send_messages = None
            await ch.set_permissions(ctx.guild.default_role, overwrite=ov, reason="Unlock")
            count += 1
            await asyncio.sleep(0.4)
    await ctx.send(f"✅ Meeting over. Unlocked **{count}** channels.")


@bot.command(name="announce")
@commands.guild_only()
@commands.has_permissions(manage_messages=True)
async def announce(ctx, channel: discord.TextChannel, *, text: str):
    """!announce #channel Your message here"""
    embed = discord.Embed(title="📢 " + rounded("Announcement"), description=text, color=CREW["red"][0])
    embed.set_footer(text=f"Posted by {ctx.author.display_name}", icon_url=ctx.author.display_avatar.url)
    await channel.send(embed=embed)
    await ctx.message.add_reaction("✅")


@bot.command(name="font")
async def font_cmd(ctx, *, text: str):
    """!font hello - rounded Fredoka-style text."""
    await ctx.send(rounded(text))


@bot.command(name="script")
async def script_cmd(ctx, *, text: str):
    """!script hello - calligraphy text."""
    await ctx.send(fancy(text))


@bot.command(name="serverinfo")
@commands.guild_only()
async def serverinfo(ctx):
    g = ctx.guild
    e = discord.Embed(title=f"🏰 {g.name}", color=CREW["blue"][0])
    e.add_field(name="👑 Owner", value=g.owner.mention if g.owner else "?")
    e.add_field(name="👥 Members", value=g.member_count)
    e.add_field(name="🎭 Roles", value=len(g.roles))
    e.add_field(name="💬 Text", value=len(g.text_channels))
    e.add_field(name="🔊 Voice", value=len(g.voice_channels))
    e.add_field(name="📅 Created", value=discord.utils.format_dt(g.created_at, "D"))
    if g.icon:
        e.set_thumbnail(url=g.icon.url)
    await ctx.send(embed=e)


@bot.command(name="staffhelp", aliases=["help"])
async def staffhelp(ctx):
    e = discord.Embed(title="🧰 " + rounded("Staff Architect Commands"), color=CREW["purple"][0])
    e.add_field(name="👑 Owner only", value=(
        "`!makeroles` – create/update staff roles (never duplicates)\n"
        "`!cleanroles [confirm]` – remove duplicate/leftover roles\n"
        "`!makechannels` – build the Among Us staff ship + permissions\n"
        "`!makegames all` – build every game hub (or `!makegames valorant, free fire`)\n"
        "`!giveallroles @user` · `!removeallroles @user`\n"
        "`!sortroles` – fix hierarchy order\n"
        "`!deleteroles confirm` · `!deletechannels confirm` · `!deletegames confirm`"), inline=False)
    e.add_field(name="🛡️ Staff", value=(
        "`!giverole @user <rank>` / `!takerole @user <rank>`\n"
        "`!purge <n>` · `!slowmode <s>` · `!lockdown` · `!unlock`\n"
        "`!announce #channel <text>` · `!gamepanel`"), inline=False)
    e.add_field(name="🌐 Everyone", value=(
        "`!games` · `!staffdirectory` · `!rolelist` · `!access #channel`\n"
        "`!font <text>` · `!script <text>` · `!serverinfo`"), inline=False)
    e.add_field(name="🔧 Developer", value="`!devhelp` – DMs, announcements, scheduler (dev only)", inline=False)
    await ctx.send(embed=e)


# ───────────────────────────── EVENTS ─────────────────────────────
@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user} | {len(ROLE_SPECS)} staff roles, {len(GAMES)} game hubs ready")
    await bot.change_presence(activity=discord.Game(name=f"🎮 {PREFIX}staffhelp"))


@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        return
    if isinstance(error, commands.MissingPermissions):
        return await ctx.send("⛔ You don't have permission to do that.")
    if isinstance(error, commands.CheckFailure):
        return await ctx.send(f"⛔ {error}")
    if isinstance(error, (commands.MemberNotFound, commands.ChannelNotFound)):
        return await ctx.send("❌ Couldn't find that.")
    if isinstance(error, commands.MissingRequiredArgument):
        return await ctx.send(f"❌ Missing argument: `{error.param.name}`. Try `{PREFIX}staffhelp`.")
    if isinstance(error, commands.BadArgument):
        return await ctx.send("❌ Invalid argument.")
    if isinstance(error, commands.CommandInvokeError) and isinstance(error.original, discord.Forbidden):
        return await ctx.send("❌ I'm missing permissions. Give me Administrator and move my role to the top.")
    raise error


if __name__ == "__main__":
    if TOKEN == "YOUR_BOT_TOKEN_HERE":
        raise SystemExit("Set DISCORD_TOKEN or paste your token into TOKEN.")
    bot.run(TOKEN)
