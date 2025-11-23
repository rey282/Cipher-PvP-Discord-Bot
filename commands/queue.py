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
from utils.db_utils import load_elo_data, get_cursor
from . import shared_cache

load_dotenv()

GUILD_ID = int(os.getenv("DISCORD_GUILD_ID", "0"))
ROSTER_API = os.getenv("ROSTER_API") or "https://draft-api.cipher.uno/getUsers"

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


    async def _fetch_roster_users(self) -> Optional[list]:
        """
        Fetch full roster JSON (same as /roster).
        Returns list of users or None on error.
        """
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(ROSTER_API, timeout=10) as resp:
                    if resp.status != 200:
                        return None
                    try:
                        return await resp.json()
                    except Exception:
                        return None
        except Exception:
            return None

    def _build_team_roster_image(
        self,
        team: List[Member],
        roster_index: Dict[str, dict],
        team_label: str,
    ) -> Optional[io.BytesIO]:
        """
        Build a roster image for a 2-player team:
        - Same style as /roster
        - Combined ownership
        - Dual Eidolon badges (left for player1, right for player2)
        - Title like "Team 1 — P1 & P2"
        """
        if len(team) < 2:
            return None

        p1, p2 = team[0], team[1]
        id1, id2 = str(p1.id), str(p2.id)

        entry1 = roster_index.get(id1)
        entry2 = roster_index.get(id2)

        # If both have no roster, skip
        if entry1 is None and entry2 is None:
            return None

        owned1 = (
            {c["id"]: c["eidolon"] for c in entry1.get("profileCharacters", [])}
            if entry1
            else {}
        )
        owned2 = (
            {c["id"]: c["eidolon"] for c in entry2.get("profileCharacters", [])}
            if entry2
            else {}
        )

        combined_owned = set(owned1.keys()) | set(owned2.keys())

        if not shared_cache.char_map_cache:
            return None

        # 1) Sorting logic 
        def sort_key(c: dict):
            return (
                0 if c["id"] in combined_owned else 1,  
                -c["rarity"],                          
                c["name"],                             
            )

        sorted_chars = sorted(shared_cache.char_map_cache.values(), key=sort_key)

        # 2) Layout 
        ICON = 110
        GAP = 8
        PADDING = 20
        PER_ROW = 8

        rows_count = max(1, math.ceil(len(sorted_chars) / PER_ROW))
        width = PADDING * 2 + PER_ROW * ICON + (PER_ROW - 1) * GAP

        # Title text: "Team 1 — P1 & P2"
        title_text = f"{team_label} — {p1.display_name} & {p2.display_name}"

        title_font = load_title_font(40)
        dummy_img = Image.new("RGB", (1, 1))
        dummy_draw = ImageDraw.Draw(dummy_img)
        title_bbox = dummy_draw.textbbox((0, 0), title_text, font=title_font)
        title_h = title_bbox[3] - title_bbox[1]

        TITLE_TOP = 30
        UNDERLINE_GAP = 8
        UNDERLINE_EXTRA = 24

        title_block_bottom = TITLE_TOP + title_h + UNDERLINE_GAP + 3 + UNDERLINE_EXTRA
        grid_top = title_block_bottom + PADDING

        grid_height = rows_count * ICON + (rows_count - 1) * GAP + PADDING
        height = grid_top + grid_height

        # 3) Canvas + gradient
        canvas = Image.new("RGBA", (width, height), (10, 10, 10, 255))
        draw = ImageDraw.Draw(canvas)

        for y in range(height):
            t = y / max(1, height - 1)
            r = int(14 + (28 - 14) * t)
            g = int(10 + (18 - 10) * t)
            b = int(30 + (52 - 30) * t)
            draw.line([(0, y), (width, y)], fill=(r, g, b, 255))

        # 4) Title + underline (same style)
        title_bbox = draw.textbbox((0, 0), title_text, font=title_font)
        title_w = title_bbox[2] - title_bbox[0]

        title_x = (width - title_w) // 2
        title_y = TITLE_TOP

        draw.text(
            (title_x, title_y),
            title_text,
            font=title_font,
            fill=(255, 255, 255, 255),
        )

        underline_y = title_y + title_h + UNDERLINE_GAP + 10
        underline_margin = int(width * 0.28)
        draw.line(
            [(underline_margin, underline_y), (width - underline_margin, underline_y)],
            fill=(255, 255, 255, 180),
            width=3,
        )

        # 5) Character icons + dual EIDs
        for idx, c in enumerate(sorted_chars):
            col = idx % PER_ROW
            row = idx // PER_ROW

            x = PADDING + col * (ICON + GAP)
            y = grid_top + row * (ICON + GAP)

            base_icon = shared_cache.icon_cache.get(c["id"])
            if not base_icon:
                continue
            
            if base_icon.size != (ICON, ICON):
                base_icon = base_icon.resize((ICON, ICON), Image.LANCZOS)

            # use exact preprocessed icon (already: cropped, resized, rounded, rarity-bg)
            icon = base_icon.copy()

            # dim if not owned (same as roster.py)
            if c["id"] not in combined_owned:
                icon = ImageEnhance.Brightness(icon).enhance(0.35)
                icon = icon.convert("LA").convert("RGBA")

            # paste directly — background & rounded edges are already included
            canvas.paste(icon, (x, y), icon)

            # Dual Eidolon badges
            e1 = owned1.get(c["id"])
            e2 = owned2.get(c["id"])

            # -------------------------------------------------------
            # DUAL EIDOLON BADGES
            # -------------------------------------------------------

            badge_w, badge_h = 40, 26         
            badge_y = y + ICON - badge_h - 4   

            def draw_badge(e_value: int, bx: int):
                rect = [bx, badge_y, bx + badge_w, badge_y + badge_h]

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

            # Player 1 badge (left)
            if e1 is not None:
                bx1 = x + 4                   # SAME as roster
                draw_badge(e1, bx1)

            # Player 2 badge (right)
            if e2 is not None:
                bx2 = x + ICON - badge_w - 4  # SAME as roster
                draw_badge(e2, bx2)


        # 6) Buffer
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
        """
        After match + prebans, send:
        - Team 1 roster image (combined of both players)
        - Team 2 roster image
        """
        if not shared_cache.char_map_cache or not shared_cache.icon_cache:
            return


        roster_users = await self._fetch_roster_users()
        if not roster_users:
            return

        roster_index = {u.get("discordId"): u for u in roster_users}

        team_pairs = [(team1, "Team 1"), (team2, "Team 2")]

        for idx, (team, label) in enumerate(team_pairs, start=1):
            buf = self._build_team_roster_image(team, roster_index, label)
            if buf:
                await channel.send(
                    file=discord.File(buf, filename=f"team{idx}_roster.png")
                )

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

        # Thresholds identical to your command
        if point_diff >= 600:
            regular_bans = 3
            joker_bans = 2 + (point_diff - 600) // 200
        elif point_diff >= 300:
            regular_bans = 3
            joker_bans = min(5, (point_diff - 300) // 150)
        else:
            regular_bans = min(3, point_diff // 100)
            joker_bans = 0

        embed = discord.Embed(
            title=f"Pre-Bans Calculation for {match_type}",
            color=discord.Color.purple()
        )
        embed.add_field(
            name="Teams Alligned",  # keep your original spelling
            value=(f" {format_team(team1)} (Avg: {points1:.1f} pts)\n"
                   f" {format_team(team2)} (Avg: {points2:.1f} pts)"),
            inline=False
        )

        ban_info = []
        if regular_bans > 0:
            ban_info.append(f"▸ {int(regular_bans)} regular ban(s) (100pts each)")
        if joker_bans > 0:
            if point_diff >= 600:
                extra_jokers = int(joker_bans - 2)
                if extra_jokers > 0:
                    ban_info.append(
                        f"▸ 2 joker bans (150pts each) + {int(extra_jokers)} extra joker ban(s) (200pts each)"
                    )
                else:
                    ban_info.append("▸ 2 joker bans (150pts each)")
            else:
                ban_info.append(f"▸ {int(joker_bans)} joker ban(s) (150pts each)")

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
