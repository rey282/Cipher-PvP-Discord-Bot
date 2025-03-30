import discord
import os
from discord.ext import commands
from discord import app_commands, Interaction
from utils.elo_utils import load_elo_data
from dotenv import load_dotenv

load_dotenv()
GUILD_ID = int(os.getenv("DISCORD_GUILD_ID"))

class TopWinRate(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="topwinrate",description="Would you like to glimpse the highest winning threads…?")
    @app_commands.guilds(GUILD_ID)
    async def topwinrate(self, interaction: Interaction):
        await interaction.response.defer()
        elo_data = load_elo_data()

        # Filter players with at least 5 games
        qualified_players = [
            (pid, pdata) for pid, pdata in elo_data.items()
            if pdata.get("games_played", 0) >= 5
        ]

        if not qualified_players:
            await interaction.followup.send(
                "O-Oh… it seems no one has played enough matches for me to show the top win rates.",
                ephemeral=False
            )
            return

        # Sort by win rate
        sorted_players = sorted(
            qualified_players,
            key=lambda item: item[1].get("win_rate", 0.0),
            reverse=True
        )

        top_players = sorted_players[:10]

        embed = discord.Embed(
            title="Top 10 Win Rates",
            description="Here are the most victorious threads I’ve seen tied by fate...",
            color=discord.Color.gold()
        )

        for i, (pid, pdata) in enumerate(top_players, start=1):
            win_pct = pdata.get("win_rate", 0.0) * 100
            games = pdata.get("games_played", 0)
            discord_name = pdata.get("discord_name", f"<@{pid}>")

            embed.add_field(
                name=f"{i}. {discord_name}",
                value=f"Win Rate: `{win_pct:.1f}%` over `{games}` trials",
                inline=False
            )

        embed.set_footer(text="Handled with care by Kyasutorisu")
        await interaction.followup.send(embed=embed)

async def setup(bot: commands.Bot):
    await bot.add_cog(TopWinRate(bot))