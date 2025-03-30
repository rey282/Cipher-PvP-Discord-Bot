import discord
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
                SELECT discord_id, win_rate, games_played
                FROM players
                WHERE games_played >= 5
                ORDER BY win_rate DESC
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
                description="The most victorious threads I've seen so far:",
                color=discord.Color.gold()
            )

            for i, (discord_id, win_rate, games_played) in enumerate(top_players, start=1):
                win_pct = round(win_rate * 100, 2)
                embed.add_field(
                    name=f"{i}. <@{discord_id}>",
                    value=f"Win Rate: `{win_pct}%`\nGames Played: `{games_played}`",
                    inline=False
                )

            embed.set_footer(text="Handled with care by Kyasutorisu")
            await interaction.followup.send(embed=embed)

        except Exception as e:
            print(f"Error fetching win rate leaderboard: {e}")
            await interaction.followup.send("Something went wrong while I searched the stars for win rates…", ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(TopWinRate(bot))