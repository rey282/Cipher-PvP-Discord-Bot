import discord
import os
import asyncio
import random
from typing import Optional, List, Dict
from discord.ext import commands
from discord import app_commands, Interaction
from dotenv import load_dotenv

# import your elo loader (same one your /prebans uses)
from utils.db_utils import load_elo_data

load_dotenv()

GUILD_ID = int(os.getenv("DISCORD_GUILD_ID"))

Member = discord.Member  # alias for readability


class MatchmakingQueue(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

        # Store queue as user IDs (stable across lookups)
        self.queue: List[int] = []
        self.queue_lock = asyncio.Lock()

        # Per-user monitors keyed by user ID
        self.voice_channel_monitor: Dict[int, asyncio.Task] = {}
        self.afk_monitor: Dict[int, asyncio.Task] = {}

        # Global inactivity timer for when people are waiting but no matches form
        self.queue_inactivity_monitor: Optional[asyncio.Task] = None

    # ─────────────────────────── helpers ───────────────────────────

    def _get_member(self, guild: discord.Guild, user_id: int) -> Optional[Member]:
        return guild.get_member(user_id)

    def _ensure_inactivity_monitor(self, channel: discord.abc.Messageable):
        if self.queue_inactivity_monitor is None:
            self.queue_inactivity_monitor = asyncio.create_task(self.check_queue_inactivity(channel))

    def _cancel_inactivity_monitor(self):
        if self.queue_inactivity_monitor:
            self.queue_inactivity_monitor.cancel()
            self.queue_inactivity_monitor = None

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
                    self.queue.clear()
                    self._cancel_inactivity_monitor()
        except asyncio.CancelledError:
            pass

    async def check_afk(self, guild_id: int, user_id: int, channel: discord.abc.Messageable):
        afk_timeout = 15 * 60
        try:
            await asyncio.sleep(afk_timeout)
            guild = self.bot.get_guild(guild_id)
            if guild is None:
                return

            async with self.queue_lock:
                if user_id in self.queue:
                    member = self._get_member(guild, user_id)

                    # Consider AFK if not in VC AND no recent message in text
                    is_not_in_vc = (member is None) or (member.voice is None)
                    no_recent_text = True
                    if member and member.last_message:
                        diff = (discord.utils.utcnow() - member.last_message.created_at).total_seconds()
                        no_recent_text = diff > afk_timeout

                    if is_not_in_vc and no_recent_text:
                        self.queue.remove(user_id)
                        await channel.send(
                            f"**{member.display_name if member else 'A player'}** ,I’m afraid your thread has been gently unraveled from the queue. "
                            "You’ve drifted away from the voice and text realms for too long..."
                        )
                        self.afk_monitor.pop(user_id, None)
                        vtask = self.voice_channel_monitor.pop(user_id, None)
                        if vtask:
                            vtask.cancel()

                        if len(self.queue) == 0:
                            self._cancel_inactivity_monitor()
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
                    atask = self.afk_monitor.pop(uid, None)
                    if atask:
                        atask.cancel()
                    vtask = self.voice_channel_monitor.pop(uid, None)
                    if vtask:
                        vtask.cancel()

                    if len(self.queue) == 0:
                        self._cancel_inactivity_monitor()
        except asyncio.CancelledError:
            pass

    async def check_voice_channel(self, guild_id: int, user_id: int, channel: discord.abc.Messageable):
        """
        10s grace; if the bot has voice_states intent and the user truly left voice, remove them.
        If voice_states intent is not enabled, we skip removal to avoid false positives.
        """
        try:
            await asyncio.sleep(10)

            # Skip this auto-kick if bot doesn't have voice state intent (prevents "instant end" false removals)
            if not getattr(self.bot, "intents", None) or not self.bot.intents.voice_states:
                return

            guild = self.bot.get_guild(guild_id)
            if guild is None:
                return

            async with self.queue_lock:
                if user_id in self.queue:
                    member = self._get_member(guild, user_id)
                    if member is None:
                        return
                    if member.voice is None:
                        self.queue.remove(user_id)
                        await channel.send(
                            f"**{member.display_name}**, your thread has been gently unwoven from the queue, "
                            "as you are no longer in the voice channel. May the threads weave once more when you return."
                        )
                        self.afk_monitor.pop(user_id, None)
                        self.voice_channel_monitor.pop(user_id, None)

                        if len(self.queue) == 0:
                            self._cancel_inactivity_monitor()
        except asyncio.CancelledError:
            pass

    # ─────────────────────── prebans builder (exact clone) ───────────────────────

    def _build_prebans_embed(self, team1: List[Member], team2: List[Member]) -> discord.Embed:
        """
        Builds a prebans embed with the *exact same* logic/text/field names as your /prebans command.
        """
        elo_data = load_elo_data()

        # Team processing
        def get_points(player: Member):
            return elo_data.get(str(player.id), {}).get("points", 0)

        def weighted_cost(team: List[Member]):
            if len(team) == 1:
                return get_points(team[0])
            c1, c2 = get_points(team[0]), get_points(team[1])
            low, high = sorted([c1, c2])
            return 0.6 * low + 0.4 * high

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

        # Define format_team function
        def format_team(team: List[Member]):
            return ", ".join(p.display_name for p in team)

        # Determine point difference / lower team
        point_diff = abs(points1 - points2)
        lower_points_team = team2 if points1 > points2 else team1

        # If <100, exact embed
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

        # Calculate bans (identical thresholds & integer division)
        if point_diff >= 560:
            regular_bans = 3
            joker_bans = 2 + (point_diff - 560) // 200
        elif point_diff >= 300:
            regular_bans = 3
            joker_bans = min(5, (point_diff - 300) // 130)
        else:
            regular_bans = min(3, point_diff // 100)
            joker_bans = 0

        # Build embed (preserve your exact field names/text)
        embed = discord.Embed(
            title=f"Pre-Bans Calculation for {match_type}",
            color=discord.Color.purple()
        )
        embed.add_field(
            name="Teams Alligned",  # keep original spelling to match your command output
            value=(f" {format_team(team1)} (Avg: {points1:.1f} pts)\n"
                   f" {format_team(team2)} (Avg: {points2:.1f} pts)"),
            inline=False
        )

        ban_info = []
        if regular_bans > 0:
            ban_info.append(f"▸ {int(regular_bans)} regular ban(s) (100pts each)")
        if joker_bans > 0:
            if point_diff >= 560:
                extra_jokers = int(joker_bans - 2)
                if extra_jokers > 0:
                    ban_info.append(
                        f"▸ 2 joker bans (130pts each) + {int(extra_jokers)} extra joker ban(s) (200pts each)"
                    )
                else:
                    ban_info.append("▸ 2 joker bans (130pts each)")
            else:
                ban_info.append(f"▸ {int(joker_bans)} joker ban(s) (130pts each)")

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

            # Start voice and afk monitors
            self.voice_channel_monitor[uid] = asyncio.create_task(
                self.check_voice_channel(interaction.guild.id, uid, interaction.channel)
            )
            self.afk_monitor[uid] = asyncio.create_task(
                self.check_afk(interaction.guild.id, uid, interaction.channel)
            )

            if len(self.queue) == 1:
                self._ensure_inactivity_monitor(interaction.channel)
                asyncio.create_task(self.check_single_player_in_queue(interaction.guild.id, interaction.channel))

        await interaction.response.send_message(
            f"{member.display_name} has joined the queue. The threads of fate are being woven.", ephemeral=False
        )

        # Try to form a match right after someone joins
        async with self.queue_lock:
            if len(self.queue) >= 4:
                guild = interaction.guild
                ids = self.queue[:4]
                self.queue = self.queue[4:]

                # Cancel monitors for these players
                for pid in ids:
                    t = self.afk_monitor.pop(pid, None)
                    if t:
                        t.cancel()
                    t = self.voice_channel_monitor.pop(pid, None)
                    if t:
                        t.cancel()

                # If queue is now empty, cancel inactivity monitor
                if len(self.queue) == 0:
                    self._cancel_inactivity_monitor()

                players: List[Member] = [self._get_member(guild, i) for i in ids]
                players = [p for p in players if p is not None]
                if len(players) < 4:
                    # If someone left between join and now, put remaining back to the head
                    remaining_ids = [p.id for p in players]
                    self.queue = remaining_ids + self.queue
                    if len(self.queue) > 0:
                        self._ensure_inactivity_monitor(interaction.channel)
                    return

                random.shuffle(players)
                team1, team2 = players[:2], players[2:]

        # Build and send the match + prebans (outside the lock)
        mentions = ", ".join(p.mention for p in (team1 + team2))
        await interaction.channel.send(
            f"**Match Found!**\n"
            f"**Players:** {mentions}\n"
            f"Fate has woven your paths together. Best of luck"
        )

        # Your original match embed
        embed = discord.Embed(
            title="Threads Aligned",
            description="The threads have been gently woven… Here is your match.",
            color=discord.Color.blue()
        )
        embed.add_field(name="Team 1", value=f"{team1[0].mention} & {team1[1].mention}", inline=False)
        embed.add_field(name="Team 2", value=f"{team2[0].mention} & {team2[1].mention}", inline=False)
        embed.set_footer(text="Woven gently by Kyasutorisu")
        await interaction.channel.send(embed=embed)

        # Prebans embed — EXACT same layout/content as your /prebans command
        prebans_embed = self._build_prebans_embed(team1, team2)
        await interaction.channel.send(embed=prebans_embed)

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
            atask = self.afk_monitor.pop(uid, None)
            if atask:
                atask.cancel()

            if len(self.queue) == 0:
                self._cancel_inactivity_monitor()

        await interaction.response.send_message("Your thread has been untied from the queue.", ephemeral=False)

    @app_commands.command(name="queue", description="Peek at those waiting in the thread.")
    @app_commands.guilds(GUILD_ID)
    async def show_queue(self, interaction: Interaction):
        if interaction.guild is None:
            await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)
            return

        async with self.queue_lock:
            if not self.queue:
                await interaction.response.send_message("It’s so quiet in here... The threads of fate are still at rest.", ephemeral=False)
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

        # If the user is not an admin and does not have the required role
        if not interaction.user.guild_permissions.administrator and not any(role.name == required_role for role in interaction.user.roles):
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
            for task in self.afk_monitor.values():
                task.cancel()
            self.voice_channel_monitor.clear()
            self.afk_monitor.clear()
            self._cancel_inactivity_monitor()

        await interaction.response.send_message("The threads of fate have been gently unraveled. The queue is now empty.", ephemeral=False)


async def setup(bot: commands.Bot):
    await bot.add_cog(MatchmakingQueue(bot))
