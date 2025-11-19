import discord
import random
import os
import re
import io
import math
from typing import List, Optional, Dict

from discord.ext import commands
from discord import app_commands
from discord import Interaction

from utils.db_utils import load_elo_data, save_elo_data, initialize_player_data
from utils.rank_utils import get_rank
from dotenv import load_dotenv

# for roster images
import aiohttp
from PIL import Image, ImageDraw, ImageEnhance, ImageFont

from . import shared_cache  

load_dotenv()
GUILD_ID = int(os.getenv("DISCORD_GUILD_ID"))
ROSTER_API = os.getenv("ROSTER_API") or "https://draft-api.cipher.uno/getUsers"

ALLOWED_COLORS = {
    "red": 0xFF4C4C,
    "orange": 0xFFA500,
    "yellow": 0xFFFF66,
    "green": 0x66FF66,
    "blue": 0x66CCFF,
    "purple": 0xB19CD9,
    "pink": 0xFFB6C1,
    "white": 0xF8F8FF,
    "gray": 0xB0B0B0,
    "black": 0x1E1E1E,
    "brown": 0xA0522D,
    "cyan": 0x00FFFF,
    "magenta": 0xFF00FF,
}

# ───────────── fonts for roster images ─────────────

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


# ───────────── Modals ─────────────


class DescriptionModal(discord.ui.Modal, title="Rewrite Your Soul’s Thread"):
    description = discord.ui.TextInput(
        label="What gentle words describe your soul?",
        placeholder="You may leave this blank if you prefer silence…",
        max_length=43,
        style=discord.TextStyle.short,
        required=False,
    )

    profile_color = discord.ui.TextInput(
        label="What color should your thread glow with?",
        placeholder="Try pink, blue, or #FF69B4…",
        required=False,
        max_length=16,
        style=discord.TextStyle.short,
    )

    banner_url = discord.ui.TextInput(
        label="Do you have a banner for your soul’s thread?",
        placeholder="Paste a direct image or gif URL here or type none to remove",
        required=False,
        max_length=300,
        style=discord.TextStyle.short,
    )

    def __init__(self, user_id):
        super().__init__()
        self.user_id = str(user_id)

    async def on_submit(self, interaction: discord.Interaction):
        desc = str(self.description).strip()
        color_input = str(self.profile_color).strip().lower()
        color_code = None
        update_desc = True

        banner = str(self.banner_url).strip()
        update_banner = False

        elo_data = load_elo_data()  # moved up so we can safely use it below

        if banner:
            # allow "none"/"default" handling below
            if banner.lower() not in ("none", "default"):
                if any(
                    banner.lower().endswith(ext)
                    for ext in (".png", ".jpg", ".jpeg", ".gif", ".webp")
                ):
                    if re.match(r"^https:\/\/", banner, re.IGNORECASE):
                        update_banner = True
                    else:
                        await interaction.response.send_message(
                            "Forgive me… your banner must begin with `https://` to be safely woven into your profile.",
                            ephemeral=True,
                        )
                        return
                else:
                    await interaction.response.send_message(
                        "Ah… that banner doesn't seem to be a direct image link. I can only accept `.png`, `.jpg`, `.gif`, etc.",
                        ephemeral=True,
                    )
                    return

        # Basic link/URL validation for description
        if desc and re.search(
            r"(https?:\/\/|discord\.gg|discordapp\.com|@|\.com|\.net|\.org)",
            desc,
            re.IGNORECASE,
        ):
            await interaction.response.send_message(
                "Oh… I must apologize… descriptions with links aren’t permitted. It’s for your safety…",
                ephemeral=True,
            )
            return

        # Reset to default if user types 'none' or 'default'
        if desc.lower() == "none":
            desc = ""
        elif desc.lower() == "default":
            desc = "A glimpse into this soul’s gentle journey…"
        elif not desc:
            update_desc = False

        # Handle banner removal
        if banner.lower() in ("none", "default"):
            elo_data.setdefault(self.user_id, initialize_player_data(self.user_id))
            elo_data[self.user_id].pop("banner_url", None)

        # Validate color
        if color_input:
            if color_input in ("none", "default"):
                color_code = 0xB197FC  # Castorice default
            elif color_input in ALLOWED_COLORS:
                color_code = ALLOWED_COLORS[color_input]
            elif re.fullmatch(r"#?[0-9a-f]{6}", color_input, re.IGNORECASE):
                color_code = int(color_input.replace("#", ""), 16)
            else:
                await interaction.response.send_message(
                    f"Ah… I didn’t quite understand that color. Please whisper one of these:\n"
                    f"> *{', '.join(ALLOWED_COLORS.keys())}*\n"
                    f"Or a hex code like `#FAB4C0`, or type `default` to reset.",
                    ephemeral=True,
                )
                return

        # Ensure player exists
        if self.user_id not in elo_data:
            elo_data[self.user_id] = initialize_player_data(self.user_id)

        if update_banner:
            elo_data[self.user_id]["banner_url"] = banner

        if update_desc:
            elo_data[self.user_id]["description"] = desc

        if color_code is not None:
            elo_data[self.user_id]["color"] = color_code

        save_elo_data(elo_data)

        await interaction.response.send_message(
            "Your soul’s thread has been gently woven, as if whispered by the loom itself.\nA new chapter begins in your gentle journey…",
            ephemeral=False,
        )


class RegisterPlayerModal(discord.ui.Modal, title="Gently Update Your Presence"):
    uid = discord.ui.TextInput(label="UID", required=False, placeholder="9-digit UID")

    async def on_submit(self, interaction: Interaction):
        await interaction.response.defer()
        elo_data = load_elo_data()
        player_id = str(interaction.user.id)

        uid_input = self.uid.value.strip()

        # Validate UID format if provided
        if uid_input and (not uid_input.isdigit() or len(uid_input) != 9):
            await interaction.followup.send(
                "<:Unamurice:1349309283669377064> U-Um… I think the UID should be exactly 9 numbers... Could you double-check it for me?",
                ephemeral=True,
            )
            return

        # Case 1: Existing player
        if player_id in elo_data:
            player_data = elo_data[player_id]
            if uid_input:
                player_data["uid"] = uid_input
            action = "updated"
        # Case 2: New registration
        else:
            if not uid_input:
                await interaction.followup.send(
                    "<:Unamurice:1349309283669377064> O-Oh… I’m sorry, but I need your UID to begin your registration. Without it, I can’t properly weave your thread…",
                    ephemeral=True,
                )
                return

            elo_data[player_id] = {
                "uid": uid_input,
                "elo": 200,
                "win_rate": 0.0,
                "games_played": 0,
                "discord_name": interaction.user.display_name,
            }
            action = "registered"

        save_elo_data(elo_data)

        embed = discord.Embed(
            title=f"Profile {action.capitalize()}",
            description="Your presence has been gently recorded…",
            color=discord.Color.purple(),
        )

        if uid_input:
            embed.add_field(name="UID", value=f"`{uid_input}`", inline=False)

        if action == "registered":
            embed.add_field(name="Starting ELO", value="`200`", inline=False)

        embed.set_footer(text="Gently handled by Kyasutorisu")

        await interaction.followup.send(embed=embed, ephemeral=False)


Member = discord.Member


# ───────────── Matchmaking helper view (Random vs Manual) ─────────────


class MatchmakingTeamSelect(discord.ui.View):
    def __init__(
        self,
        cog: "MatchmakingCommands",
        players: List[Member],
        invoker_id: int,
        timeout: float = 60.0,
    ):
        super().__init__(timeout=timeout)
        self.cog = cog
        self.players = players
        self.invoker_id = invoker_id

    async def interaction_check(self, interaction: Interaction) -> bool:
        if interaction.user.id != self.invoker_id:
            await interaction.response.send_message(
                "Only the one who invoked this command may choose how to weave the teams…",
                ephemeral=True,
            )
            return False
        return True

    async def _finalize(self, interaction: Interaction, ordered_players: List[Member], randomized: bool):
        # disable buttons
        for child in self.children:
            child.disabled = True

        note = (
            "\n\nTeams chosen: **Randomized**."
            if randomized
            else "\n\nTeams chosen: **Manual (1+2 vs 3+4)**."
        )
        await interaction.response.edit_message(
            content=interaction.message.content + note,
            view=self,
        )

        team1, team2 = ordered_players[:2], ordered_players[2:]
        channel = interaction.channel

        # Announce match (same style as queue)
        mentions = ", ".join(p.mention for p in ordered_players)
        await channel.send(
            f"**Match Found!**\n"
            f"**Players:** {mentions}\n"
            f"Fate has woven your paths together. Best of luck"
        )

        match_embed = discord.Embed(
            title="Threads Aligned",
            description="The threads have been gently woven… Here is your match.",
            color=discord.Color.blue(),
        )
        match_embed.add_field(
            name="Team 1", value=f"{team1[0].mention} & {team1[1].mention}", inline=False
        )
        match_embed.add_field(
            name="Team 2", value=f"{team2[0].mention} & {team2[1].mention}", inline=False
        )
        match_embed.set_footer(text="Woven gently by Kyasutorisu")
        await channel.send(embed=match_embed)

        # Prebans embed (same logic as queue)
        prebans_embed = self.cog._build_prebans_embed(team1, team2)
        await channel.send(embed=prebans_embed)

        # Roster images (Team 1 then Team 2)
        try:
            await self.cog._send_match_rosters(channel, team1, team2)
        except Exception as e:
            print(f"[matchmaking] Failed to send match rosters: {e}")

        self.stop()

    @discord.ui.button(label="Randomize Teams", style=discord.ButtonStyle.primary)
    async def randomize_button(
        self, interaction: Interaction, button: discord.ui.Button
    ):
        players = self.players[:]
        random.shuffle(players)
        await self._finalize(interaction, players, randomized=True)

    @discord.ui.button(label="Manual (1+2 vs 3+4)", style=discord.ButtonStyle.secondary)
    async def manual_button(
        self, interaction: Interaction, button: discord.ui.Button
    ):
        await self._finalize(interaction, self.players, randomized=False)


# ───────────── Cog ─────────────


class MatchmakingCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # ─────────── shared prebans helper (same as queue.py) ───────────

    def _build_prebans_embed(
        self, team1: List[Member], team2: List[Member]
    ) -> discord.Embed:
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
                color=discord.Color.purple(),
            )
            embed.add_field(
                name="Teams Aligned",
                value=f"{format_team(team1)} (Avg: {points1:.1f} pts)\n"
                f"{format_team(team2)} (Avg: {points2:.1f} pts)",
                inline=False,
            )
            embed.add_field(
                name="Result",
                value="It seems the threads of fate have tied these teams... No pre-bans required for either side.\n\n"
                f"*Total point difference: {point_diff:.1f}*",
                inline=False,
            )
            embed.set_footer(text="Handled with care by Kyasutorisu")
            return embed

        # Thresholds identical to queue
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
            color=discord.Color.purple(),
        )
        embed.add_field(
            name="Teams Alligned",  # keep the original spelling
            value=(
                f" {format_team(team1)} (Avg: {points1:.1f} pts)\n"
                f" {format_team(team2)} (Avg: {points2:.1f} pts)"
            ),
            inline=False,
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
            value="\n".join(ban_info)
            + f"\n\n*Total point difference: {point_diff:.1f}*",
            inline=False,
        )
        embed.set_footer(text="Handled with care by Kyasutorisu")
        return embed

    # ─────────── roster helpers (same as queue.py, using shared_cache) ───────────

    async def _fetch_roster_users(self) -> Optional[list]:
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
        if len(team) < 2:
            return None

        p1, p2 = team[0], team[1]
        id1, id2 = str(p1.id), str(p2.id)

        entry1 = roster_index.get(id1)
        entry2 = roster_index.get(id2)

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

        char_map_cache = shared_cache.char_map_cache
        icon_cache = shared_cache.icon_cache

        if not char_map_cache:
            return None

        def sort_key(c: dict):
            return (
                0 if c["id"] in combined_owned else 1,
                -c["rarity"],
                c["name"],
            )

        sorted_chars = sorted(char_map_cache.values(), key=sort_key)

        ICON = 96
        GAP = 10
        PADDING = 20
        PER_ROW = 10

        rows_count = max(1, math.ceil(len(sorted_chars) / PER_ROW))
        width = PADDING * 2 + PER_ROW * ICON + (PER_ROW - 1) * GAP

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

        canvas = Image.new("RGBA", (width, height), (10, 10, 10, 255))
        draw = ImageDraw.Draw(canvas)

        for y in range(height):
            t = y / max(1, height - 1)
            r = int(14 + (28 - 14) * t)
            g = int(10 + (18 - 10) * t)
            b = int(30 + (52 - 30) * t)
            draw.line([(0, y), (width, y)], fill=(r, g, b, 255))

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

        for idx, c in enumerate(sorted_chars):
            col = idx % PER_ROW
            row = idx // PER_ROW

            x = PADDING + col * (ICON + GAP)
            y = grid_top + row * (ICON + GAP)

            base_icon = icon_cache.get(c["id"])
            if base_icon is None:
                continue

            icon = base_icon.copy()

            if c["id"] not in combined_owned:
                icon = ImageEnhance.Brightness(icon).enhance(0.35)
                icon = icon.convert("LA").convert("RGBA")

            mask = Image.new("L", (ICON, ICON), 0)
            mask_draw = ImageDraw.Draw(mask)
            radius = 12
            mask_draw.rounded_rectangle(
                [(0, 0), (ICON, ICON)],
                radius=radius,
                fill=255,
            )

            canvas.paste(icon, (x, y), mask)

            border_rect = [x + 2, y + 2, x + ICON - 2, y + ICON - 2]
            if c["rarity"] == 5:
                color = (255, 215, 0, 255)
            elif c["rarity"] == 4:
                color = (182, 102, 210, 255)
            else:
                color = None

            if color:
                glow_rect = [
                    border_rect[0] - 1,
                    border_rect[1] - 1,
                    border_rect[2] + 1,
                    border_rect[3] + 1,
                ]
                draw.rounded_rectangle(glow_rect, radius=14, outline=color, width=1)
                draw.rounded_rectangle(border_rect, radius=12, outline=color, width=3)

            e1 = owned1.get(c["id"])
            e2 = owned2.get(c["id"])

            badge_w = 38
            badge_h = 24
            badge_y = y + ICON - badge_h - 6

            def draw_badge(e_value: int, bx: int):
                badge_rect = [
                    bx,
                    badge_y,
                    bx + badge_w,
                    badge_y + badge_h,
                ]
                draw.rounded_rectangle(
                    badge_rect,
                    radius=8,
                    fill=(0, 0, 0, 210),
                    outline=(255, 255, 255, 255),
                    width=2,
                )
                text = f"E{e_value}"
                text_bbox = draw.textbbox((0, 0), text, font=BADGE_FONT)
                tw = text_bbox[2] - text_bbox[0]
                th = text_bbox[3] - text_bbox[1]
                tx = bx + (badge_w - tw) // 2
                ty = badge_y + (badge_h - th) // 2 - 3
                draw.text(
                    (tx, ty),
                    text,
                    font=BADGE_FONT,
                    fill=(255, 255, 255, 255),
                )

            if e1 is not None:
                bx1 = x + 6
                draw_badge(e1, bx1)
            if e2 is not None:
                bx2 = x + ICON - badge_w - 6
                draw_badge(e2, bx2)

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
        char_map_cache = shared_cache.char_map_cache
        icon_cache = shared_cache.icon_cache

        if not char_map_cache or not icon_cache:
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

    # ─────────── Slash commands ───────────

    @app_commands.command(
        name="matchmaking",
        description="Allow me to gently weave a 2v2 from the threads you've offered...",
    )
    @app_commands.guilds(GUILD_ID)
    @app_commands.describe(
        player1="First player",
        player2="Second player",
        player3="Third player",
        player4="Fourth player",
    )
    async def matchmaking(
        self,
        interaction: Interaction,
        player1: discord.Member,
        player2: discord.Member,
        player3: discord.Member,
        player4: discord.Member,
    ):
        # Validate unique players
        players = [player1, player2, player3, player4]
        if len({p.id for p in players}) != 4:
            await interaction.response.send_message(
                "O-Oh… it seems some players are listed more than once.\nAll souls must be unique for the threads to form properly…",
                ephemeral=False,
            )
            return

        mentions = ", ".join(p.mention for p in players)
        view = MatchmakingTeamSelect(self, players, interaction.user.id)

        await interaction.response.send_message(
            content=(
                "Please choose how to weave these threads into teams:\n"
                f"Players: {mentions}\n\n"
                "**Randomize Teams** → random 2v2\n"
                "**Manual (1+2 vs 3+4)** → Team 1 = first two, Team 2 = last two"
            ),
            view=view,
        )

    # (existing /register, /setplayercard, /playercard, /prebans stay the same)

    @app_commands.command(
        name="register",
        description="Allow me to gently record or update your thread…",
    )
    @app_commands.guilds(GUILD_ID)
    async def register(self, interaction: Interaction):
        await interaction.response.send_modal(RegisterPlayerModal())

    @app_commands.command(
        name="setplayercard",
        description="Gently adjust your soul’s card — a new whisper, a new color…",
    )
    @app_commands.guilds(GUILD_ID)
    async def setdescription(self, interaction: discord.Interaction):
        modal = DescriptionModal(interaction.user.id)
        await interaction.response.send_modal(modal)

    @app_commands.command(
        name="playercard",
        description="Would you like to glimpse a player’s thread…? I can show you their profile.",
    )
    @app_commands.guilds(GUILD_ID)
    async def profile(self, interaction: Interaction, user: discord.Member = None):
        await interaction.response.defer()
        user = user or interaction.user
        elo_data = load_elo_data()
        player_id = str(user.id)

        player_data = elo_data.get(player_id, {})

        elo = player_data.get("elo", 200)
        win_rate = player_data.get("win_rate", 0.0)
        games_played = player_data.get("games_played", 0)
        uid = player_data.get("uid", "Not Registered")
        mirror_id = player_data.get("mirror_id", "Not Set")
        points = player_data.get("points", 0)

        rank = get_rank(elo_score=elo, player_id=player_id, elo_data=elo_data)

        banner_url = player_data.get("banner_url")
        color = elo_data.get(player_id, {}).get("color", 0xB197FC)
        description = elo_data.get(player_id, {}).get(
            "description", "A glimpse into this soul’s gentle journey…"
        )
        embed = discord.Embed(
            title=f"Thread of {user.display_name}",
            description=description,
            color=color,
        )
        embed.set_thumbnail(url=user.display_avatar.url)

        embed.add_field(name="ELO Woven", value=f"{elo:.0f}", inline=False)
        embed.add_field(
            name="Stats",
            value=f"Win Rate: {win_rate * 100:.0f}%\n"
            f"Trials Faced: {games_played}",
            inline=False,
        )
        embed.add_field(
            name="Reflections",
            value=f"UID: {uid}\n"
            f"Total Cost: {points}\n"
            f"Rank: {rank}",
            inline=False,
        )

        if banner_url:
            embed.set_image(url=banner_url)

        embed.set_footer(text=f"Handled with care by Kyasutorisu")

        await interaction.followup.send(embed=embed)

    @app_commands.command(
        name="prebans",
        description="Allow me to gently calculate the pre-bans, with teams woven into their fates.",
    )
    @app_commands.guilds(GUILD_ID)
    @app_commands.describe(
        team1_player1="First player (Team 1)",
        team1_player2="Second player (Team 1, optional)",
        team2_player1="First player (Team 2)",
        team2_player2="Second player (Team 2, optional)",
    )
    async def prebans(
        self,
        interaction: Interaction,
        team1_player1: discord.Member,
        team2_player1: discord.Member,
        team1_player2: discord.Member = None,
        team2_player2: discord.Member = None,
    ):
        await interaction.response.defer()

        team1 = [p for p in [team1_player1, team1_player2] if p is not None]
        team2 = [p for p in [team2_player1, team2_player2] if p is not None]

        embed = self._build_prebans_embed(team1, team2)
        await interaction.followup.send(embed=embed)


async def setup(bot):
    await bot.add_cog(MatchmakingCommands(bot))
