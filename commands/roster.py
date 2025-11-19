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

load_dotenv()

API = os.getenv("CIPHER_API") or "https://api.cipher.uno"
ROSTER_API = os.getenv("ROSTER_API") or "https://draft-api.cipher.uno/getUsers"
GUILD_ID = int(os.getenv("DISCORD_GUILD_ID"))

ICON_SIZE = 96
PADDING = 28
PER_ROW = 10


class Roster(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.char_meta = None          # metadata cache
        self.icon_cache = {}           # id → preloaded PIL image
        bot.loop.create_task(self.preload_all_icons())  # async preload

    # -----------------------------------------------------------
    # LOAD & CACHE CHARACTER METADATA + IMAGES ONLY ONCE
    # -----------------------------------------------------------
    async def preload_all_icons(self):
        print("[ROSTER] Preloading metadata + icons...")

        async with aiohttp.ClientSession() as session:
            async with session.get(f"{API}/api/characters?cycle=0") as resp:
                data = await resp.json()

        self.char_meta = []
        tasks = []

        for c in data["data"]:
            filename = c["image_url"].split("/")[-1]
            char_id = filename.split(".")[0]

            self.char_meta.append({
                "id": char_id,
                "name": c["name"],
                "rarity": c["rarity"],
                "image": c["image_url"]
            })

            tasks.append(self.download_icon(char_id, c["image_url"]))

        await asyncio.gather(*tasks)

        print(f"[ROSTER] Preloaded {len(self.icon_cache)} character icons!")

    async def download_icon(self, char_id, url):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as resp:
                    raw = await resp.read()

            img = Image.open(io.BytesIO(raw)).convert("RGBA")
            img = img.resize((ICON_SIZE, ICON_SIZE), Image.LANCZOS)

            # Rounded corners
            mask = Image.new("L", (ICON_SIZE, ICON_SIZE), 0)
            draw = ImageDraw.Draw(mask)
            draw.rounded_rectangle([0, 0, ICON_SIZE, ICON_SIZE], radius=18, fill=255)
            img.putalpha(mask)

            self.icon_cache[char_id] = img
        except Exception as e:
            print(f"[ROSTER] Failed to load icon {char_id}: {e}")

    # -----------------------------------------------------------
    # MAIN ROSTER COMMAND
    # -----------------------------------------------------------
    @app_commands.command(name="roster", description="Show a player's roster as an image.")
    @app_commands.guilds(GUILD_ID)
    async def roster(self, interaction: discord.Interaction, member: discord.Member = None):
        await interaction.response.defer()

        discord_id = str(member.id if member else interaction.user.id)

        # Fetch roster data (fast, small JSON)
        async with aiohttp.ClientSession() as session:
            async with session.get(ROSTER_API) as r1:
                roster_users = await r1.json()

        entry = next((u for u in roster_users if u["discordId"] == discord_id), None)
        if not entry:
            return await interaction.followup.send("❌ This player hasn't created a roster yet.")

        owned = {c["id"]: c["eidolon"] for c in entry["profileCharacters"]}

        # Sorting
        def sort_key(c):
            return (0 if c["id"] in owned else 1, -c["rarity"], c["name"])

        chars = sorted(self.char_meta, key=sort_key)

        # -----------------------------------------------------------
        # BUILD CANVAS (Glassmorphism Style)
        # -----------------------------------------------------------
        rows = math.ceil(len(chars) / PER_ROW)
        width = PADDING * 2 + PER_ROW * ICON_SIZE
        height = PADDING * 2 + rows * ICON_SIZE + 70

        canvas = Image.new("RGBA", (width, height), (0, 0, 0, 0))

        # Glass background
        bg = Image.new("RGBA", (width, height), (20, 20, 25, 200))
        blurred = bg.filter(ImageFilter.GaussianBlur(8))
        canvas.paste(blurred, (0, 0))

        draw = ImageDraw.Draw(canvas)
        font = ImageFont.load_default()

        # Header text
        header = f"Roster – {interaction.user.display_name}"
        draw.text((width // 2 - len(header) * 3, 20), header, fill="white", font=font)

        # Offset for grid
        offset_y = 70

        # -----------------------------------------------------------
        # DRAW EACH CHARACTER ICON
        # -----------------------------------------------------------
        for idx, c in enumerate(chars):
            x = PADDING + (idx % PER_ROW) * ICON_SIZE
            y = offset_y + (idx // PER_ROW) * ICON_SIZE

            icon = self.icon_cache.get(c["id"])
            if icon is None:
                continue

            # If not owned → greyscale fade
            img = icon.copy()
            if c["id"] not in owned:
                img = ImageEnhance.Brightness(img).enhance(0.35)
                img = img.convert("LA").convert("RGBA")

            # Soft drop shadow
            shadow = Image.new("RGBA", (ICON_SIZE, ICON_SIZE), (0, 0, 0, 0))
            shadow_draw = ImageDraw.Draw(shadow)
            shadow_draw.rounded_rectangle([2, 2, ICON_SIZE, ICON_SIZE], radius=18, fill=(0, 0, 0, 110))
            canvas.paste(shadow, (x, y), shadow)

            canvas.paste(img, (x, y), img)

            # Rarity glow borders
            if c["rarity"] == 5:
                border_color = (255, 215, 0, 220)  # bright gold
            else:
                border_color = (182, 102, 210, 200)  # purple

            draw.rounded_rectangle([x, y, x + ICON_SIZE, y + ICON_SIZE], radius=18, outline=border_color, width=3)

            # Eidolon badge
            if c["id"] in owned:
                e = owned[c["id"]]
                badge_w, badge_h = 32, 20
                badge_box = [x + 6, y + ICON_SIZE - badge_h - 6, x + 6 + badge_w, y + ICON_SIZE - 6]
                draw.rounded_rectangle(badge_box, radius=6, fill=(0, 0, 0, 180))
                draw.text((badge_box[0] + 8, badge_box[1] + 4), f"E{e}", fill="white", font=font)

        # -----------------------------------------------------------
        # SEND IMAGE
        # -----------------------------------------------------------
        buffer = io.BytesIO()
        canvas.save(buffer, format="PNG")
        buffer.seek(0)

        await interaction.followup.send(
            file=discord.File(buffer, filename="roster.png")
        )


async def setup(bot):
    await bot.add_cog(Roster(bot))
