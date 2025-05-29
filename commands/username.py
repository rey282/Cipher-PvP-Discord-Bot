import discord
from discord.ext import commands
import asyncpg
import os

class MemberSync(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.pool = None
        self.guild_id = int(os.getenv("DISCORD_GUILD_ID"))

    async def cog_load(self):
        self.pool = await asyncpg.create_pool(dsn=os.getenv("DATABASE_URL"))

    @commands.command(name="syncallmembers")
    @commands.is_owner()
    async def sync_all_members(self, ctx):
        guild = self.bot.get_guild(self.guild_id)
        if guild is None:
            await ctx.send("I am not in the specified guild.")
            return

        await ctx.send("Starting member sync... This may take a while.")

        # Fetch all members from the guild cache or fetch from API if needed
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

        await ctx.send(f"Synced {count} members.")

async def setup(bot):
    await bot.add_cog(MemberSync(bot))
