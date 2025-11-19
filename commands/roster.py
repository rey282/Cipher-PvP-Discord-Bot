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


class Roster(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="roster", description="Show a player's roster as an image.")
    @app_commands.guilds(GUILD_ID)
    @app_commands.describe(member="Whose roster do you want to view?")
    async def roster(self, interaction: discord.Interaction, member: discord.Member = None):
        await interaction.response.defer()

        discord_id = str(member.id if member else interaction.user.id)

        # -------------------------------------------------------
        # 1) Fetch roster (from Yanyan API)
        # -------------------------------------------------------
        async with aiohttp.ClientSession() as session:
            async with session.get(ROSTER_API) as resp:
                roster_users = await resp.json()

        entry = next((u for u in roster_users if u["discordId"] == discord_id), None)
        if not entry:
            return await interaction.followup.send("❌ This player hasn't created a roster yet.")

        owned = {c["id"]: c["eidolon"] for c in entry["profileCharacters"]}

        # -------------------------------------------------------
        # 2) Load character metadata DIRECTLY from PostgreSQL
        # -------------------------------------------------------
        char_map = {}

        with get_cursor() as cur:
            cur.execute("SELECT name, rarity, image_url FROM characters")
            rows = cur.fetchall()

        for row in rows:
            url = row["image_url"]
            file = url.split("/")[-1]
            numeric_id = file.split(".")[0]   # 1308.png → 1308

            char_map[numeric_id] = {
                "id": numeric_id,
                "name": row["name"],
                "rarity": row["rarity"],
                "image": row["image_url"],
            }

        # -------------------------------------------------------
        # 3) Sorting logic
        # -------------------------------------------------------
        def sort_key(c):
            return (
                0 if c["id"] in owned else 1,
                -c["rarity"],
                c["name"]
            )

        sorted_chars = sorted(char_map.values(), key=sort_key)

        # -------------------------------------------------------
        # 4) Canvas layout
        # -------------------------------------------------------
        ICON = 96
        PADDING = 14
        PER_ROW = 10
        rows = math.ceil(len(sorted_chars) / PER_ROW)

        width = PADDING * 2 + PER_ROW * ICON
        height = PADDING * 2 + rows * ICON

        canvas = Image.new("RGBA", (width, height), (10, 10, 10, 255))
        draw = ImageDraw.Draw(canvas)
        font = ImageFont.load_default()

        # -------------------------------------------------------
        # 5) Draw icons
        # -------------------------------------------------------
        async with aiohttp.ClientSession() as session:
            for idx, c in enumerate(sorted_chars):
                x = PADDING + (idx % PER_ROW) * ICON
                y = PADDING + (idx // PER_ROW) * ICON

                async with session.get(c["image"]) as resp:
                    raw = await resp.read()

                try:
                    icon = Image.open(io.BytesIO(raw)).convert("RGBA")
                except:
                    continue

                icon = icon.resize((ICON, ICON))

                # Grey out unowned
                if c["id"] not in owned:
                    icon = ImageEnhance.Brightness(icon).enhance(0.35)
                    icon = icon.convert("LA").convert("RGBA")

                canvas.paste(icon, (x, y), icon)

                # Border (rarity)
                if c["rarity"] == 5:
                    draw.rectangle([x+2, y+2, x+ICON-2, y+ICON-2], outline="gold", width=4)
                elif c["rarity"] == 4:
                    draw.rectangle([x+2, y+2, x+ICON-2, y+ICON-2], outline="#b666d2", width=4)

                # Eidolon badge
                if c["id"] in owned:
                    e = owned[c["id"]]
                    draw.rectangle([x, y+ICON-20, x+28, y+ICON], fill=(0, 0, 0, 180))
                    draw.text((x+4, y+ICON-17), f"E{e}", fill="white", font=font)

        # -------------------------------------------------------
        # 6) Send to Discord
        # -------------------------------------------------------
        buffer = io.BytesIO()
        canvas.save(buffer, "PNG")
        buffer.seek(0)

        await interaction.followup.send(
            content=f"**Roster for <@{discord_id}>**",
            file=discord.File(buffer, filename="roster.png")
        )


async def setup(bot):
    await bot.add_cog(Roster(bot))
