import discord
from discord import app_commands, Interaction
from discord.ext import commands
from datetime import datetime
from typing import Optional
from typing import List

class Tournament(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # --- Admin Command to Submit Tournament ---
    @app_commands.command(name="submit-tournament", description="Submit a finished tournament to the archive.")
    @app_commands.describe(
        name="Name of the tournament",
        winners="The champion(s) of this tournament"
    )
    async def submit_tournament(
        self,
        interaction: Interaction,
        name: str,
        winners: List[discord.Member] 
    ):
        required_role = "Organizer"

        # Check permission
        if not interaction.user.guild_permissions.administrator and not any(role.name == required_role for role in interaction.user.roles):
            await interaction.response.send_message(
                "I-I’m afraid only tournament organizers can submit the results... Please make sure you have the right permissions to proceed!",
                ephemeral=True
            )
            return

        # Build winner string from mentions or display names
        winner_string = ", ".join([winner.display_name for winner in winners])

        # Insert into database
        await self.bot.db.execute(
            "INSERT INTO tournaments (name, winner, timestamp) VALUES ($1, $2, $3)",
            name,
            winner_string,
            datetime.now()
        )

        await interaction.response.send_message(
            f"📜 Tournament **{name}** with winner(s) **{winner_string}** has been recorded in the archive!",
            ephemeral=False
        )

    # --- Public Command to View Tournament History ---
    @app_commands.command(name="tournament-winner", description="view the glorious archive of tournament champions...")
    async def tournament_winner(self, interaction: Interaction):
        await self.send_page(interaction, page=1)

    async def send_page(self, interaction, page: int):
        async with self.bot.db_pool.acquire() as conn:
            records = await conn.fetch("SELECT * FROM tournament_winners ORDER BY timestamp DESC")
        
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

        view = None
        if total_pages > 1:
            view = TournamentPagination(self, page, total_pages)

        await interaction.response.send_message(embed=embed, view=view)

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
