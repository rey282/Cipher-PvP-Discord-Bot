# roster.py
import discord
from discord.ext import commands
from discord import app_commands
import aiohttp
from PIL import Image, ImageDraw, ImageEnhance, ImageFont
import io
import math
import os
from dotenv import load_dotenv

from utils.db_utils import get_cursor  

load_dotenv()

ROSTER_API = os.getenv("ROSTER_API") or "https://draft-api.cipher.uno/getUsers"
GUILD_ID = int(os.getenv("DISCORD_GUILD_ID"))

FONT_PATH = os.path.join(
    os.path.dirname(__file__),
    "fonts",
    "NotoSansSC-VariableFont_wght.ttf",
)


def load_title_font(size: int) -> ImageFont.FreeTypeFont:
    """Try to load HSR-like font, fallback to default if missing."""
    try:
        return ImageFont.truetype(FONT_PATH, size)
    except Exception:
        try:
            return ImageFont.truetype("DejaVuSans.ttf", size)
        except Exception:
            return ImageFont.load_default()


class Roster(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(
        name="roster",
        description="Show a player's roster as an image.",
    )
    @app_commands.guilds(GUILD_ID)
    @app_commands.describe(member="Whose roster do you want to view?")
    async def roster(
        self,
        interaction: discord.Interaction,
        member: discord.Member | None = None,
    ):
        await interaction.response.defer()

        # Whose roster?
        discord_id = str(member.id if member else interaction.user.id)

        # -------------------------------------------------------
        # 1) Fetch roster (from Yanyan API)
        # -------------------------------------------------------
        async with aiohttp.ClientSession() as session:
            async with session.get(ROSTER_API) as resp:
                roster_users = await resp.json()

        entry = next((u for u in roster_users if u["discordId"] == discord_id), None)
        if not entry:
            return await interaction.followup.send(
                "❌ This player hasn't created a roster yet."
            )

        owned = {c["id"]: c["eidolon"] for c in entry["profileCharacters"]}

        # Choose a display name for the title
        player_name = (
            entry.get("globalName")
            or entry.get("username")
            or f"Player {discord_id}"
        )
        title_text = f"{player_name}'s Roster"

        # -------------------------------------------------------
        # 2) Load character metadata DIRECTLY from PostgreSQL
        # -------------------------------------------------------
        char_map: dict[str, dict] = {}

        with get_cursor() as cur:
            cur.execute(
                """
                SELECT name, rarity, image_url
                FROM characters
                WHERE image_url IS NOT NULL
                """
            )
            rows = cur.fetchall()

        for row in rows:
            url = row["image_url"]
            if not url:
                continue
            file = url.split("/")[-1]
            numeric_id = file.split(".")[0]  # 1308.png → "1308"

            char_map[numeric_id] = {
                "id": numeric_id,
                "name": row["name"],
                "rarity": row["rarity"],
                "image": row["image_url"],
            }

        if not char_map:
            return await interaction.followup.send(
                "❌ No character metadata found in the database."
            )

        # -------------------------------------------------------
        # 3) Sorting logic (Owned → 5★ → 4★ → alphabetical)
        # -------------------------------------------------------
        def sort_key(c: dict):
            return (
                0 if c["id"] in owned else 1,  # owned first
                -c["rarity"],                  # 5★ above 4★
                c["name"],                     # alphabetical
            )

        sorted_chars = sorted(char_map.values(), key=sort_key)

        # -------------------------------------------------------
        # 4) Layout calculations
        # -------------------------------------------------------
        ICON = 96          # icon size
        GAP = 10           # space between icons
        PADDING = 20       # padding around grid
        PER_ROW = 10

        rows_count = max(1, math.ceil(len(sorted_chars) / PER_ROW))

        # width: PADDING + (ICON+GAP)*PER_ROW - GAP + PADDING
        width = PADDING * 2 + PER_ROW * ICON + (PER_ROW - 1) * GAP

        # Measure title height using the target font
        title_font = load_title_font(40)
        dummy_img = Image.new("RGB", (1, 1))
        dummy_draw = ImageDraw.Draw(dummy_img)
        title_bbox = dummy_draw.textbbox((0, 0), title_text, font=title_font)
        title_h = title_bbox[3] - title_bbox[1]

        TITLE_TOP = 30
        UNDERLINE_GAP = 8
        UNDERLINE_EXTRA = 24  # space under the underline

        title_block_bottom = TITLE_TOP + title_h + UNDERLINE_GAP + 3 + UNDERLINE_EXTRA
        grid_top = title_block_bottom + PADDING

        grid_height = rows_count * ICON + (rows_count - 1) * GAP + PADDING
        height = grid_top + grid_height

        # -------------------------------------------------------
        # 5) Create canvas with subtle gradient background
        # -------------------------------------------------------
        canvas = Image.new("RGBA", (width, height), (10, 10, 10, 255))
        draw = ImageDraw.Draw(canvas)

        # gradient: dark purple → dark blue-ish
        for y in range(height):
            t = y / max(1, height - 1)
            r = int(14 + (28 - 14) * t)   # 14 → 28
            g = int(10 + (18 - 10) * t)   # 10 → 18
            b = int(30 + (52 - 30) * t)   # 30 → 52
            draw.line([(0, y), (width, y)], fill=(r, g, b, 255))

        # -------------------------------------------------------
        # 6) Draw title + underline (Style C)
        # -------------------------------------------------------
        title_bbox = draw.textbbox((0, 0), title_text, font=title_font)
        title_w = title_bbox[2] - title_bbox[0]

        title_x = (width - title_w) // 2
        title_y = TITLE_TOP

        # main title
        draw.text((title_x, title_y), title_text, font=title_font, fill=(255, 255, 255, 255))

        # underline (shorter than full width)
        underline_y = title_y + title_h + UNDERLINE_GAP + 10
        underline_margin = int(width * 0.28)
        draw.line(
            [(underline_margin, underline_y), (width - underline_margin, underline_y)],
            fill=(255, 255, 255, 180),
            width=3,
        )

        # -------------------------------------------------------
        # 7) Draw character icons
        # -------------------------------------------------------
        async with aiohttp.ClientSession() as session:
            for idx, c in enumerate(sorted_chars):
                col = idx % PER_ROW
                row = idx // PER_ROW

                x = PADDING + col * (ICON + GAP)
                y = grid_top + row * (ICON + GAP)

                # Load image
                async with session.get(c["image"]) as resp:
                    raw = await resp.read()

                try:
                    icon = Image.open(io.BytesIO(raw)).convert("RGBA")
                except Exception:
                    continue  # skip broken images

                icon = icon.resize((ICON, ICON), Image.LANCZOS)

                # Grey out unowned
                if c["id"] not in owned:
                    icon = ImageEnhance.Brightness(icon).enhance(0.35)
                    icon = icon.convert("LA").convert("RGBA")

                # Slight rounded-corner mask for icons
                mask = Image.new("L", (ICON, ICON), 0)
                mask_draw = ImageDraw.Draw(mask)
                radius = 12
                mask_draw.rounded_rectangle(
                    [(0, 0), (ICON, ICON)],
                    radius=radius,
                    fill=255,
                )

                # Paste with rounded mask
                canvas.paste(icon, (x, y), mask)

                # Rarity border with small glow
                border_rect = [x + 2, y + 2, x + ICON - 2, y + ICON - 2]
                if c["rarity"] == 5:
                    color = (255, 215, 0, 255)  # gold
                elif c["rarity"] == 4:
                    color = (182, 102, 210, 255)  # purple
                else:
                    color = None

                if color:
                    # soft outer glow
                    glow_rect = [border_rect[0] - 1, border_rect[1] - 1,
                                 border_rect[2] + 1, border_rect[3] + 1]
                    draw.rounded_rectangle(glow_rect, radius=14, outline=color, width=1)
                    # main border
                    draw.rounded_rectangle(border_rect, radius=12, outline=color, width=3)

                # Eidolon badge (only if owned)
                if c["id"] in owned:
                    e = owned[c["id"]]

                    # Bigger, bolder badge size
                    badge_w = 38
                    badge_h = 24
                    badge_x = x + 6
                    badge_y = y + ICON - badge_h - 6

                    # Stronger pill background + bold outline
                    badge_rect = [
                        badge_x,
                        badge_y,
                        badge_x + badge_w,
                        badge_y + badge_h,
                    ]
                    draw.rounded_rectangle(
                        badge_rect,
                        radius=8,
                        fill=(0, 0, 0, 210),              # darker background
                        outline=(255, 255, 255, 255),     # FULL white border
                        width=2,                          # thicker outline
                    )

                    # Bigger + clearer text
                    badge_font = load_title_font(16)      # increased from 14 → 16
                    text = f"E{e}"
                    text_bbox = draw.textbbox((0, 0), text, font=badge_font)
                    tw = text_bbox[2] - text_bbox[0]
                    th = text_bbox[3] - text_bbox[1]

                    # Center the text
                    tx = badge_x + (badge_w - tw) // 2
                    ty = badge_y + (badge_h - th) // 2 - 1

                    draw.text((tx, ty), text, font=badge_font, fill=(255, 255, 255, 255))

        # -------------------------------------------------------
        # 8) Send to Discord
        # -------------------------------------------------------
        buffer = io.BytesIO()
        canvas.save(buffer, "PNG")
        buffer.seek(0)

        await interaction.followup.send(
            content=f"**Roster for <@{discord_id}>**",
            file=discord.File(buffer, filename="roster.png"),
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(Roster(bot))
