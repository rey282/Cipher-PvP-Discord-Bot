import discord
import random
import os
from discord.ext import commands
from discord import app_commands
from discord import Interaction
from utils.db_utils import load_elo_data, save_elo_data
from utils.rank_utils import get_rank
from dotenv import load_dotenv

load_dotenv()

GUILD_ID = int(os.getenv("DISCORD_GUILD_ID"))

class RegisterPlayerModal(discord.ui.Modal, title="Register or Update Profile"):
    uid = discord.ui.TextInput(label="UID", required=False, placeholder="9-digit UID")
    mirror_id = discord.ui.TextInput(label="Mirror ID", required=False, placeholder="Mirror ID")
    points = discord.ui.TextInput(label="Total Cost", required=False, placeholder="Mirror Points")

    async def on_submit(self, interaction: Interaction):
        elo_data = load_elo_data()
        player_id = str(interaction.user.id)

        uid_input = self.uid.value.strip()
        mirror_id_input = self.mirror_id.value.strip()
        points_input = self.points.value.strip()

        # Validate UID format if provided
        if uid_input and (not uid_input.isdigit() or len(uid_input) != 9):
            await interaction.response.send_message("❌ UID must be 9 numeric characters!", ephemeral=True)
            return

        # Convert points
        try:
            points = int(points_input) if points_input else 0
        except ValueError:
            await interaction.response.send_message("❌ Total cost must be a valid number.", ephemeral=True)
            return

        # Case 1: Existing player
        if player_id in elo_data:
            player_data = elo_data[player_id]
            if uid_input:
                player_data["uid"] = uid_input
            if mirror_id_input:
                player_data["mirror_id"] = mirror_id_input
            if points_input:
                player_data["points"] = points
            action = "updated"
        # Case 2: New registration
        else:
            if not uid_input:
                await interaction.response.send_message("❌ UID is required for first-time registration!", ephemeral=True)
                return

            elo_data[player_id] = {
                "uid": uid_input,
                "mirror_id": mirror_id_input,
                "points": points,
                "elo": 200,
                "win_rate": 0.0,
                "games_played": 0,
                "discord_name": interaction.user.display_name
            }
            action = "registered"

        save_elo_data(elo_data)

        # Response message
        response = f"✅ Successfully {action} your profile!\n"
        if uid_input:
            response += f"▸ UID: `{uid_input}`\n"
        if mirror_id_input:
            response += f"▸ Mirror ID: `{mirror_id_input}`\n"
        response += f"▸ Points: `{elo_data[player_id].get('points', 0)}`"
        if action == "registered":
            response += f"\n▸ Starting ELO: `200`"

        await interaction.response.send_message(response, ephemeral=True)


class MatchmakingCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="matchmaking", description="Randomize a 2v2")
    @app_commands.guilds(GUILD_ID)
    @app_commands.describe(
        player1="First player",
        player2="Second player",
        player3="Third player",
        player4="Fourth player"
    )
    async def matchmaking(self, interaction: Interaction, player1: discord.Member, player2: discord.Member, player3: discord.Member, player4: discord.Member):
        # Validate unique players
        players = [player1, player2, player3, player4]
        if len(set(players)) != 4:
            await interaction.response.send_message("❌ All players must be unique!", ephemeral=True)
            return

        # Shuffle and split teams
        random.shuffle(players)
        team1, team2 = players[:2], players[2:]

        embed = discord.Embed(title="Randomized Teams", color=discord.Color.blue())
        embed.add_field(name="Team 1", value=f"{team1[0].mention} & {team1[1].mention}", inline=False)
        embed.add_field(name="Team 2", value=f"{team2[0].mention} & {team2[1].mention}", inline=False)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="register", description="Register or update your player data")
    @app_commands.guilds(GUILD_ID)
    async def register(self, interaction: Interaction):
        await interaction.response.send_modal(RegisterPlayerModal())


    @app_commands.command(name="playercard", description="Player's Profile")
    @app_commands.guilds(GUILD_ID)
    async def profile(self, interaction: Interaction, user: discord.Member = None):
        await interaction.response.defer()
        user = user or interaction.user
        elo_data = load_elo_data()
        player_id = str(user.id)

        # Get player data with all required fields, providing defaults if missing
        player_data = elo_data.get(player_id, {})
        
        # Set defaults for all possible fields
        elo = player_data.get("elo", 200)
        win_rate = player_data.get("win_rate", 0.0)
        games_played = player_data.get("games_played", 0)
        uid = player_data.get("uid", "Not Registered")
        mirror_id = player_data.get("mirror_id", "Not Set")
        points = player_data.get("points", 0)

        # Rank based on ELO + leaderboard
        rank = get_rank(elo_score=elo, player_id=player_id, elo_data=elo_data)
        
        # Create embed with new layout
        embed = discord.Embed(
            title=f"{user.display_name}'s Profile",
            color=user.color
        )
        embed.set_thumbnail(url=user.display_avatar.url)

        # Main rating field
        embed.add_field(
            name="Rating",
            value=f"{elo:.0f}",
            inline=False
        )

        # Combined Win Rate and Games Played
        embed.add_field(
            name="Stats",
            value=f"Win Rate: {win_rate * 100:.1f}%\n"
                f"Games Played: {games_played}",
            inline=False
        )

        # Expanded Details section with UID, Mirror ID, Points and Rank
        embed.add_field(
            name="Details",
            value=f"UID: {uid}\n"
                f"Mirror ID: {mirror_id}\n"
                f"Total Cost: {points}\n"
                f"Rank: {rank}",
            inline=False
        )

        await interaction.followup.send(embed=embed)

    @app_commands.command(name="prebans", description="Calculate pre-bans with explicit team assignments")
    @app_commands.guilds(GUILD_ID)
    @app_commands.describe(
        team1_player1="First player (Team 1)",
        team1_player2="Second player (Team 1, optional)",
        team2_player1="First player (Team 2)",
        team2_player2="Second player (Team 2, optional)"
    )
    async def prebans(
        self,
        interaction: Interaction,
        team1_player1: discord.Member,
        team2_player1: discord.Member,
        team1_player2: discord.Member = None,
        team2_player2: discord.Member = None
    ):
        try:
            # Load ELO data at the start of the command
            elo_data = load_elo_data()
            # Team processing (now unambiguous)
            team1 = [p for p in [team1_player1, team1_player2] if p is not None]
            team2 = [p for p in [team2_player1, team2_player2] if p is not None]
            # Determine match type
            match_type = f"{len(team1)}v{len(team2)}"
            
            # Get points for all players
            def get_points(player):
                return elo_data.get(str(player.id), {}).get("points", 0)
            
            # Calculate team averages
            if match_type == "1v1":
                points1 = get_points(team1[0])
                points2 = get_points(team2[0])
            elif match_type == "1v2":
                points1 = get_points(team1[0])
                team2_avg = sum(get_points(p) for p in team2) / len(team2)
                points2 = team2_avg * 1.2
            elif match_type == "2v1":
                points2 = get_points(team2[0])
                team1_avg = sum(get_points(p) for p in team1) / len(team1)
                points1 = team1_avg * 1.2
            else:  # 2v2
                points1 = sum(get_points(p) for p in team1) / len(team1)
                points2 = sum(get_points(p) for p in team2) / len(team2)
            
            # Define format_team function
            def format_team(team):
                return ", ".join(p.display_name for p in team)

             # Determine point difference
            point_diff = abs(points1 - points2)
            lower_points_team = team2 if points1 > points2 else team1

            # Check if point difference is less than 100
            if point_diff < 100:
                embed = discord.Embed(
                    title=f"Pre-Bans Calculation for {match_type}",
                    color=discord.Color.blue()
                )
                embed.add_field(
                    name="Teams",
                    value=f"{format_team(team1)} (Avg: {points1:.0f} pts)\n"
                        f"{format_team(team2)} (Avg: {points2:.0f} pts)",
                    inline=False
                )
                embed.add_field(
                    name="Result",
                    value="It's a tie! No pre-bans for either team."+ f"\n\n*Total point difference: {point_diff:.0f}*",
                    inline=False
                )
                await interaction.response.send_message(embed=embed)
                return  
            
            # Calculate bans
            if point_diff >= 800:
                # First 800 points: 3 regular + 5 joker bans
                # Beyond 800: additional joker bans (1 per 200pts)
                regular_bans = 3
                joker_bans = 5 + (point_diff - 800) // 200
            elif point_diff >= 300:
                # First 300 points: 3 regular bans
                # Next 500 points: joker bans (1 per 100pts, max 5)
                regular_bans = 3
                joker_bans = min(5, (point_diff - 300) // 100)
            else:
                # Below 300: regular bans only (1 per 100pts, max 3)
                regular_bans = min(3, point_diff // 100)
                joker_bans = 0

            # Create embed
            embed = discord.Embed(
                title=f"Pre-Bans Calculation for {match_type}",
                color=discord.Color.blue()
            )
            
            # Add team info
            
            embed.add_field(
                name="Teams",
                value=f" {format_team(team1)} (Avg: {points1:.0f} pts)\n"
                    f" {format_team(team2)} (Avg: {points2:.0f} pts)",
                inline=False
            )
            
            # Add bans info
            ban_info = []
            if regular_bans > 0:
                ban_info.append(f"▸ {regular_bans} regular ban(s) (100pts each)")
            if joker_bans > 0:
                if point_diff >= 800:
                    ban_info.append(f"▸ 5 joker bans (100pts each) + {joker_bans-5} extra joker ban(s) (200pts each)")
                else:
                    ban_info.append(f"▸ {joker_bans} joker ban(s) (100pts each)")

            embed.add_field(
                name=f"{format_team(lower_points_team)} receives pre-bans",
                value="\n".join(ban_info) + f"\n\n*Total point difference: {point_diff:.0f}*",
                inline=False
            )
            
            await interaction.response.send_message(embed=embed)

        except Exception as e:
            await interaction.response.send_message(
                f"❌ Error calculating pre-bans: {str(e)}",
                ephemeral=True
            )
            raise

async def setup(bot):
    await bot.add_cog(MatchmakingCommands(bot))