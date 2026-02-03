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
from . import shared_cache   # global shared cache for characters + icons

from typing import Dict, List, Optional

load_dotenv()

ROSTER_API = os.getenv("ROSTER_API") or "https://draft-api.cipher.uno/getUsers"
GUILD_ID = int(os.getenv("DISCORD_GUILD_ID"))

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

        # Initialize shared cache structure
        shared_cache.char_map_cache = {}
        shared_cache.icon_cache = {}

    async def preload_all(self):
        """
        Load character metadata + icons ONCE when bot starts.
        Fills shared_cache.char_map_cache and shared_cache.icon_cache.
        """
        char_map: Dict[str, dict] = {}

        # 1) Load metadata from DB
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

        shared_cache.char_map_cache.clear()
        shared_cache.char_map_cache.update(char_map)

        # 2) Preload all icons (crop, zoom, rarity background, rounded edges)
        async with aiohttp.ClientSession() as session:
            for cid, meta in char_map.items():
                try:
                    async with session.get(meta["image"]) as resp:
                        if resp.status != 200:
                            continue
                        raw = await resp.read()

                    img = Image.open(io.BytesIO(raw)).convert("RGBA")

                    # Tighter smart zoom
                    w, h = img.size
                    crop_size = int(min(w, h) * 0.85)

                    x_center = w // 2
                    y_center = int(h * 0.35)

                    left = max(0, x_center - crop_size // 2)
                    right = min(w, x_center + crop_size // 2)
                    top = max(0, y_center - crop_size // 2)
                    bottom = min(h, y_center + crop_size // 2)

                    img = img.crop((left, top, right, bottom))

                    # Soften slightly
                    img = ImageEnhance.Brightness(img).enhance(0.95)
                    img = ImageEnhance.Contrast(img).enhance(0.96)

                    ICON = 110
                    img = img.resize((ICON, ICON), Image.LANCZOS)

                    # Rarity background
                    rarity = char_map[cid]["rarity"]
                    if rarity == 5:
                        bg_color = (174, 150, 92, 255)   # gold-ish
                    elif rarity == 4:
                        bg_color = (88, 61, 116, 255)    # purple
                    else:
                        bg_color = (54, 54, 54, 255)     # gray

                    bg = Image.new("RGBA", (ICON, ICON), bg_color)

                    # Rounded mask
                    mask = Image.new("L", (ICON, ICON), 0)
                    draw_mask = ImageDraw.Draw(mask)
                    draw_mask.rounded_rectangle([0, 0, ICON, ICON], radius=22, fill=255)

                    # Paste face on top of bg
                    bg.paste(img, (0, 0), img)

                    rounded = Image.new("RGBA", (ICON, ICON))
                    rounded.paste(bg, (0, 0), mask)

                    shared_cache.icon_cache[cid] = rounded

                except Exception:
                    continue

    # ──────────────────────────────────────────────────────────────
    # /roster command
    # ──────────────────────────────────────────────────────────────
    @app_commands.command(
        name="roster",
        description="Show a player's roster as an image (optionally combine two players).",
    )
    @app_commands.guilds(GUILD_ID)
    @app_commands.describe(
        member="Primary player whose roster you want to see (default: yourself).",
        member2="Optional second player to build a combined roster with dual Eidolon badges.",
    )
    async def roster(
        self,
        interaction: discord.Interaction,
        member: Optional[discord.Member] = None,
        member2: Optional[discord.Member] = None,
    ):
        await interaction.response.defer(thinking=True)

        guild = interaction.guild
        if guild is None:
            return await interaction.followup.send("❌ This command can only be used in a server.")

        # Resolve players
        p1 = member or interaction.user
        p2 = member2

        # If only member2 is given, treat them as primary
        if member is None and member2 is not None:
            p1 = member2
            p2 = None

        # If both are the same, just treat as single
        if p2 is not None and p2.id == p1.id:
            p2 = None

        is_dual = p2 is not None

        id1 = str(p1.id)
        id2 = str(p2.id) if p2 is not None else None

        # -------------------------------------------------------
        # 1) Fetch roster data from API
        # -------------------------------------------------------

        try:
            timeout = aiohttp.ClientTimeout(total=20, connect=5, sock_read=15)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(ROSTER_API) as resp:
                    if resp.status != 200:
                        return await interaction.followup.send("⚠️ Roster server unavailable.")
                    try:
                        roster_users = await resp.json()
                    except Exception:
                        return await interaction.followup.send("⚠️ Invalid roster data returned.")
        except asyncio.TimeoutError:
            return await interaction.followup.send("⚠️ Roster request timed out.")
        except aiohttp.ClientConnectorError:
            return await interaction.followup.send("⚠️ Could not reach roster server (connection error).")
        except Exception as e:
            return await interaction.followup.send(f"⚠️ Error: `{e}`")


        roster_index = {u.get("discordId"): u for u in roster_users}

        entry1 = roster_index.get(id1)
        entry2 = roster_index.get(id2) if is_dual and id2 is not None else None

        # Handle "no roster" cases
        if not is_dual:
            if not entry1:
                return await interaction.followup.send("❌ This player has no roster saved.")
        else:
            if not entry1 and not entry2:
                return await interaction.followup.send("❌ Neither player has a saved roster.")
            # If one is None, we still proceed — that player just has no owned units.

        def resolve_name(did: str, entry: Optional[dict]) -> str:
            roster_name = (entry or {}).get("globalName") or (entry or {}).get("username")
            member_obj = guild.get_member(int(did))
            discord_name = member_obj.display_name if member_obj else None
            return roster_name or discord_name or f"User {did}"

        name1 = resolve_name(id1, entry1)
        name2 = resolve_name(id2, entry2) if is_dual and id2 is not None else None

        # Owned maps
        owned1: Dict[str, int] = (
            {c["id"]: c["eidolon"] for c in entry1["profileCharacters"]} if entry1 else {}
        )
        owned2: Dict[str, int] = (
            {c["id"]: c["eidolon"] for c in entry2["profileCharacters"]} if entry2 else {}
        )

        if is_dual:
            title_text = f"{name1} • {name2} — Roster"
        else:
            title_text = f"{name1}'s Roster"

        # Combined owned set controls which icons are dimmed
        combined_owned = set(owned1.keys()) | set(owned2.keys())

        # -------------------------------------------------------
        # 2) Character metadata (from shared cache)
        # -------------------------------------------------------
        if not shared_cache.char_map_cache:
            return await interaction.followup.send("❌ Character cache not loaded. Try again in a moment.")

        char_map = shared_cache.char_map_cache

        # -------------------------------------------------------
        # 3) Sorting: owned first, then rarity, then name
        # -------------------------------------------------------
        def sort_key(c: dict):
            return (
                0 if c["id"] in combined_owned else 1,
                -c["rarity"],
                c["name"],
            )

        sorted_chars = sorted(char_map.values(), key=sort_key)

        # -------------------------------------------------------
        # 4) Layout
        # -------------------------------------------------------
        ICON = 110
        GAP = 8
        PADDING = 20
        PER_ROW = 8

        rows_count = max(1, math.ceil(len(sorted_chars) / PER_ROW))
        width = PADDING * 2 + PER_ROW * ICON + (PER_ROW - 1) * GAP

        title_font = load_title_font(40)
        dummy = Image.new("RGB", (1, 1))
        draw_dummy = ImageDraw.Draw(dummy)
        title_bbox = draw_dummy.textbbox((0, 0), title_text, font=title_font)
        title_h = title_bbox[3] - title_bbox[1]

        TITLE_TOP = 30
        UNDERLINE_GAP = 8
        UNDERLINE_EXTRA = 24

        title_block_bottom = TITLE_TOP + title_h + UNDERLINE_GAP + 3 + UNDERLINE_EXTRA
        grid_top = title_block_bottom + PADDING

        grid_height = rows_count * ICON + (rows_count - 1) * GAP + PADDING
        height = grid_top + grid_height

        # -------------------------------------------------------
        # 5) Canvas + gradient background
        # -------------------------------------------------------
        canvas = Image.new("RGBA", (width, height), (10, 10, 10, 255))
        draw = ImageDraw.Draw(canvas)

        for y in range(height):
            t = y / max(1, (height - 1))
            r = int(14 + (28 - 14) * t)
            g = int(10 + (18 - 10) * t)
            b = int(30 + (52 - 30) * t)
            draw.line([(0, y), (width, y)], fill=(r, g, b, 255))

        # -------------------------------------------------------
        # 6) Title + underline
        # -------------------------------------------------------
        title_bbox = draw.textbbox((0, 0), title_text, font=title_font)
        title_w = title_bbox[2] - title_bbox[0]
        title_x = (width - title_w) // 2
        title_y = TITLE_TOP

        draw.text((title_x, title_y), title_text, font=title_font, fill="white")

        underline_y = title_y + title_h + UNDERLINE_GAP + 10
        margin = int(width * 0.28)
        draw.line(
            [(margin, underline_y), (width - margin, underline_y)],
            fill=(255, 255, 255, 180),
            width=3,
        )

        # -------------------------------------------------------
        # 7) Draw icons + Eidolon badges
        # -------------------------------------------------------
        for idx, c in enumerate(sorted_chars):
            col = idx % PER_ROW
            row = idx // PER_ROW

            x = PADDING + col * (ICON + GAP)
            y = grid_top + row * (ICON + GAP)

            base_icon = shared_cache.icon_cache.get(c["id"])
            if not base_icon:
                continue

            icon = base_icon.copy()

            # Dim if neither player owns this character
            if c["id"] not in combined_owned:
                icon = ImageEnhance.Brightness(icon).enhance(0.35)
                icon = icon.convert("LA").convert("RGBA")

            canvas.paste(icon, (x, y), icon)

            # Eidolons for each player
            e1 = owned1.get(c["id"])
            e2 = owned2.get(c["id"]) if is_dual else None

            badge_w, badge_h = 40, 26
            badge_y = y + ICON - badge_h - 4

            def draw_badge(e_val: int, bx: int):
                # dark, no white outline (softer on the eyes)
                draw.rounded_rectangle(
                    [bx, badge_y, bx + badge_w, badge_y + badge_h],
                    radius=8,
                    fill=(0, 0, 0, 190),
                )

                text = f"E{e_val}"
                tb = draw.textbbox((0, 0), text, font=BADGE_FONT)
                tw = tb[2] - tb[0]
                th = tb[3] - tb[1]

                tx = bx + (badge_w - tw) // 2
                ty = badge_y + (badge_h - th) // 2 - 3

                draw.text((tx, ty), text, font=BADGE_FONT, fill="white")

            # Left badge = player 1
            if e1 is not None:
                bx1 = x + 4
                draw_badge(e1, bx1)

            # Right badge = player 2 (if dual)
            if e2 is not None:
                bx2 = x + ICON - badge_w - 4
                draw_badge(e2, bx2)

        # -------------------------------------------------------
        # 8) Send image (NO PING)
        # -------------------------------------------------------
        buffer = io.BytesIO()
        canvas.save(buffer, "PNG")
        buffer.seek(0)

        if is_dual:
            header = f"**Combined roster for {name1} & {name2}**"
        else:
            header = f"**Roster for {name1}**"

        await interaction.followup.send(
            content=header,
            file=discord.File(buffer, filename="roster.png"),
        )


async def setup(bot: commands.Bot):
    cog = Roster(bot)
    await cog.preload_all()   # preload metadata + icons once
    await bot.add_cog(cog)
