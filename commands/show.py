import discord
import asyncpg
import os
import psycopg2
from discord.ext import commands
from discord import app_commands, Interaction
from dotenv import load_dotenv

load_dotenv()
GUILD_ID = int(os.getenv("DISCORD_GUILD_ID"))
POSTGRES_URL = os.getenv("DATABASE_URL")

class TopWinRate(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
    async def get_db_pool(self):
        if not hasattr(self.bot, "db_pool"):
            self.bot.db_pool = await asyncpg.create_pool(POSTGRES_URL)
        return self.bot.db_pool

    @app_commands.command(name="show-cipher", description="Gently unveiling the Mirror ID and Cipher Points for up to 4 players, woven by fate...")
    @app_commands.guilds(GUILD_ID)
    @app_commands.describe(
        player1="First player",
        player2="Second player",
        player3="Third player",
        player4="Fourth player"
    )
    async def show_cipher(
        self,
        interaction: discord.Interaction,
        player1: discord.Member,
        player2: discord.Member = None,
        player3: discord.Member = None,
        player4: discord.Member = None,
    ):
        await interaction.response.defer()

        players = [p for p in [player1, player2, player3, player4] if p]
        ids = [str(p.id) for p in players]

        pool = await self.get_db_pool()
        async with pool.acquire() as conn:
            records = await conn.fetch(
                "SELECT discord_id, mirror_id, points FROM players WHERE discord_id = ANY($1::text[])",
                ids
            )
        data = {row['discord_id']: row for row in records}

        embed = discord.Embed(
            title="Threads of Fate: Cipher Report",
            description="Peeking into the threads of fate… Let's see what secrets lie beneath~",
            color=discord.Color.dark_purple()
        )
        embed.set_footer(text="Handled with care by Kyasutorisu")

        for member in players:
            record = data.get(str(member.id))
            if record:
                embed.add_field(
                    name=f"{member.display_name}",
                    value=(
                        f"**Cipher Points:** `{record['points']}`\n"
                        f"**Mirror ID:** `{record['mirror_id']}`"
                    ),
                    inline=False
                )
            else:
                embed.add_field(
                    name=f"🧵 {member.display_name}",
                    value="`No thread found in the Archive.",
                    inline=False
                )

        await interaction.followup.send(embed=embed)

async def setup(bot: commands.Bot):
    await bot.add_cog(TopWinRate(bot))