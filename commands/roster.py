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

load_dotenv()

API = os.getenv("CIPHER_API") or "https://api.cipher.uno"
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
        # 1) Fetch roster + metadata from your Cipher backend
        # -------------------------------------------------------
        async with aiohttp.ClientSession() as session:
            # Roster
            async with session.get(f"{API}/api/roster/users") as r1:
                roster_users = await r1.json()

            # Character metadata
            async with session.get(f"{API}/api/characters?cycle=0") as r2:
                meta = await r2.json()

        # Find user entry
        entry = next((u for u in roster_users if u["discordId"] == discord_id), None)
        if not entry:
            return await interaction.followup.send("❌ This player hasn't created a roster yet.")

        owned = {c["id"]: c["eidolon"] for c in entry["profileCharacters"]}

        # Map ID → metadata
        char_map = {}
        for c in meta["data"]:
            filename = c["image_url"].split("/")[-1]
            char_id = filename.split(".")[0]
            char_map[char_id] = {
                "id": char_id,
                "name": c["name"],
                "rarity": c["rarity"],
                "image": c["image_url"]
            }

        # -------------------------------------------------------
        # 2) Sorting logic (Owned → 5★ → 4★ → alphabetical)
        # -------------------------------------------------------
        def sort_key(c):
            return (
                0 if c["id"] in owned else 1,
                -c["rarity"],
                c["name"]
            )

        sorted_chars = sorted(char_map.values(), key=sort_key)

        # -------------------------------------------------------
        # 3) Canvas layout
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
        # 4) Draw character icons
        # -------------------------------------------------------
        async with aiohttp.ClientSession() as session:
            for idx, c in enumerate(sorted_chars):
                x = PADDING + (idx % PER_ROW) * ICON
                y = PADDING + (idx // PER_ROW) * ICON

                # Load image
                async with session.get(c["image"]) as resp:
                    raw = await resp.read()
                icon = Image.open(io.BytesIO(raw)).convert("RGBA")
                icon = icon.resize((ICON, ICON))

                # Grey out unowned
                if c["id"] not in owned:
                    icon = ImageEnhance.Brightness(icon).enhance(0.35)
                    icon = icon.convert("LA").convert("RGBA")

                canvas.paste(icon, (x, y), icon)

                # Rarity border
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
        # 5) Send image to Discord
        # -------------------------------------------------------
        buffer = io.BytesIO()
        canvas.save(buffer, format="PNG")
        buffer.seek(0)

        await interaction.followup.send(
            content=f"**Roster for <@{discord_id}>**",
            file=discord.File(buffer, filename="roster.png")
        )


async def setup(bot):
    await bot.add_cog(Roster(bot))
