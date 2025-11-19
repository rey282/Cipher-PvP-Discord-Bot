# roster.py
import discord
from discord.ext import commands
from discord import app_commands
import aiohttp
from PIL import Image, ImageDraw, ImageEnhance, ImageFont
import io
import math
import os
import asyncio
from dotenv import load_dotenv

from utils.db_utils import get_cursor
from . import shared_cache   

BADGE_FONT = ImageFont.truetype(
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 15
)

load_dotenv()

ROSTER_API = os.getenv("ROSTER_API") or "https://draft-api.cipher.uno/getUsers"
GUILD_ID = int(os.getenv("DISCORD_GUILD_ID"))

FONT_PATH = os.path.join(
    os.path.dirname(__file__),
    "fonts",
    "NotoSansSC-VariableFont_wght.ttf",
)

ICON_SIZE = 132


def load_title_font(size: int) -> ImageFont.FreeTypeFont:
    """Try to load HSR-like font, fallback to default."""
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

        # Initialize shared cache
        shared_cache.char_map_cache = {}
        shared_cache.icon_cache = {}

    async def preload_all(self):
        """Load character metadata + icons ONCE when bot starts."""
        # --------------------------
        # Load metadata from DB
        # --------------------------
        char_map = {}

        with get_cursor() as cur:
            cur.execute(
                "SELECT name, rarity, image_url FROM characters WHERE image_url IS NOT NULL"
            )
            rows = cur.fetchall()

        for r in rows:
            url = r["image_url"]
            fid = url.split("/")[-1].split(".")[0]  # 1003.png -> "1003"
            char_map[fid] = {
                "id": fid,
                "name": r["name"],
                "rarity": r["rarity"],
                "image": url,
            }

        # Store into shared cache
        shared_cache.char_map_cache.clear()
        shared_cache.char_map_cache.update(char_map)

        # --------------------------
        # Preload all icons once
        # --------------------------
        async with aiohttp.ClientSession() as session:
            for cid, meta in char_map.items():
                try:
                    async with session.get(meta["image"]) as resp:
                        raw = await resp.read()

                    img = Image.open(io.BytesIO(raw)).convert("RGBA")

                    # ────────────────────────────────
                    # SMART CENTERED FACE CROP
                    # ────────────────────────────────
                    w, h = img.size

                    # a bit tighter zoom so faces are larger
                    crop_size = int(min(w, h) * 0.75)

                    # center ~slightly above middle
                    x_center = w // 2
                    y_center = int(h * 0.37)

                    left   = x_center - crop_size // 2
                    right  = x_center + crop_size // 2
                    top    = y_center - crop_size // 2
                    bottom = y_center + crop_size // 2

                    # clamp
                    left   = max(0, left)
                    top    = max(0, top)
                    right  = min(w, right)
                    bottom = min(h, bottom)

                    img = img.crop((left, top, right, bottom))

                    # ────────────────────────────────
                    # INTERNAL PADDING + BLACK BG
                    # ────────────────────────────────
                    pad = 8  # small, just enough to avoid border overflow
                    padded = Image.new(
                        "RGBA",
                        (crop_size + pad * 2, crop_size + pad * 2),
                        (0, 0, 0, 255),
                    )
                    padded.paste(img, (pad, pad), img)
                    img = padded

                    # ────────────────────────────────
                    # BRIGHTNESS / CONTRAST
                    # ────────────────────────────────
                    img = ImageEnhance.Brightness(img).enhance(0.93)
                    img = ImageEnhance.Contrast(img).enhance(0.93)

                    # ────────────────────────────────
                    # FINAL SQUARE RESIZE
                    # ────────────────────────────────
                    img = img.resize((ICON_SIZE, ICON_SIZE), Image.LANCZOS)

                    shared_cache.icon_cache[cid] = img

                except Exception:
                    continue


    # ──────────────────────────────────────────────────────────────
    # /roster command
    # ──────────────────────────────────────────────────────────────
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

        discord_id = str(member.id if member else interaction.user.id)

        # -------------------------------------------------------
        # 1) Fetch roster from Yanyan API
        # -------------------------------------------------------
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(ROSTER_API, timeout=10) as resp:
                    if resp.status != 200:
                        return await interaction.followup.send(
                            "⚠️ Roster server unavailable."
                        )

                    try:
                        roster_users = await resp.json()
                    except:
                        return await interaction.followup.send(
                            "⚠️ Invalid roster data returned."
                        )

            except asyncio.TimeoutError:
                return await interaction.followup.send(
                    "⚠️ Roster request timed out."
                )
            except Exception as e:
                return await interaction.followup.send(f"⚠️ Error: `{e}`")

        entry = next((u for u in roster_users if u["discordId"] == discord_id), None)
        if not entry:
            return await interaction.followup.send("❌ This player has no roster.")

        owned = {c["id"]: c["eidolon"] for c in entry["profileCharacters"]}

        player_name = (
            entry.get("globalName")
            or entry.get("username")
            or f"Player {discord_id}"
        )
        title_text = f"{player_name}'s Roster"

        # -------------------------------------------------------
        # 2) Character metadata (from shared cache)
        # -------------------------------------------------------
        if not shared_cache.char_map_cache:
            return await interaction.followup.send("❌ Character cache not loaded.")

        char_map = shared_cache.char_map_cache

        # -------------------------------------------------------
        # 3) Sorting
        # -------------------------------------------------------
        def sort_key(c: dict):
            return (
                0 if c["id"] in owned else 1,
                -c["rarity"],
                c["name"],
            )

        sorted_chars = sorted(char_map.values(), key=sort_key)

        # -------------------------------------------------------
        # 4) Layout
        # -------------------------------------------------------
        ICON = ICON_SIZE
        GAP = 2
        PADDING = 20
        PER_ROW = 8

        rows_count = max(1, math.ceil(len(sorted_chars) / PER_ROW))
        width = PADDING * 2 + PER_ROW * ICON + (PER_ROW - 1) * GAP

        title_font = load_title_font(40)
        dummy = Image.new("RGB", (1, 1))
        draw_dummy = ImageDraw.Draw(dummy)
        title_h = draw_dummy.textbbox((0, 0), title_text, font=title_font)[3]

        TITLE_TOP = 30
        UNDERLINE_GAP = 8
        UNDERLINE_EXTRA = 24

        title_block_bottom = TITLE_TOP + title_h + UNDERLINE_GAP + 3 + UNDERLINE_EXTRA
        grid_top = title_block_bottom + PADDING

        grid_height = rows_count * ICON + (rows_count - 1) * GAP + PADDING
        height = grid_top + grid_height

        # -------------------------------------------------------
        # 5) Canvas + gradient
        # -------------------------------------------------------
        canvas = Image.new("RGBA", (width, height), (10, 10, 10, 255))
        draw = ImageDraw.Draw(canvas)

        for y in range(height):
            t = y / (height - 1)
            r = int(14 + (28 - 14) * t)
            g = int(10 + (18 - 10) * t)
            b = int(30 + (52 - 30) * t)
            draw.line([(0, y), (width, y)], fill=(r, g, b, 255))

        # -------------------------------------------------------
        # 6) Title
        # -------------------------------------------------------
        title_bbox = draw.textbbox((0, 0), title_text, font=title_font)
        title_w = title_bbox[2] - title_bbox[0]
        title_x = (width - title_w) // 2
        title_y = TITLE_TOP

        draw.text((title_x, title_y), title_text, font=title_font, fill="white")

        underline_y = title_y + title_h + UNDERLINE_GAP + 10
        margin = int(width * 0.28)
        draw.line([(margin, underline_y), (width - margin, underline_y)], fill=(255, 255, 255, 180), width=3)

        # -------------------------------------------------------
        # 7) Draw icons + eidolon badges
        # -------------------------------------------------------
        for idx, c in enumerate(sorted_chars):
            col = idx % PER_ROW
            row = idx // PER_ROW

            x = PADDING + col * (ICON + GAP)
            y = grid_top + row * (ICON + GAP)

            icon = shared_cache.icon_cache.get(c["id"])
            if not icon:
                continue

            icon = icon.copy()
            if c["id"] not in owned:
                icon = ImageEnhance.Brightness(icon).enhance(0.35)
                icon = icon.convert("LA").convert("RGBA")

            
            SAFE_PAD = 5

            # mask with inner margin
            rounded = Image.new("L", (ICON, ICON), 0)
            mask_draw = ImageDraw.Draw(rounded)
            mask_draw.rounded_rectangle(
                [SAFE_PAD, SAFE_PAD, ICON - SAFE_PAD, ICON - SAFE_PAD],
                radius=12,
                fill=255,
            )

            # paste full icon using reduced mask
            canvas.paste(icon, (x, y), rounded)


            # rarity border
            border_rect = [
                x + SAFE_PAD + 2,
                y + SAFE_PAD + 2,
                x + ICON - SAFE_PAD - 2,
                y + ICON - SAFE_PAD - 2
            ]

            if c["rarity"] == 5:
                color = (212, 175, 55, 255)
            elif c["rarity"] == 4:
                color = (182, 102, 210, 255)
            else:
                color = None

            if color:
                glow_rect = [
                    border_rect[0] - 1,
                    border_rect[1] - 1,
                    border_rect[2] + 1,
                    border_rect[3] + 1
                ]
                draw.rounded_rectangle(glow_rect, radius=14, outline=color, width=1)
                draw.rounded_rectangle(border_rect, radius=12, outline=color, width=3)

            # eidolon badge
            if c["id"] in owned:
                e = owned[c["id"]]
                badge_w, badge_h = 38, 24
                bx = x + 6
                by = y + ICON - badge_h - 6

                draw.rounded_rectangle([bx, by, bx + badge_w, by + badge_h],
                                       radius=8,
                                       fill=(0, 0, 0, 210),
                                       outline="white",
                                       width=2)

                text = f"E{e}"
                tw = draw.textbbox((0, 0), text, font=BADGE_FONT)[2]
                th = draw.textbbox((0, 0), text, font=BADGE_FONT)[3]
                tx = bx + (badge_w - tw) // 2
                ty = by + (badge_h - th) // 2 - 3

                draw.text((tx, ty), text, font=BADGE_FONT, fill="white")

        # -------------------------------------------------------
        # 8) Send image
        # -------------------------------------------------------
        buffer = io.BytesIO()
        canvas.save(buffer, "PNG")
        buffer.seek(0)

        await interaction.followup.send(
            content=f"**Roster for <@{discord_id}>**",
            file=discord.File(buffer, filename="roster.png"),
        )


async def setup(bot: commands.Bot):
    cog = Roster(bot)
    await cog.preload_all()  
    await bot.add_cog(cog)
