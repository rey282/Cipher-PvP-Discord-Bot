# roster.py
import discord
from discord.ext import commands
from discord import app_commands
import aiohttp
from PIL import Image, ImageDraw, ImageEnhance, ImageFont, ImageFilter
import io
import math
import os
from dotenv import load_dotenv
from utils.db_utils import get_cursor

load_dotenv()

ROSTER_API = os.getenv("ROSTER_API") or "https://draft-api.cipher.uno/getUsers"
GUILD_ID = int(os.getenv("DISCORD_GUILD_ID"))

ICON_SIZE = 110                # bigger icons
BORDER_SIZE = 6
PADDING = 20
PER_ROW = 9

# --- Color themes matching your Cipher website ---
BACKGROUND = (15, 15, 25, 255)               # dark blue-ish
CARD_BORDER_5 = (255, 215, 0, 255)           # gold
CARD_BORDER_4 = (182, 102, 210, 255)         # purple
OWNED_SHADOW = (255, 255, 255, 120)

class Roster(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.icon_cache = {}   # {id: PIL.Image}

    async def preload_icons(self):
        """Loads all character icons ONCE at bot startup for fast rendering."""
        print("[Roster] Preloading character icons...")

        with get_cursor() as cur:
            cur.execute("SELECT name, rarity, image_url FROM characters")
            rows = cur.fetchall()

        async with aiohttp.ClientSession() as session:
            for row in rows:
                url = row["image_url"]
                num = url.split("/")[-1].split(".")[0]

                try:
                    async with session.get(url) as r:
                        img_bytes = await r.read()
                        img = Image.open(io.BytesIO(img_bytes)).convert("RGBA")
                        img = img.resize((ICON_SIZE, ICON_SIZE), Image.LANCZOS)
                        self.icon_cache[num] = img
                except:
                    pass

        print(f"[Roster] Cached {len(self.icon_cache)} icons.")

    # Run preload automatically
    @commands.Cog.listener()
    async def on_ready(self):
        await self.preload_icons()

    @app_commands.command(name="roster", description="Show a player's roster as an image.")
    @app_commands.guilds(GUILD_ID)
    async def roster(self, interaction, member: discord.Member = None):
        await interaction.response.defer()
        user_id = str(member.id if member else interaction.user.id)

        # 1) Fetch roster from Yanyan API
        async with aiohttp.ClientSession() as session:
            async with session.get(ROSTER_API) as r:
                roster_users = await r.json()

        entry = next((u for u in roster_users if u["discordId"] == user_id), None)
        if not entry:
            return await interaction.followup.send("❌ This player does not have a roster saved.")

        owned = {c["id"]: c["eidolon"] for c in entry["profileCharacters"]}

        # 2) Fetch metadata from DB
        with get_cursor() as cur:
            cur.execute("SELECT name, rarity, image_url FROM characters")
            rows = cur.fetchall()

        characters = []
        for row in rows:
            url = row["image_url"]
            char_id = url.split("/")[-1].split(".")[0]
            characters.append({
                "id": char_id,
                "name": row["name"],
                "rarity": row["rarity"],
            })

        # sort: owned → rarity → name
        characters.sort(key=lambda c: (
            0 if c["id"] in owned else 1,
            -c["rarity"],
            c["name"]
        ))

        # 3) Canvas
        rows_needed = math.ceil(len(characters) / PER_ROW)
        W = PADDING * 2 + PER_ROW * ICON_SIZE
        H = PADDING * 2 + rows_needed * ICON_SIZE

        canvas = Image.new("RGBA", (W, H), BACKGROUND)
        draw = ImageDraw.Draw(canvas)
        font = ImageFont.load_default()

        # 4) Draw character cards
        for idx, c in enumerate(characters):
            x = PADDING + (idx % PER_ROW) * ICON_SIZE
            y = PADDING + (idx // PER_ROW) * ICON_SIZE

            img = self.icon_cache.get(c["id"])
            if img is None:
                continue

            # Duplicate to avoid modifying cache image
            icon = img.copy()

            # grey out unowned
            if c["id"] not in owned:
                icon = ImageEnhance.Brightness(icon).enhance(0.35).convert("LA").convert("RGBA")

            # glow for owned
            if c["id"] in owned:
                glow = icon.filter(ImageFilter.GaussianBlur(radius=10))
                canvas.paste(glow, (x - 5, y - 5), glow)

            canvas.paste(icon, (x, y), icon)

            # rarity border
            border_color = None
            if c["rarity"] == 5:
                border_color = CARD_BORDER_5
            elif c["rarity"] == 4:
                border_color = CARD_BORDER_4

            if border_color:
                draw.rectangle(
                    [x, y, x + ICON_SIZE, y + ICON_SIZE],
                    outline=border_color,
                    width=BORDER_SIZE
                )

            # E-level badge
            if c["id"] in owned:
                e = owned[c["id"]]
                badge_box = [x, y + ICON_SIZE - 24, x + 36, y + ICON_SIZE]
                draw.rectangle(badge_box, fill=(0, 0, 0, 180))
                draw.text((x + 6, y + ICON_SIZE - 20), f"E{e}", fill="white", font=font)

        # 5) Send image
        buf = io.BytesIO()
        canvas.save(buf, "PNG")
        buf.seek(0)

        await interaction.followup.send(
            file=discord.File(buf, filename="roster.png"),
            content=f"**Roster for <@{user_id}>**"
        )


async def setup(bot):
    await bot.add_cog(Roster(bot))
