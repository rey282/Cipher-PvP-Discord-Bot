import discord
import os
import asyncpg
import psycopg2
from discord import app_commands, Interaction
from discord.ext import commands
from datetime import datetime
from typing import Optional
from typing import List
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
GUILD_ID = int(os.getenv("DISCORD_GUILD_ID"))

class Tournament(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def get_db_pool(self):
        if not hasattr(self.bot, "db_pool"):
            self.bot.db_pool = await asyncpg.create_pool(DATABASE_URL)
        return self.bot.db_pool


    # --- Admin Command to Submit Tournament ---
    @app_commands.command(name="submit-tournament", description="Submit a finished tournament to the archive.")
    @app_commands.guilds(GUILD_ID)
    @app_commands.describe(
        name="The name of the tournament",
        winner_1="First champion",
        winner_2="Second champion (optional)",
        winner_3="Third champion (optional)",
        winner_4="Fourth champion (optional)",
        winner_5="Fifth champion (optional)",
    )
    async def submit_tournament(
        self,
        interaction: Interaction,
        name: str,
        winner_1: discord.Member,
        winner_2: Optional[discord.Member] = None,
        winner_3: Optional[discord.Member] = None,
        winner_4: Optional[discord.Member] = None,
        winner_5: Optional[discord.Member] = None,
    ):
        required_role = "Organizer"

        if not interaction.user.guild_permissions.administrator and not any(role.name == required_role for role in interaction.user.roles):
            await interaction.response.send_message(
                "I-I’m afraid only tournament organizers can submit the results... Please make sure you have the right permissions to proceed!",
                ephemeral=True
            )
            return

        winners = [winner_1]
        if winner_2: winners.append(winner_2)
        if winner_3: winners.append(winner_3)
        if winner_4: winners.append(winner_4)
        if winner_5: winners.append(winner_5)

        winner_string = ", ".join(w.display_name for w in winners)

        pool = await self.get_db_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO tournaments (name, winner, timestamp) VALUES ($1, $2, $3)",
                name,
                winner_string,
                datetime.now()
            )

        await interaction.response.send_message(f"**{name}** has been recorded!\nWinners: {winner_string}")

    # --- Public Command to View Tournament History ---
    @app_commands.command(name="tournament-winner", description="view the glorious archive of tournament champions...")
    @app_commands.guilds(GUILD_ID)
    async def tournament_winner(self, interaction: Interaction):
        await self.send_page(interaction, page=1)

    async def send_page(self, interaction, page: int):
        pool = await self.get_db_pool()
        async with pool.acquire() as conn:
            records = await conn.fetch("SELECT * FROM tournaments ORDER BY timestamp DESC")

        if not records:
            await interaction.response.send_message(
                "The tournament archive is currently empty...\nNo brave champions have yet etched their names into history.",
                ephemeral=False
            )
            return
        
        per_page = 10
        total_pages = (len(records) + per_page - 1) // per_page
        start = (page - 1) * per_page
        end = start + per_page
        page_records = records[start:end]

        embed = discord.Embed(
            title="📜 Tournament Archive",
            color=discord.Color.gold(),
            description="\n".join(
                f"**{start + i + 1}. {r['name']}** — 🏆 {', '.join(r['winner'].split(',')).strip()} *(on {r['timestamp'].strftime('%d/%m/%Y')})*"
                for i, r in enumerate(page_records)
            )
        )
        embed.set_footer(text=f"Page {page} of {total_pages} — preserved with care")

        view = TournamentPagination(self, page, total_pages) if total_pages > 1 else None

        if view:
            await interaction.response.send_message(embed=embed, view=view)
        else:
            await interaction.response.send_message(embed=embed)

class TournamentPagination(discord.ui.View):
    def __init__(self, cog: Tournament, current_page: int, total_pages: int):
        super().__init__(timeout=60)
        self.cog = cog
        self.current_page = current_page
        self.total_pages = total_pages

    @discord.ui.button(label="⬅️", style=discord.ButtonStyle.gray)
    async def prev_page(self, interaction: Interaction, button: discord.ui.Button):
        if self.current_page > 1:
            await interaction.response.defer()
            await self.cog.send_page(interaction, self.current_page - 1)
        else:
            await interaction.response.defer()

    @discord.ui.button(label="➡️", style=discord.ButtonStyle.gray)
    async def next_page(self, interaction: Interaction, button: discord.ui.Button):
        if self.current_page < self.total_pages:
            await interaction.response.defer()
            await self.cog.send_page(interaction, self.current_page + 1)
        else:
            await interaction.response.defer()

# Setup
async def setup(bot):
    await bot.add_cog(Tournament(bot))
