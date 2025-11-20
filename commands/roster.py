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
from . import shared_cache   # shared global cache

load_dotenv()

BADGE_FONT = ImageFont.truetype(
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 15
)

ROSTER_API = os.getenv("ROSTER_API") or "https://draft-api.cipher.uno/getUsers"
GUILD_ID = int(os.getenv("DISCORD_GUILD_ID"))

FONT_PATH = os.path.join(
    os.path.dirname(__file__),
    "fonts",
    "NotoSansSC-VariableFont_wght.ttf",
)


def load_title_font(size: int):
    try:
        return ImageFont.truetype(FONT_PATH, size)
    except:
        try:
            return ImageFont.truetype("DejaVuSans.ttf", size)
        except:
            return ImageFont.load_default()


class Roster(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        shared_cache.char_map_cache = {}
        shared_cache.icon_cache = {}

    async def preload_all(self):
        """Load character metadata + icons ONCE."""
        char_map = {}

        # --- Load metadata from DB ---
        with get_cursor() as cur:
            cur.execute(
                "SELECT name, rarity, image_url FROM characters WHERE image_url IS NOT NULL"
            )
            rows = cur.fetchall()

        for r in rows:
            url = r["image_url"]
            fid = url.split("/")[-1].split(".")[0]
            char_map[fid] = {
                "id": fid,
                "name": r["name"],
                "rarity": r["rarity"],
                "image": url,
            }

        shared_cache.char_map_cache = char_map

        # --- Preload icons with background ---
        async with aiohttp.ClientSession() as session:
            for cid, meta in char_map.items():
                try:
                    async with session.get(meta["image"]) as resp:
                        raw = await resp.read()

                    img = Image.open(io.BytesIO(raw)).convert("RGBA")

                    # Smart crop
                    w, h = img.size
                    crop_size = int(min(w, h) * 0.85)
                    x_center = w // 2
                    y_center = int(h * 0.35)

                    left = max(0, x_center - crop_size // 2)
                    right = min(w, x_center + crop_size // 2)
                    top = max(0, y_center - crop_size // 2)
                    bottom = min(h, y_center + crop_size // 2)
                    img = img.crop((left, top, right, bottom))

                    # Slight soften
                    img = ImageEnhance.Brightness(img).enhance(0.95)
                    img = ImageEnhance.Contrast(img).enhance(0.96)

                    ICON = 110
                    img = img.resize((ICON, ICON), Image.LANCZOS)

                    # Rarity background
                    if meta["rarity"] == 5:
                        bg_color = (174, 150, 92, 255)
                    elif meta["rarity"] == 4:
                        bg_color = (88, 61, 116, 255)
                    else:
                        bg_color = (54, 54, 54, 255)

                    bg = Image.new("RGBA", (ICON, ICON), bg_color)

                    mask = Image.new("L", (ICON, ICON), 0)
                    draw_mask = ImageDraw.Draw(mask)
                    draw_mask.rounded_rectangle([0, 0, ICON, ICON], radius=22, fill=255)

                    bg.paste(img, (0, 0), img)

                    rounded = Image.new("RGBA", (ICON, ICON))
                    rounded.paste(bg, (0, 0), mask)

                    shared_cache.icon_cache[cid] = rounded

                except:
                    continue

    # ----------------------------------------------------------------
    # /roster command  (NOW CORRECTLY INDENTED)
    # ----------------------------------------------------------------
    @app_commands.command(
        name="roster",
        description="Show a player's roster as an image.",
    )
    @app_commands.guilds(GUILD_ID)
    @app_commands.describe(member="Whose roster do you want to view?")
    async def roster(self, interaction, member: discord.Member | None = None):

        await interaction.response.defer()

        discord_id = str(member.id if member else interaction.user.id)

        # Fetch roster JSON
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(ROSTER_API, timeout=10) as resp:
                    if resp.status != 200:
                        return await interaction.followup.send("⚠️ Roster server unavailable.")
                    roster_users = await resp.json()
        except:
            return await interaction.followup.send("⚠️ Failed to fetch roster data.")

        # roster_index FIXED
        roster_index = {u.get("discordId"): u for u in roster_users}

        entry = roster_index.get(discord_id)
        if not entry:
            return await interaction.followup.send("❌ This player has no roster.")

        owned = {c["id"]: c["eidolon"] for c in entry["profileCharacters"]}

        # Name priority
        roster_name = entry.get("globalName") or entry.get("username")
        member_obj = interaction.guild.get_member(int(discord_id))
        discord_name = member_obj.display_name if member_obj else None

        player_name = roster_name or discord_name or f"User {discord_id}"
        title_text = f"{player_name}'s Roster"

        if not shared_cache.char_map_cache:
            return await interaction.followup.send("❌ Character cache not loaded.")

        char_map = shared_cache.char_map_cache

        # Sorting
        def sort_key(c):
            return (
                0 if c["id"] in owned else 1,
                -c["rarity"],
                c["name"],
            )

        sorted_chars = sorted(char_map.values(), key=sort_key)

        # Layout
        ICON = 110
        GAP = 8
        PADDING = 20
        PER_ROW = 8

        rows = math.ceil(len(sorted_chars) / PER_ROW)
        width = PADDING * 2 + PER_ROW * ICON + (PER_ROW - 1) * GAP

        title_font = load_title_font(40)
        dummy = Image.new("RGB", (1, 1))
        draw_dummy = ImageDraw.Draw(dummy)
        title_h = draw_dummy.textbbox((0, 0), title_text, font=title_font)[3]

        TITLE_TOP = 30
        grid_top = TITLE_TOP + title_h + 45

        height = grid_top + rows * ICON + (rows - 1) * GAP + PADDING

        # Canvas gradient
        canvas = Image.new("RGBA", (width, height), (10, 10, 10, 255))
        draw = ImageDraw.Draw(canvas)

        for y in range(height):
            t = y / (height - 1)
            r = int(14 + (28 - 14) * t)
            g = int(10 + (18 - 10) * t)
            b = int(30 + (52 - 30) * t)
            draw.line([(0, y), (width, y)], fill=(r, g, b, 255))

        # Title
        title_bbox = draw.textbbox((0, 0), title_text, font=title_font)
        title_w = title_bbox[2] - title_bbox[0]
        draw.text(((width - title_w) // 2, TITLE_TOP), title_text, font=title_font, fill="white")

        # Icons + Eid badges
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

            canvas.paste(icon, (x, y), icon)

            if c["id"] in owned:
                e = owned[c["id"]]
                badge_w, badge_h = 40, 26
                bx = x + 4
                by = y + ICON - badge_h - 4

                draw.rounded_rectangle(
                    [bx, by, bx + badge_w, by + badge_h],
                    radius=8,
                    fill=(0, 0, 0, 180),
                )

                text = f"E{e}"
                tw = draw.textbbox((0, 0), text, font=BADGE_FONT)[2]
                th = draw.textbbox((0, 0), text, font=BADGE_FONT)[3]
                tx = bx + (badge_w - tw) // 2
                ty = by + (badge_h - th) // 2 - 3
                draw.text((tx, ty), text, font=BADGE_FONT, fill="white")

        # Send
        buffer = io.BytesIO()
        canvas.save(buffer, "PNG")
        buffer.seek(0)

        await interaction.followup.send(
            content=f"**Roster for {player_name}**",  # NO PING
            file=discord.File(buffer, filename="roster.png"),
        )


# ----------------------------------------------------------------
# REQUIRED setup()
# ----------------------------------------------------------------
async def setup(bot: commands.Bot):
    cog = Roster(bot)
    await cog.preload_all()
    await bot.add_cog(cog)
