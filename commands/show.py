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

    @app_commands.command(name="topwinrate",description="Would you like to glimpse the highest winning threads…?")
    @app_commands.guilds(GUILD_ID)
    async def topwinrate(self, interaction: Interaction):
        await interaction.response.defer()
        try:
            conn = psycopg2.connect(POSTGRES_URL)
            cur = conn.cursor()

            # Fetch top 10 players with at least 5 games
            cur.execute("""
                SELECT
                    discord_id,
                    win_rate,
                    games_played,
                    (win_rate * (1 - EXP(-games_played / 10.0))) AS weighted_score
                FROM players
                WHERE games_played >= 5
                ORDER BY weighted_score DESC
                LIMIT 10;
            """)
            top_players = cur.fetchall()

            cur.close()
            conn.close()

            if not top_players:
                await interaction.followup.send("Oh… no one has played enough matches to tie their thread to fate just yet.")
                return

            embed = discord.Embed(
                title="Top 10 Win Rates",
                description="More games? More fate. Here's the fairest ranking by threads of victory:",
                color=discord.Color.purple()
            )

            for i, (discord_id, win_rate, games_played, weighted_score) in enumerate(top_players, start=1):
                win_pct = round(win_rate * 100, 2)
                try:
                    user = await self.bot.fetch_user(discord_id)
                    name = user.display_name if hasattr(user, "display_name") else user.name
                except Exception:
                    name = f"<@{discord_id}>"
                embed.add_field(
                    name=f"{i}. {name}",
                    value=(
                        f"Win Rate: `{win_pct}%` over `{games_played}` trials\n"
                        f"Thread Strength: `{weighted_score:.3f}`"
                    ),
                    inline=False
                )

            embed.set_footer(text="Handled with care by Kyasutorisu")
            await interaction.followup.send(embed=embed)

        except Exception as e:
            print(f"Error fetching win rate leaderboard: {e}")
            await interaction.followup.send("Something went wrong while I searched the stars for win rates…", ephemeral=True)

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
                "SELECT uid, mirror_id, points FROM players WHERE uid = ANY($1::text[])",
                ids
            )
        data = {row['uid']: row for row in records}

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
                    name=f"🧵 {member.display_name}",
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