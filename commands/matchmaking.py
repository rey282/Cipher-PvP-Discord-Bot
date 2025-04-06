import discord
import random
import os
import re
from discord.ext import commands
from discord import app_commands
from discord import Interaction
from utils.db_utils import load_elo_data, save_elo_data, initialize_player_data
from utils.rank_utils import get_rank
from dotenv import load_dotenv

load_dotenv()
GUILD_ID = int(os.getenv("DISCORD_GUILD_ID"))

ALLOWED_COLORS = {
    "red": 0xFF4C4C,
    "orange": 0xFFA500,
    "yellow": 0xFFFF66,
    "green": 0x66FF66,
    "blue": 0x66CCFF,
    "purple": 0xB19CD9,
    "pink": 0xFFB6C1,
    "white": 0xF8F8FF,
    "gray": 0xB0B0B0,
    "black": 0x1E1E1E,
    "brown": 0xA0522D,
    "cyan": 0x00FFFF,
    "magenta": 0xFF00FF,
}

class DescriptionModal(discord.ui.Modal, title="Rewrite Your Soul’s Thread"):
    description = discord.ui.TextInput(
        label="What gentle words describe your soul?",
        placeholder="You may leave this blank if you prefer silence…",
        max_length=43,
        style=discord.TextStyle.short,
        required=False
    )

    profile_color = discord.ui.TextInput(
        label="What gentle words describe your soul?",
        placeholder="Try pink, blue, or #FF69B4…",
        required=False,
        max_length=16,
        style=discord.TextStyle.short
    )

    def __init__(self, user_id):
        super().__init__()
        self.user_id = str(user_id)

    async def on_submit(self, interaction: discord.Interaction):
        desc = str(self.description).strip()
        color_input = str(self.profile_color).strip().lower()
        color_code = None
        update_desc = True

        # Basic link/URL validation (reject discord links, http, etc.)
        if desc and re.search(r"(https?:\/\/|discord\.gg|discordapp\.com|@|\.com|\.net|\.org)", desc, re.IGNORECASE):
            await interaction.response.send_message(
                "Oh… I must apologize… descriptions with links aren’t permitted. It’s for your safety…",
                ephemeral=True
            )
            return
        # Reset to default if user types 'none' or 'default'
        if desc.lower() == "none":
            desc = ""
        elif desc.lower() == "default":
            desc = "A glimpse into this soul’s gentle journey…"
        elif not desc:
            update_desc = False

        # Validate color
        if color_input:
            if color_input in ("none", "default"):
                color_code = 0xB197FC  # Castorice default
            elif color_input in ALLOWED_COLORS:
                color_code = ALLOWED_COLORS[color_input]
            elif re.fullmatch(r"#?[0-9a-f]{6}", color_input, re.IGNORECASE):
                color_code = int(color_input.replace("#", ""), 16)
            else:
                await interaction.response.send_message(
                    f"Ah… I didn’t quite understand that color. Please whisper one of these:\n"
                    f"> *{', '.join(ALLOWED_COLORS.keys())}*\n"
                    f"Or a hex code like `#FAB4C0`, or type `default` to reset.",
                    ephemeral=True
                )
                return

        elo_data = load_elo_data()

        if self.user_id not in elo_data:
            elo_data[self.user_id] = initialize_player_data(self.user_id)

        if update_desc:
            elo_data[self.user_id]["description"] = desc
            
        if color_code is not None:
            elo_data[self.user_id]["color"] = color_code

        save_elo_data(elo_data)

        await interaction.response.send_message(
            "Your soul’s thread has been gently woven, as if whispered by the loom itself.\nA new chapter begins in your gentle journey…", ephemeral=False
        )

class RegisterPlayerModal(discord.ui.Modal, title="Gently Update Your Presence"):
    uid = discord.ui.TextInput(label="UID", required=False, placeholder="9-digit UID")
    mirror_id = discord.ui.TextInput(label="Mirror ID", required=False, placeholder="Mirror ID")
    points = discord.ui.TextInput(label="Total Cost", required=False, placeholder="Mirror Points")

    async def on_submit(self, interaction: Interaction):
        await interaction.response.defer()
        elo_data = load_elo_data()
        player_id = str(interaction.user.id)

        uid_input = self.uid.value.strip()
        mirror_id_input = self.mirror_id.value.strip()
        points_input = self.points.value.strip()

        # Validate UID format if provided
        if uid_input and (not uid_input.isdigit() or len(uid_input) != 9):
            await interaction.followup.send("<:Unamurice:1349309283669377064> U-Um… I think the UID should be exactly 9 numbers... Could you double-check it for me?", ephemeral=True)
            return

        # Convert points
        try:
            points = int(points_input) if points_input else 0
        except ValueError:
            await interaction.followup.send("<:Unamurice:1349309283669377064> Oh no… I couldn’t understand the Mirror Points. It should be a number—would you mind trying again?", ephemeral=True)
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
                await interaction.followup.send("<:Unamurice:1349309283669377064> O-Oh… I’m sorry, but I need your UID to begin your registration. Without it, I can’t properly weave your thread…", ephemeral=True)
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
        embed = discord.Embed(
            title=f"Profile {action.capitalize()}",
            description="Your presence has been gently recorded…",
            color=discord.Color.purple()
        )

        if uid_input:
            embed.add_field(name="UID", value=f"`{uid_input}`", inline=False)

        if mirror_id_input:
            embed.add_field(name="Mirror ID", value=f"`{mirror_id_input}`", inline=False)

        embed.add_field(
            name="Total cost",
            value=f"`{elo_data[player_id].get('points', 0)}`",
            inline=False
        )

        if action == "registered":
            embed.add_field(name="Starting ELO", value="`200`", inline=False)

        embed.set_footer(text="Gently handled by Kyasutorisu")

        await interaction.followup.send(embed=embed, ephemeral=False)


class MatchmakingCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="matchmaking", description="Allow me to gently weave a random 2v2 from the threads you've offered...")
    @app_commands.guilds(GUILD_ID)
    @app_commands.describe(
        player1="First player",
        player2="Second player",
        player3="Third player",
        player4="Fourth player"
    )
    async def matchmaking(self, interaction: Interaction, player1: discord.Member, player2: discord.Member, player3: discord.Member, player4: discord.Member):
        await interaction.response.defer()
        # Validate unique players
        players = [player1, player2, player3, player4]
        if len(set(players)) != 4:
            await interaction.followup.send("O-Oh… it seems some players are listed more than once.\nAll souls must be unique for the threads to form properly…", ephemeral=False)
            return

        # Shuffle and split teams
        random.shuffle(players)
        team1, team2 = players[:2], players[2:]

        embed = discord.Embed(
            title="Threads Aligned",
            description="The threads have been gently woven… Here is your match.",
            color=discord.Color.blue()
        )
        embed.add_field(name="Team 1", value=f"{team1[0].mention} & {team1[1].mention}", inline=False)
        embed.add_field(name="Team 2", value=f"{team2[0].mention} & {team2[1].mention}", inline=False)
        embed.set_footer(text="Woven gently by Kyasutorisu")
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="register", description="Allow me to gently record or update your thread…")
    @app_commands.guilds(GUILD_ID)
    async def register(self, interaction: Interaction):
        await interaction.response.send_modal(RegisterPlayerModal())

    @app_commands.command(name="setplayercard", description="Gently adjust your soul’s card — a new whisper, a new color…")
    @app_commands.guilds(GUILD_ID)
    async def setdescription(self, interaction: discord.Interaction):
        modal = DescriptionModal(interaction.user.id)
        await interaction.response.send_modal(modal)

    @app_commands.command(name="playercard", description="Would you like to glimpse a player’s thread…? I can show you their profile.")
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
        color = elo_data.get(player_id, {}).get("color", 0xB197FC)
        description = elo_data.get(player_id, {}).get("description", "A glimpse into this soul’s gentle journey…")
        embed = discord.Embed(
            title=f"Thread of {user.display_name}",
            description = description,
            color=color
        )
        embed.set_thumbnail(url=user.display_avatar.url)

        # Main rating field
        embed.add_field(
            name="ELO Woven",
            value=f"{elo:.0f}",
            inline=False
        )

        # Combined Win Rate and Games Played
        embed.add_field(
            name="Stats",
            value=f"Win Rate: {win_rate * 100:.1f}%\n"
                f"Trials Faced: {games_played}",
            inline=False
        )

        # Expanded Details section with UID, Mirror ID, Points and Rank
        embed.add_field(
            name="Reflections",
            value=f"UID: {uid}\n"
                f"Total Cost: {points}\n"
                f"Rank: {rank}",
            inline=False
        )

        embed.set_footer(text=f"Mirror ID: {mirror_id}\nHandled with care by Kyasutorisu")

        custom_banners = {
        "371513247641370625": "https://tenor.com/view/vivian-vivian-zzz-gif-2645749298490638118",
        "663145925807702029": "https://tenor.com/view/feixiao-feixiao-honkai-star-rail-feixiao-hsr-feixiao-honkai-feixiao-ult-gif-9999284838159144419",
        }

        users_with_discord_banners = {
            "249042315736252417"  
        }

        if uid in custom_banners:
            embed.set_image(url=custom_banners[uid])
        elif player_id in users_with_discord_banners:
            try:
                full_user = await user.fetch()
                if full_user.banner:
                    embed.set_image(url=full_user.banner.url)
            except Exception as e:
                print(f"[Banner] Failed to fetch for {user}: {e}")
    
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="prebans", description="Allow me to gently calculate the pre-bans, with teams woven into their fates.")
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
        await interaction.response.defer() 
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
                    color=discord.Color.purple()
                )
                embed.add_field(
                    name="Teams Aligned",
                    value=f"{format_team(team1)} (Avg: {points1:.0f} pts)\n"
                        f"{format_team(team2)} (Avg: {points2:.0f} pts)",
                    inline=False
                )
                embed.add_field(
                    name="Result",
                    value="It seems the threads of fate have tied these teams... No pre-bans required for either side.\n\n"
                        f"*Total point difference: {point_diff:.0f}*",
                    inline=False
                )
                embed.set_footer(text="Handled with care by Kyasutorisu")
                await interaction.followup.send(embed=embed)
                return  
            
            # Calculate bans
            if point_diff >= 900:
                regular_bans = 3
                joker_bans = 5 + (point_diff - 900) // 200
            elif point_diff >= 300:
                regular_bans = 3
                joker_bans = min(5, (point_diff - 300) // 120)
            else:
                regular_bans = min(3, point_diff // 100)
                joker_bans = 0

            # Create embed
            embed = discord.Embed(
                title=f"Pre-Bans Calculation for {match_type}",
                color=discord.Color.purple()
            )
            
            # Add team info
            
            embed.add_field(
                name="Teams Alligned",
                value=f" {format_team(team1)} (Avg: {points1:.0f} pts)\n"
                    f" {format_team(team2)} (Avg: {points2:.0f} pts)",
                inline=False
            )
            
            # Add bans info
            ban_info = []
            if regular_bans > 0:
                ban_info.append(f"▸ {regular_bans} regular ban(s) (100pts each)")
            if joker_bans > 0:
                if point_diff >= 900:
                    ban_info.append(f"▸ 5 joker bans (120pts each) + {joker_bans-5} extra joker ban(s) (200pts each)")
                else:
                    ban_info.append(f"▸ {joker_bans} joker ban(s) (120pts each)")

            embed.add_field(
                name=f"{format_team(lower_points_team)} receives pre-bans",
                value="\n".join(ban_info) + f"\n\n*Total point difference: {point_diff:.0f}*",
                inline=False
            )
            embed.set_footer(text="Handled with care by Kyasutorisu")
            await interaction.followup.send(embed=embed)

        except Exception as e:
            await interaction.response.send_message(
                f"<:Poutorice:1349312201973829733> I’m truly sorry. Please allow me to try again. Here’s the error: {str(e)}",
                ephemeral=True
            )
            raise

async def setup(bot):
    await bot.add_cog(MatchmakingCommands(bot))