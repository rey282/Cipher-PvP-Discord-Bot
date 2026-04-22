# queue.py
import discord
import os
import asyncio
import random
import io
import math
from typing import Optional, List, Dict

from discord.ext import commands
from discord import app_commands, Interaction
from dotenv import load_dotenv

import aiohttp
from PIL import Image, ImageDraw, ImageEnhance, ImageFont

# DB helpers
from utils.db_utils import load_elo_data
from . import shared_cache

load_dotenv()

GUILD_ID = int(os.getenv("DISCORD_GUILD_ID", "0"))
ROSTER_API = os.getenv("ROSTER_API") or "https://draft-api.cipher.uno/user"
PVP_BANNED_ROLE = "pvp banned"

# Font paths (same pattern as roster.py)
FONT_PATH = os.path.join(
    os.path.dirname(__file__),
    "fonts",
    "NotoSansSC-VariableFont_wght.ttf",
)

try:
    BADGE_FONT = ImageFont.truetype(
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 15
    )
except Exception:
    BADGE_FONT = ImageFont.load_default()


def load_title_font(size: int) -> ImageFont.FreeTypeFont:
    """Try to load HSR-like font, fallback to default if missing."""
    try:
        return ImageFont.truetype(FONT_PATH, size)
    except Exception:
        try:
            return ImageFont.truetype("DejaVuSans.ttf", size)
        except Exception:
            return ImageFont.load_default()


Member = discord.Member  # alias for readability


class MatchmakingQueue(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

        # Queue & locks
        self.queue: List[int] = []  # store user IDs (not Member objects)
        self.queue_lock = asyncio.Lock()

        # Per-user monitor (VOICE ONLY — AFK removed)
        self.voice_channel_monitor: Dict[int, asyncio.Task] = {}

        # Global monitors
        self.queue_inactivity_monitor: Optional[asyncio.Task] = None  # 45m when people are waiting
        self.single_player_monitor: Optional[asyncio.Task] = None     # 15m when exactly one is waiting

    # ─────────────────────────── helpers ───────────────────────────

    def _get_member(self, guild: discord.Guild, user_id: int) -> Optional[Member]:
        return guild.get_member(user_id)

    # Inactivity monitor (45m with people waiting)
    def _ensure_inactivity_monitor(self, channel: discord.abc.Messageable):
        if self.queue_inactivity_monitor is None:
            self.queue_inactivity_monitor = asyncio.create_task(self.check_queue_inactivity(channel))

    def _cancel_inactivity_monitor(self):
        if self.queue_inactivity_monitor:
            self.queue_inactivity_monitor.cancel()
            self.queue_inactivity_monitor = None

    # Single-player monitor (15m when exactly one is waiting)
    def _ensure_single_player_monitor(self, guild_id: int, channel: discord.abc.Messageable):
        if self.single_player_monitor is None and len(self.queue) == 1:
            self.single_player_monitor = asyncio.create_task(self.check_single_player_in_queue(guild_id, channel))

    def _cancel_single_player_monitor(self):
        if self.single_player_monitor:
            self.single_player_monitor.cancel()
            self.single_player_monitor = None

    # Bring monitors into a valid state for the current queue length (no forced resets)
    def _sync_global_monitors(self, guild_id: int, channel: discord.abc.Messageable):
        if len(self.queue) == 0:
            self._cancel_inactivity_monitor()
            self._cancel_single_player_monitor()
        elif len(self.queue) == 1:
            self._ensure_inactivity_monitor(channel)
            self._cancel_single_player_monitor()
            self._ensure_single_player_monitor(guild_id, channel)
        else:  # 2 or more
            self._ensure_inactivity_monitor(channel)
            self._cancel_single_player_monitor()

    # Force reset global monitors after a match is formed (as requested)
    def _reset_global_monitors(self, guild_id: int, channel: discord.abc.Messageable):
        self._cancel_inactivity_monitor()
        self._cancel_single_player_monitor()
        # Start fresh according to current queue size
        if len(self.queue) > 0:
            self._ensure_inactivity_monitor(channel)
            if len(self.queue) == 1:
                self._ensure_single_player_monitor(guild_id, channel)

    def _is_pvp_banned(self, member: discord.Member) -> bool:
        return any(role.name.lower() == PVP_BANNED_ROLE.lower() for role in member.roles)

    # ───────────────────────── background tasks ─────────────────────────

    async def check_queue_inactivity(self, channel: discord.abc.Messageable):
        try:
            await asyncio.sleep(45 * 60)
            async with self.queue_lock:
                if len(self.queue) > 0:
                    await channel.send(
                        "The threads of fate have not woven any new paths for 45 minutes... "
                        "As a result, the queue has been gently disbanded. May your threads intertwine again when the time is right."
                    )
                    # Clear queue and cancel all per-user voice monitors (FIX #1)
                    self.queue.clear()
                    for task in self.voice_channel_monitor.values():
                        task.cancel()
                    self.voice_channel_monitor.clear()

                    self._cancel_inactivity_monitor()
                    self._cancel_single_player_monitor()
        except asyncio.CancelledError:
            pass

    async def check_single_player_in_queue(self, guild_id: int, channel: discord.abc.Messageable):
        try:
            await asyncio.sleep(15 * 60)
            guild = self.bot.get_guild(guild_id)
            if guild is None:
                return

            async with self.queue_lock:
                if len(self.queue) == 1:
                    uid = self.queue[0]
                    member = self._get_member(guild, uid)
                    self.queue.remove(uid)
                    await channel.send(
                        f"**{member.display_name if member else 'A player'}** , alas, your thread has been gently unwoven from the queue. "
                        "You've waited with patience, but fate has not yet woven your match. Please return soon, dear one..."
                    )
                    vtask = self.voice_channel_monitor.pop(uid, None)
                    if vtask: vtask.cancel()

                    self._cancel_single_player_monitor()
                    self._sync_global_monitors(guild_id, channel)
        except asyncio.CancelledError:
            pass

    async def check_voice_channel(self, guild_id: int, user_id: int, channel: discord.abc.Messageable):
        """
        10s grace; if bot has voice_states intent and the user truly left voice, remove them.
        If voice_states intent is not enabled, skip removal to avoid false positives.
        """
        try:
            await asyncio.sleep(10)

            if not getattr(self.bot, "intents", None) or not self.bot.intents.voice_states:
                return  # safety: avoid false kicks when intent is off

            guild = self.bot.get_guild(guild_id)
            if guild is None:
                return

            async with self.queue_lock:
                if user_id in self.queue:
                    member = self._get_member(guild, user_id)
                    if member and member.voice is None:
                        self.queue.remove(user_id)
                        await channel.send(
                            f"**{member.display_name}**, your thread has been gently unwoven from the queue, "
                            "as you are no longer in the voice channel. May the threads weave once more when you return."
                        )
                        self.voice_channel_monitor.pop(user_id, None)

                        self._sync_global_monitors(guild_id, channel)
        except asyncio.CancelledError:
            pass

    async def _deny_pvp_banned(self, interaction: Interaction):
        await interaction.response.send_message(
            f"**{interaction.user.display_name} is banned from PvP matchmaking.**\n"
            "The threads of fate reject your call. You may not enter or interact with the queue.",
            ephemeral=False  # public message
        )



    async def _fetch_profile_characters(
        self,
        session: aiohttp.ClientSession,
        discord_id: str
    ) -> Optional[dict]:
        if not discord_id:
            return None

        url = f"{ROSTER_API}/{discord_id}/profile-characters"
        try:
            async with session.get(url) as resp:
                if resp.status == 404:
                    return None
                if resp.status != 200:
                    return None

                data = await resp.json()
                if isinstance(data, dict) and isinstance(data.get("profileCharacters"), list):
                    return data
                return None
        except Exception:
            return None


    def _build_team_roster_image(
        self,
        team: List[Member],
        entry1: Optional[dict],
        entry2: Optional[dict],
        team_label: str,
    ) -> Optional[io.BytesIO]:


        # must be 2 players
        if len(team) < 2:
            return None

        p1, p2 = team[0], team[1]

        if not entry1 and not entry2:
            return None

        owned1 = {c["id"]: c["eidolon"] for c in entry1.get("profileCharacters", [])} if entry1 else {}
        owned2 = {c["id"]: c["eidolon"] for c in entry2.get("profileCharacters", [])} if entry2 else {}

        has_gp1 = "9999" in owned1
        has_gp2 = "9999" in owned2

        # union of both players' owned roster
        combined_owned = set(owned1.keys()) | set(owned2.keys())

        char_map_cache = shared_cache.char_map_cache
        icon_cache = shared_cache.icon_cache
        if not char_map_cache:
            return None

        # ******** sorting *******
        def sort_key(c: dict):
            return (
                0 if c["id"] in combined_owned else 1,
                -c["rarity"],
                c["name"],
            )

        sorted_chars = sorted(char_map_cache.values(), key=sort_key)

        # ******** layout ********
        ICON = 110
        GAP = 8
        PADDING = 20
        PER_ROW = 8

        rows_count = max(1, math.ceil(len(sorted_chars) / PER_ROW))
        width = PADDING * 2 + PER_ROW * ICON + (PER_ROW - 1) * GAP

        title_text = f"{p1.display_name} • {p2.display_name}"

        title_font = load_title_font(40)
        dummy = Image.new("RGB", (1, 1))
        draw_dummy = ImageDraw.Draw(dummy)
        tb = draw_dummy.textbbox((0, 0), title_text, font=title_font)
        title_h = tb[3] - tb[1]


        TITLE_TOP = 30
        UNDERLINE_GAP = 8
        UNDERLINE_EXTRA = 24

        title_block_bottom = TITLE_TOP + title_h + UNDERLINE_GAP + 3 + UNDERLINE_EXTRA
        grid_top = title_block_bottom + PADDING
        grid_height = rows_count * ICON + (rows_count - 1) * GAP + PADDING
        height = grid_top + grid_height

        canvas = Image.new("RGBA", (width, height), (10, 10, 10, 255))
        draw = ImageDraw.Draw(canvas)

        for y in range(height):
            t = y / (height - 1)
            r = int(14 + (28 - 14) * t)
            g = int(10 + (18 - 10) * t)
            b = int(30 + (52 - 30) * t)
            draw.line([(0, y), (width, y)], fill=(r, g, b, 255))

        # ******** Title + underline ********
        title_bbox = draw.textbbox((0, 0), title_text, font=title_font)
        title_w = title_bbox[2] - title_bbox[0]
        title_x = (width - title_w) // 2
        title_y = TITLE_TOP

        draw.text(
            (title_x, title_y),
            title_text,
            font=title_font,
            fill="white",
        )

        gp_icon = shared_cache.gp_icon

        if gp_icon:
            icon_y = title_y + 5

            def draw_gp_icon(x_pos, has_gp):
                icon = gp_icon.copy()

                if not has_gp:
                    icon = ImageEnhance.Brightness(icon).enhance(0.3)
                    icon = icon.convert("LA").convert("RGBA")

                canvas.paste(icon, (x_pos, icon_y), icon)

            draw_gp_icon(title_x - 40, has_gp1)
            draw_gp_icon(title_x + title_w + 8, has_gp2)

        underline_y = title_y + title_h + UNDERLINE_GAP + 10
        margin = int(width * 0.28)
        draw.line([(margin, underline_y), (width - margin, underline_y)],
                fill=(255, 255, 255, 180), width=3)

        # ******** Icons + Eidolon Badges ********
        for idx, c in enumerate(sorted_chars):
            col = idx % PER_ROW
            row = idx // PER_ROW

            x = PADDING + col * (ICON + GAP)
            y = grid_top + row * (ICON + GAP)

            icon = icon_cache.get(c["id"])
            if not icon:
                continue
            
            if icon.size != (ICON, ICON):
                icon = icon.resize((ICON, ICON), Image.LANCZOS)

            # dim unowned
            icon = icon.copy()
            if c["id"] not in combined_owned:
                icon = ImageEnhance.Brightness(icon).enhance(0.35)
                icon = icon.convert("LA").convert("RGBA")

            # icon (already includes rarity background)
            canvas.paste(icon, (x, y), icon)

            # *****************
            # EID BADGES (same)
            # *****************
            badge_w, badge_h = 40, 26
            badge_y = y + ICON - badge_h - 4

            def draw_badge(e_value: int, bx: int):

                draw.rounded_rectangle(
                    [bx, badge_y, bx + badge_w, badge_y + badge_h],
                    radius=8,
                    fill=(0, 0, 0, 190),
                )


                text = f"E{e_value}"
                text_bbox = draw.textbbox((0, 0), text, font=BADGE_FONT)
                tw = text_bbox[2] - text_bbox[0]
                th = text_bbox[3] - text_bbox[1]

                tx = bx + (badge_w - tw) // 2
                ty = badge_y + (badge_h - th) // 2 - 3

                draw.text((tx, ty), text, font=BADGE_FONT, fill="white")

            e1 = owned1.get(c["id"])
            e2 = owned2.get(c["id"])

            if e1 is not None:
                draw_badge(e1, x + 4)
            if e2 is not None:
                draw_badge(e2, x + ICON - badge_w - 4)

        # return buffer
        buffer = io.BytesIO()
        canvas.save(buffer, "PNG")
        buffer.seek(0)
        return buffer
        
    async def _send_match_rosters(
        self,
        channel: discord.abc.Messageable,
        team1: List[Member],
        team2: List[Member],
    ):
        if not shared_cache.char_map_cache or not shared_cache.icon_cache:
            return

        timeout = aiohttp.ClientTimeout(total=20, connect=5, sock_read=15)

        async with aiohttp.ClientSession(timeout=timeout) as session:
            team_pairs = [(team1, "Team 1"), (team2, "Team 2")]

            for idx, (team, label) in enumerate(team_pairs, start=1):
                if len(team) < 2:
                    continue

                id1 = str(team[0].id)
                id2 = str(team[1].id)

                entry1 = await self._fetch_profile_characters(session, id1)
                entry2 = await self._fetch_profile_characters(session, id2)

                buf = self._build_team_roster_image(team, entry1, entry2, label)
                if buf:
                    await channel.send(file=discord.File(buf, filename=f"team{idx}_roster.png"))


    # ────────────────────── prebans builder (exact same as /prebans) ──────────────────────

    def _build_prebans_embed(self, team1: List[Member], team2: List[Member]) -> discord.Embed:
        elo_data = load_elo_data()

        def get_points(player: Member):
            return elo_data.get(str(player.id), {}).get("points", 0)

        def weighted_cost(team: List[Member]):
            if len(team) == 1:
                return get_points(team[0])
            c1, c2 = get_points(team[0]), get_points(team[1])
            low, high = sorted([c1, c2])
            return 0.65 * low + 0.35 * high

        match_type = f"{len(team1)}v{len(team2)}"

        # Match type logic
        if match_type == "1v1":
            points1 = get_points(team1[0])
            points2 = get_points(team2[0])
        elif match_type == "1v2":
            points1 = get_points(team1[0])
            points2 = weighted_cost(team2)
        elif match_type == "2v1":
            points1 = weighted_cost(team1)
            points2 = get_points(team2[0])
        else:  # 2v2
            points1 = weighted_cost(team1)
            points2 = weighted_cost(team2)

        def format_team(team: List[Member]):
            return ", ".join(p.display_name for p in team)

        point_diff = abs(points1 - points2)
        lower_points_team = team2 if points1 > points2 else team1

        if point_diff < 100:
            embed = discord.Embed(
                title=f"Pre-Bans Calculation for {match_type}",
                color=discord.Color.purple()
            )
            embed.add_field(
                name="Teams Aligned",
                value=f"{format_team(team1)} (Avg: {points1:.1f} pts)\n"
                      f"{format_team(team2)} (Avg: {points2:.1f} pts)",
                inline=False
            )
            embed.add_field(
                name="Result",
                value="It seems the threads of fate have tied these teams... No pre-bans required for either side.\n\n"
                      f"*Total point difference: {point_diff:.1f}*",
                inline=False
            )
            embed.set_footer(text="Handled with care by Kyasutorisu")
            return embed

        PREBAN_COSTS = [100, 120, 140]
        JOKER_COSTS = [170, 180, 210, 230]

        remaining_diff = point_diff

        regular_bans = 0
        joker_bans = 0

        # Apply prebans (max 3)
        for cost in PREBAN_COSTS:
            if remaining_diff >= cost and regular_bans < 3:
                remaining_diff -= cost
                regular_bans += 1
            else:
                break

        # Apply joker bans (max 4)
        for cost in JOKER_COSTS:
            if remaining_diff >= cost and joker_bans < 4:
                remaining_diff -= cost
                joker_bans += 1
            else:
                break

        embed = discord.Embed(
            title=f"Pre-Bans Calculation for {match_type}",
            color=discord.Color.purple()
        )
        embed.add_field(
            name="Teams Aligned", 
            value=(f" {format_team(team1)} (Avg: {points1:.1f} pts)\n"
                   f" {format_team(team2)} (Avg: {points2:.1f} pts)"),
            inline=False
        )

        ban_info = []

        if regular_bans > 0:
            ban_info.append(f"▸ {regular_bans} preban(s)")

        if joker_bans > 0:
            ban_info.append(f"▸ {joker_bans} joker ban(s)")

        embed.add_field(
            name=f"{format_team(lower_points_team)} receives pre-bans",
            value="\n".join(ban_info) + f"\n\n*Total point difference: {point_diff:.1f}*",
            inline=False
        )
        embed.set_footer(text="Handled with care by Kyasutorisu")
        return embed

    # ────────────────────────── slash commands ──────────────────────────

    @app_commands.command(name="joinqueue", description="Tie your thread to the matchmaking queue.")
    @app_commands.guilds(GUILD_ID)
    async def join_queue(self, interaction: Interaction):
        if interaction.guild is None:
            await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)
            return

        member = interaction.guild.get_member(interaction.user.id)

        if member and self._is_pvp_banned(member):
            await self._deny_pvp_banned(interaction)
            return

        if member is None or member.voice is None:
            await interaction.response.send_message(
                "Oops! You must be in a voice channel to join the queue. Please join a voice channel and try again.",
                ephemeral=True
            )
            return

        uid = member.id

        async with self.queue_lock:
            if uid in self.queue:
                await interaction.response.send_message("You're already woven into the queue", ephemeral=True)
                return

            self.queue.append(uid)

            # Start voice monitor ONLY (AFK removed)
            self.voice_channel_monitor[uid] = asyncio.create_task(
                self.check_voice_channel(interaction.guild.id, uid, interaction.channel)
            )

            # Bring global monitors into a valid state
            self._sync_global_monitors(interaction.guild.id, interaction.channel)

        await interaction.response.send_message(
            f"{member.display_name} has joined the queue. The threads of fate are being woven.", ephemeral=False
        )

        # ── Form as many matches as possible (drain in groups of 4) ──
        match_groups: List[List[int]] = []
        async with self.queue_lock:
            while len(self.queue) >= 4:
                ids = self.queue[:4]
                self.queue = self.queue[4:]

                # Cancel voice monitor for these 4
                for pid in ids:
                    t = self.voice_channel_monitor.pop(pid, None)
                    if t:
                        t.cancel()

                match_groups.append(ids)

            # After forming matches, reset global timers for remaining queued
            self._reset_global_monitors(interaction.guild.id, interaction.channel)

        # Announce each match outside the lock
        guild = interaction.guild
        for ids in match_groups:
            players = [self._get_member(guild, i) for i in ids]
            players = [p for p in players if p is not None]
            if len(players) < 4:
                # Someone bailed; requeue remaining and RESTART their voice monitors (FIX #2)
                async with self.queue_lock:
                    self.queue = [p.id for p in players] + self.queue

                    for p in players:
                        old = self.voice_channel_monitor.pop(p.id, None)
                        if old:
                            old.cancel()
                        self.voice_channel_monitor[p.id] = asyncio.create_task(
                            self.check_voice_channel(interaction.guild.id, p.id, interaction.channel)
                        )

                    self._reset_global_monitors(interaction.guild.id, interaction.channel)
                continue

            random.shuffle(players)
            team1, team2 = players[:2], players[2:]
            mentions = ", ".join(p.mention for p in players)

            await interaction.channel.send(
                f"**Match Found!**\n"
                f"**Players:** {mentions}\n"
                f"Fate has woven your paths together. Best of luck"
            )

            match_embed = discord.Embed(
                title="Threads Aligned",
                description="The threads have been gently woven… Here is your match.",
                color=discord.Color.blue()
            )
            match_embed.add_field(name="Team 1", value=f"{team1[0].mention} & {team1[1].mention}", inline=False)
            match_embed.add_field(name="Team 2", value=f"{team2[0].mention} & {team2[1].mention}", inline=False)
            match_embed.set_footer(text="Woven gently by Kyasutorisu")
            await interaction.channel.send(embed=match_embed)

            prebans_embed = self._build_prebans_embed(team1, team2)
            await interaction.channel.send(embed=prebans_embed)

            try:
                await self._send_match_rosters(interaction.channel, team1, team2)
            except Exception as e:

                print(f"[queue] Failed to send match rosters: {e}")

    @app_commands.command(name="leavequeue", description="Untie your thread from the queue.")
    @app_commands.guilds(GUILD_ID)
    async def leave_queue(self, interaction: Interaction):
        if interaction.guild is None:
            await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)
            return

        uid = interaction.user.id

        async with self.queue_lock:
            if uid not in self.queue:
                await interaction.response.send_message("You were never in the thread to begin with.", ephemeral=True)
                return

            self.queue.remove(uid)

            vtask = self.voice_channel_monitor.pop(uid, None)
            if vtask:
                vtask.cancel()

            self._sync_global_monitors(interaction.guild.id, interaction.channel)

        await interaction.response.send_message("Your thread has been untied from the queue.", ephemeral=False)

    @app_commands.command(name="queue", description="Peek at those waiting in the thread.")
    @app_commands.guilds(GUILD_ID)
    async def show_queue(self, interaction: Interaction):
        if interaction.guild is None:
            await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)
            return
        
        member = interaction.guild.get_member(interaction.user.id)

        if member and self._is_pvp_banned(member):
            await self._deny_pvp_banned(interaction)
            return

        async with self.queue_lock:
            if not self.queue:
                await interaction.response.send_message(
                    "It’s so quiet in here... The threads of fate are still at rest.",
                    ephemeral=False
                )
                return

            guild = interaction.guild
            lines = []
            for i, uid in enumerate(self.queue, start=1):
                m = guild.get_member(uid)
                lines.append(f"{i}. {m.display_name if m else f'User {uid}'}")

            embed = discord.Embed(
                title="🧵 Matchmaking Queue",
                description="\n".join(lines),
                color=discord.Color.purple()
            )
            embed.set_footer(text="Kyasutorisu are watching over the threads of fate...")

        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="clearqueue", description="Gently unravel all threads from the queue.")
    @app_commands.guilds(GUILD_ID)
    async def clear_queue(self, interaction: Interaction):
        required_role = "Stonehearts"

        if interaction.guild is None:
            await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)
            return

        if (not interaction.user.guild_permissions.administrator and
                not any(role.name == required_role for role in interaction.user.roles)):
            await interaction.response.send_message(
                "<:Unamurice:1349309283669377064> I-I’m really sorry, but only an administrator may pull the threads of fate this way...\n"
                "Please speak to someone with the right permissions if you'd like this command woven into being.",
                ephemeral=True
            )
            return

        async with self.queue_lock:
            self.queue.clear()
            for task in self.voice_channel_monitor.values():
                task.cancel()
            self.voice_channel_monitor.clear()
            self._cancel_inactivity_monitor()
            self._cancel_single_player_monitor()

        await interaction.response.send_message("The threads of fate have been gently unraveled. The queue is now empty.", ephemeral=False)


async def setup(bot: commands.Bot):
    await bot.add_cog(MatchmakingQueue(bot))
