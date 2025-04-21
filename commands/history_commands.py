import discord
import os
from discord import app_commands, ui
from discord.ext import commands
from datetime import datetime
from utils.db_utils import load_match_history
from dotenv import load_dotenv

load_dotenv()

GUILD_ID = int(os.getenv("DISCORD_GUILD_ID"))

class HistoryCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="match-history", description="Let me gently reveal the echoes of a player's past battles.")
    @app_commands.guilds(GUILD_ID)
    @app_commands.describe(player="Player to view history for (leave empty for your own)")
    async def match_history(self, interaction: discord.Interaction, player: discord.Member = None):
        await interaction.response.defer()
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
            await interaction.followup.send(
                f"Ah… I looked, but I couldn't find any match history for {target_user.display_name}.\nMaybe their thread has yet to be woven?",
                ephemeral=False
            )
            return

        user_matches.sort(
            key=lambda x: datetime.strptime(x.get('date', '01/01/1900'), "%d/%m/%Y"),
            reverse=True
        )
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

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user.id:
            await interaction.response.send_message(
                "Only the original thread-weaver may flip through these echoes...",
                ephemeral=True
            )
            return False
        return True

    

    async def send_initial_message(self, interaction):
        embed = self.create_embed()
        await interaction.followup.send(embed=embed, view=self)
        self.message = await interaction.original_response()

    def create_embed(self):
        match = self.matches[self.current_index]
        embed = discord.Embed(
            title=f"Threads of Battle for {self.user.display_name}",
            description=f"This memory was woven on: {match['date']}",
            color=discord.Color.blue()
        )
        
        # Blue Team
        blue_players = "\n".join(
            f"{p['name']} ({p['cycles']}c)" 
            for p in match['blue_team']
        )
        embed.add_field(
            name=f"Blue Team ({match['blue_score']} Cycles)",
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
            name=f"Red Team ({match['red_score']} Cycles)",
            value=(
            f"{red_players}\n"
            f"▸ Cycle Penalty: +{match['red_penalty']}"
        ),
            inline=False
        )

        # Add result at the bottom
        winner = match.get("winner", "")
        if winner == "blue":
            result = "🔵 *The Blue Thread shimmered brighter that day...*"
        elif winner == "red":
            result = "🔴 *The Red Thread held firm in fate’s embrace.*"
        else:
            result = "⚪ *Neither thread frayed — a balance untouched.*"
        embed.add_field(name="Result", value=result, inline=False)
        
        # Footer with match counter
        embed.set_footer(text=f"Memory {self.current_index + 1} of {len(self.matches)} — preserved with care")
        return embed

    @ui.button(emoji="⬅️", style=discord.ButtonStyle.gray)
    async def previous_match(self, interaction, button):
        try:
            # Proceed to the previous match
            self.current_index = max(0, self.current_index - 1)
            embed = self.create_embed()

            # Check if the interaction is still valid
            if interaction.response.is_done():
                await interaction.followup.send(embed=embed, view=self)
            else:
                await interaction.response.edit_message(embed=embed, view=self)

        except discord.errors.InteractionResponded:
            # Interaction already responded to, use followup instead
            await interaction.followup.send(embed=embed, view=self)

        except discord.errors.NotFound:
            # If interaction has expired or not found, handle the case
            await interaction.followup.send("The moment has slipped through time’s fingers... I can no longer alter that message.\nShall we begin anew?", ephemeral=True)


    @ui.button(emoji="➡️", style=discord.ButtonStyle.gray)
    async def next_match(self, interaction, button):
        try:
            # Proceed to the next match
            self.current_index = min(len(self.matches) - 1, self.current_index + 1)
            embed = self.create_embed()

            # Check if the interaction is still valid
            if interaction.response.is_done():
                await interaction.followup.send(embed=embed, view=self)
            else:
                await interaction.response.edit_message(embed=embed, view=self)

        except discord.errors.InteractionResponded:
            # Interaction already responded to, use followup instead
            await interaction.followup.send(embed=embed, view=self)

        except discord.errors.NotFound:
            # If interaction has expired or not found, handle the case
            await interaction.followup.send("The moment has slipped through time’s fingers... I can no longer alter that message.\nShall we begin anew?", ephemeral=True)


        async def on_timeout(self):
            for item in self.children:
                item.disabled = True
            await self.message.edit(view=self)
            try:
                await self.message.channel.send(
                    f"{self.user.mention}, the thread has faded... Use `/match-history` again to revisit.",
                    delete_after=10
                )
            except Exception:
                pass
