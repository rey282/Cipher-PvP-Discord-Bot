import discord
from discord import app_commands, ui
from discord.ext import commands
from datetime import datetime
from utils.db_utils import load_match_history

GUILD_ID = 1339490588386525266

class HistoryCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="match-history", description="View match history for a player")
    @app_commands.guilds(GUILD_ID)
    @app_commands.describe(player="Player to view history for (leave empty for your own)")
    async def match_history(self, interaction: discord.Interaction, player: discord.Member = None):
        target_user = player or interaction.user
        history = load_match_history()
        
        # Find matches where target_user participated
        user_matches = []
        for match in history:
            if not match or not isinstance(match, dict):
                continue  # skip None or invalid format

            for player_data in match.get('blue_team', []):
                if str(target_user.id) == player_data.get('id'):
                    user_matches.append(match)
                    break

            if match not in user_matches:
                for player_data in match.get('red_team', []):
                    if str(target_user.id) == player_data.get('id'):
                        user_matches.append(match)
                        break
        
        if not user_matches:
            await interaction.response.send_message(
                f"❌ No match history found for {target_user.display_name}!",
                ephemeral=False
            )
            return

        user_matches.sort(key=lambda x: x.get('date', ''), reverse=True)  # Sort by date (newest first)
        user_matches = user_matches[:15]  # Limit to 15 most recent matches
            
        view = MatchHistoryView(user_matches, target_user)
        await view.send_initial_message(interaction)
async def setup(bot):
    await bot.add_cog(HistoryCommands(bot))

class MatchHistoryView(ui.View):
    def __init__(self, matches, user):
        super().__init__(timeout=60)
        self.matches = matches
        self.user = user
        self.current_index = 0

    async def send_initial_message(self, interaction):
        embed = self.create_embed()
        await interaction.response.send_message(embed=embed, view=self)
        self.message = await interaction.original_response()

    def create_embed(self):
        match = self.matches[self.current_index]
        embed = discord.Embed(
            title=f"Match History for {self.user.display_name}",
            description=f"Match played on: {match['date']}",
            color=discord.Color.blue()
        )
        
        # Blue Team
        blue_players = "\n".join(
            f"{p['name']} ({p['cycles']}c)" 
            for p in match['blue_team']
        )
        embed.add_field(
            name=f"Blue Team ({match['blue_score']} Points)",
            value=(
            f"{blue_players}\n"
            f"▸ Cycle Penalty: +{match['blue_penalty']}"
        ),
            inline=False
        )
        
        # Red Team
        red_players = "\n".join(
            f"{p['name']} ({p['cycles']}c)" 
            for p in match['red_team']
        )
        embed.add_field(
            name=f"Red Team ({match['red_score']} Points)",
            value=(
            f"{red_players}\n"
            f"▸ Cycle Penalty: +{match['red_penalty']}"
        ),
            inline=False
        )
        
        # Footer with match counter
        embed.set_footer(text=f"Match {self.current_index + 1}/{len(self.matches)}")
        return embed

    @ui.button(emoji="⬅️", style=discord.ButtonStyle.gray)
    async def previous_match(self, interaction, button):
        self.current_index = max(0, self.current_index - 1)
        embed = self.create_embed()
        await interaction.response.edit_message(embed=embed, view=self)

    @ui.button(emoji="➡️", style=discord.ButtonStyle.gray)
    async def next_match(self, interaction, button):
        self.current_index = min(len(self.matches) - 1, self.current_index + 1)
        embed = self.create_embed()
        await interaction.response.edit_message(embed=embed, view=self)

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True
        await self.message.edit(view=self)