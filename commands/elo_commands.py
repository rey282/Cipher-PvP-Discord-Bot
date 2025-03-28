import discord
from discord.ext import commands
from discord import ui
from discord import app_commands
from discord import Interaction
from discord import Object
from utils.db_utils import load_elo_data, save_elo_data
from utils.views import UpdateEloView, TiebreakerView
from dotenv import load_dotenv

load_dotenv()

GUILD_ID = int(os.getenv("DISCORD_GUILD_ID"))

class EloCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="submit-match", description="Update ELO")
    @app_commands.guilds(GUILD_ID)  # Associate the command with a specific guild
    @app_commands.describe(
        blue_player_1="First player",
        blue_player_2="Second player",
        red_player_1="Third player",
        red_player_2="Fourth player",
        blue_player_1_cycle="Cycle score of Blue Player 1 (0-15)",
        blue_player_2_cycle="Cycle score of Blue Player 2 (0-15)",
        red_player_1_cycle="Cycle score of Red Player 1 (0-15)",
        red_player_2_cycle="Cycle score of Red Player 2 (0-15)",
        blue_cycle_penalty="Cycle penalty for Blue Team",
        red_cycle_penalty="Cycle penalty for Red Team"
    )

    async def update_elo(self, interaction: Interaction, blue_player_1: discord.Member, blue_player_2: discord.Member, red_player_1: discord.Member, red_player_2: discord.Member, blue_player_1_cycle: int, blue_player_2_cycle: int, red_player_1_cycle: int, red_player_2_cycle: int, blue_cycle_penalty: int, red_cycle_penalty: int):
        try:
            # Validate no duplicate players
            players = [blue_player_1, blue_player_2, red_player_1, red_player_2]
            if (blue_player_1 in [red_player_1, red_player_2]) or (blue_player_2 in [red_player_1, red_player_2]):
                await interaction.response.send_message("What are we? Naruto from Wish?", ephemeral=False)
                return
            
            # Validate scores (0-15)
            blue_scores = [blue_player_1_cycle, blue_player_2_cycle]
            red_scores = [red_player_1_cycle, red_player_2_cycle]
            if any(score < 0 or score > 15 for score in blue_scores + red_scores):
                await interaction.response.send_message("Cmon, you are not that stupid", ephemeral=False)
                return

            # Validate cycle penalties (non-negative)
            if blue_cycle_penalty < 0 or red_cycle_penalty < 0:
                await interaction.response.send_message("Why would you put a negative cycle penalty", ephemeral=False)
                return

            # Calculate total scores for each team (excluding penalties)
            blue_total_score = sum(blue_scores)
            red_total_score = sum(red_scores)

            # Create an embed to display the results
            embed = discord.Embed(
                title="Match Results",
                color=discord.Color.blue() if blue_total_score < red_total_score else discord.Color.red()
            )

            # Add Blue Team field
            embed.add_field(
                name="Blue Team",
                value=f"{blue_player_1.display_name} ({blue_player_1_cycle}c) & {blue_player_2.display_name} ({blue_player_2_cycle}c)",
                inline=False
            )

            # Add Red Team field
            embed.add_field(
                name="Red Team",
                value=f"{red_player_1.display_name} ({red_player_1_cycle}c) & {red_player_2.display_name} ({red_player_2_cycle}c)",
                inline=False
            )   

            # Add total scores and cycle penalties
            embed.add_field(
                name="Total Scores",
                value=f"Blue Team: {blue_total_score} Points (+{blue_cycle_penalty} Penalty)\nRed Team: {red_total_score} Points (+{red_cycle_penalty} Penalty)",
                inline=False
            )

            # Add winner (if not a tie)
            if blue_total_score < red_total_score:
                embed.add_field(name="Winner", value="Blue Team", inline=False)
            elif red_total_score < blue_total_score:
                embed.add_field(name="Winner", value="Red Team", inline=False)
            else:
                embed.add_field(name="Winner", value="It's a tie!", inline=False)

            # Create view with buttons
            view = UpdateEloView(
                blue_team=[blue_player_1, blue_player_2],
                red_team=[red_player_1, red_player_2],
                blue_scores=blue_scores,
                red_scores=red_scores,
                blue_cycle_penalty=blue_cycle_penalty,
                red_cycle_penalty=red_cycle_penalty
            )

            # Handle duplicate mentions
            mentioned_users = set()  # Use a set to avoid duplicate mentions
            mentioned_users.add(blue_player_1)
            if blue_player_2 != blue_player_1:  # Only add if it's a different user
                mentioned_users.add(blue_player_2)
            mentioned_users.add(red_player_1)
            if red_player_2 != red_player_1:  # Only add if it's a different user
                mentioned_users.add(red_player_2)

            # Create the mention string
            user_mentions = " ".join(user.mention for user in mentioned_users)
            message_content = f"{user_mentions}\nDoes this look correct?"

            # Send the embed with buttons
            await interaction.response.send_message(content=message_content, embed=embed, view=view)

        except Exception as e:
            print(f"Error in update-elo command: {e}")
            await interaction.response.send_message("An error occurred while processing the command.", ephemeral=True)

async def setup(bot):
    await bot.add_cog(EloCommands(bot))