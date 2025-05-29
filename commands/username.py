import discord
from discord import app_commands
from discord.ext import commands
import asyncpg
import os
from dotenv import load_dotenv

load_dotenv()
GUILD_ID = int(os.getenv("DISCORD_GUILD_ID"))
class MemberSync(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.pool = None
        self.guild_id = int(os.getenv("DISCORD_GUILD_ID"))

    async def cog_load(self):
        self.pool = await asyncpg.create_pool(dsn=os.getenv("DATABASE_URL"))

    @app_commands.command(name="syncallmembers", description="Sync all guild members to the database")
    @app_commands.guilds(GUILD_ID)
    async def syncallmembers(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        
        guild = self.bot.get_guild(self.guild_id)
        if not guild:
            await interaction.followup.send("I am not in the specified guild.")
            return

        await guild.chunk()
        
        count = 0
        async with self.pool.acquire() as conn:
            for member in guild.members:
                discord_id = str(member.id)
                username = str(member)
                await conn.execute("""
                    INSERT INTO discord_usernames (discord_id, username)
                    VALUES ($1, $2)
                    ON CONFLICT (discord_id) DO UPDATE SET username = EXCLUDED.username
                """, discord_id, username)
                count += 1

        await interaction.followup.send(f"Synced {count} members.")

async def setup(bot):
    await bot.add_cog(MemberSync(bot))
