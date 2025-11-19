import discord
from discord.ext import commands
from discord import app_commands
import aiohttp
from PIL import Image, ImageDraw, ImageEnhance, ImageFont, ImageFilter
import io, math, os
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
    async def roster(self, interaction: discord.Interaction, member: discord.Member = None):

        await interaction.response.defer()
        discord_id = str(member.id if member else interaction.user.id)

        # -------------------------------------------------------
        # 1) Fetch roster (Yanyan API)
        # -------------------------------------------------------
        async with aiohttp.ClientSession() as session:
            async with session.get(ROSTER_API) as resp:
                roster_users = await resp.json()

        entry = next((u for u in roster_users if u["discordId"] == discord_id), None)
        if not entry:
            return await interaction.followup.send("❌ This player hasn't created a roster yet.")

        owned = {c["id"]: c["eidolon"] for c in entry["profileCharacters"]}

        # -------------------------------------------------------
        # 2) Load metadata from DB
        # -------------------------------------------------------
        with get_cursor() as cur:
            cur.execute("SELECT name, rarity, image_url FROM characters ORDER BY rarity DESC, name ASC")
            rows = cur.fetchall()

        char_map = {}
        for row in rows:
            char_id = row["image_url"].split("/")[-1].split(".")[0]
            char_map[char_id] = {
                "id": char_id,
                "name": row["name"],
                "rarity": row["rarity"],
                "image": row["image_url"],
            }

        # Sort
        def sort_key(c):
            return (0 if c["id"] in owned else 1, -c["rarity"], c["name"])
        sorted_chars = sorted(char_map.values(), key=sort_key)

        # -------------------------------------------------------
        # 3) Styled Canvas
        # -------------------------------------------------------
        ICON = 96
        PADDING = 20
        PER_ROW = 10
        rows = math.ceil(len(sorted_chars) / PER_ROW)

        width = PADDING * 2 + PER_ROW * ICON
        height = PADDING * 2 + rows * ICON

        # Gradient background
        bg = Image.new("RGB", (width, height), "#0f0f14")
        overlay = Image.new("RGBA", (width, height), "#1a1a22cc")
        bg = Image.alpha_composite(bg.convert("RGBA"), overlay)

        canvas = bg.copy()
        draw = ImageDraw.Draw(canvas)
        font = ImageFont.load_default()

        # -------------------------------------------------------
        # 4) Draw icons
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

                # Unowned → grayscale dim
                if c["id"] not in owned:
                    icon = ImageEnhance.Brightness(icon).enhance(0.40)
                    icon = icon.convert("LA").convert("RGBA")

                # Rounded corners
                mask = Image.new("L", (ICON, ICON), 0)
                shape = ImageDraw.Draw(mask)
                shape.rounded_rectangle([0,0,ICON,ICON], radius=16, fill=255)
                icon.putalpha(mask)

                canvas.paste(icon, (x, y), icon)

                # Borders
                if c["rarity"] == 5:
                    color = "#ffd86b"
                else:
                    color = "#b666ff"

                draw.rounded_rectangle(
                    [x, y, x+ICON, y+ICON],
                    radius=16,
                    outline=color,
                    width=4
                )

                # Eidolon
                if c["id"] in owned:
                    e = owned[c["id"]]
                    draw.rectangle([x, y+ICON-22, x+32, y+ICON], fill=(0,0,0,180))
                    draw.text((x+6, y+ICON-18), f"E{e}", fill="white", font=font)

        # Drop shadow effect around full roster
        shadow = canvas.filter(ImageFilter.GaussianBlur(8))
        final_img = Image.new("RGBA", (width+32, height+32), (0,0,0,0))
        final_img.paste(shadow, (16,16))
        final_img.paste(canvas, (0,0), canvas)

        # -------------------------------------------------------
        # 5) Send
        # -------------------------------------------------------
        buffer = io.BytesIO()
        final_img.save(buffer, "PNG")
        buffer.seek(0)

        await interaction.followup.send(
            content=f"**Roster for <@{discord_id}>**",
            file=discord.File(buffer, filename="roster.png")
        )

async def setup(bot):
    await bot.add_cog(Roster(bot))
