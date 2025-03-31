import discord
import os
import json
import asyncio
from discord import app_commands, ui
from discord.ext import commands, tasks
from discord import Interaction
from discord.app_commands import AppCommandError
from utils.rank_utils import update_rank_role, get_rank
from utils.db_utils import load_elo_data, save_elo_data
from dotenv import load_dotenv

load_dotenv()

OWNER_ID = int(os.getenv("OWNER_ID"))
GUILD_ID = int(os.getenv("DISCORD_GUILD_ID"))

class ResetConfirmModal(discord.ui.Modal, title="Are you sure you wish to reset all ELO?"):
    confirmation = discord.ui.TextInput(
        label="Type ‘CONFIRM’ to reset ELO",
        placeholder="Type here...",
        required=True
    )

    def __init__(self, interaction: Interaction, elo_data):
        super().__init__()
        self.interaction = interaction
        self.elo_data = elo_data

    async def on_submit(self, interaction: Interaction):
        if self.confirmation.value.strip().upper() != "CONFIRM":
            await interaction.response.send_message("Oh… I’m sorry, but the confirmation wasn’t quite right. The reset has been gently cancelled… for now.", ephemeral=True)
            return
        
        try:
            # Reset data but keep uid, mirror_id, and points
            for player_id, player_data in self.elo_data.items():
                self.elo_data[player_id]["elo"] = 200
                self.elo_data[player_id]["win_rate"] = 0.0
                self.elo_data[player_id]["games_played"] = 0

            # Save changes
            save_elo_data(self.elo_data)

            await interaction.response.send_message("It’s done… All player stats have been reset. A new season begins — may your journey be filled with grace.")
        except Exception as e:
            await interaction.response.send_message(f"The thread frayed… I couldn’t reset the ratings: {str(e)}. Forgive me. We can try again… when fate allows.", ephemeral=True)



class AdminCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.leaderboard_message = None
        # Track last known ELO data for change detection
        self.last_elo_data = {}
        self.message_id_file = 'leaderboard_message_id.json'

    async def cog_load(self):
        """Ensure leaderboard loop starts when bot loads."""
        await self.before_update_leaderboard()
        self.update_leaderboard.start()
        await self.retrieve_leaderboard_message()

    def cog_unload(self):
        self.update_leaderboard.cancel()

    async def before_update_leaderboard(self):
        """Wait until bot is ready before starting the leaderboard loop."""
        await self.bot.wait_until_ready()

    async def retrieve_leaderboard_message(self):
        """Retrieve the leaderboard message by its ID if stored."""
        try:
            with open(self.message_id_file, 'r') as f:
                data = json.load(f)
                message_id = data.get('message_id')
                
            if message_id:
                channel = self.bot.get_channel(data.get('channel_id'))
                if channel:
                    self.leaderboard_message = await channel.fetch_message(message_id)
        except (FileNotFoundError, json.JSONDecodeError):
            # No saved message ID or file error, just continue without it
            pass
    
    @tasks.loop(seconds=15)
    async def update_leaderboard(self):
        """Check for changes in JSON file and update the leaderboard."""
        try:
            current_data = load_elo_data()
            
            if current_data != self.last_elo_data:
                self.last_elo_data = current_data  # Update cache
                
                if self.leaderboard_message:
                    embed = await self._create_leaderboard_embed()
                    await self.leaderboard_message.edit(embed=embed)
        except Exception as e:
            print(f"Leaderboard update error: {e}")

    @update_leaderboard.before_loop
    async def before_update_leaderboard(self):
        """Wait until the bot is ready before running the update loop."""
        await self.bot.wait_until_ready()

    async def _create_leaderboard_embed(self) -> discord.Embed:
        """Generate an embed showing the leaderboard."""
        elo_data = load_elo_data()
        top_players = sorted(
            elo_data.items(),
            key=lambda x: x[1].get("elo", 200),
            reverse=True
        )[:10]

        embed = discord.Embed(
            title="<:Nekorice:1349312200426127420> Threads of the Strongest <:Nekorice:1349312200426127420>",
            color=discord.Color.purple(),
            description="The top 10 players... whose threads shine brightest in this season’s weave."
        )

        for rank, (player_id, data) in enumerate(top_players, 1):
            try:
                player = await self.bot.fetch_user(int(player_id))
                name = player.display_name
            except:
                name = f"Unknown Soul ({player_id})"

            embed.add_field(
                name=f"{rank}. {name}",
                value=(
                    f"✦ ELO Woven: {int(data.get('elo', 200))}\n"
                    f"✦ Win Rate: {data.get('win_rate', 0.0) * 100:.1f}%\n"
                    f"✦ Trials Faced: {data.get('games_played', 0)}\n"
                    f"✦ Mirror Points: {data.get('points', 0)}"
                ),
                inline=False
            )
        embed.set_footer(text="The loom watches in silence... Your journey is far from over.")
            

        return embed

    @app_commands.command(name="start-leaderboard", description="Live Leaderboard")
    @app_commands.guilds(GUILD_ID)
    @app_commands.checks.has_permissions(administrator=True)
    if interaction.user.id != OWNER_ID:
        await interaction.response.send_message(
            "<:Unamurice:1349309283669377064> O-oh… I’m sorry, but only Haya may realign the threads of fate like this...\n"
            "*You’re not Haya, are you…?*",
            ephemeral=True
        )
        return
    async def start_leaderboard(self, interaction: discord.Interaction):
        await interaction.response.defer()
        try:
            embed = await self._create_leaderboard_embed()

            if self.leaderboard_message is None:
                # Send the leaderboard message and store it in leaderboard_message
                self.leaderboard_message = await interaction.followup.send(embed=embed)
                # Store the message ID and channel ID to retrieve it later
                with open(self.message_id_file, 'w') as f:
                    json.dump({
                        'message_id': self.leaderboard_message.id,
                        'channel_id': interaction.channel.id
                    }, f)
            else:
                # If the message already exists, just update it
                await self.leaderboard_message.edit(embed=embed)

        except Exception as e:
            await interaction.response.send_message(
                f"❌ Failed to create leaderboard: {str(e)}",
                ephemeral=True
            )

    @app_commands.command(name="change-rating", description="Gently adjust a player's ELO rating, weaving their journey with care.")
    @app_commands.guilds(GUILD_ID)
    @app_commands.describe(
        player="Player to adjust rating",
        new_rating="Exact ELO rating to set"
    )
    required_role = "Stonehearts" 
    
    # If the user is not an admin and does not have the required role
    if not interaction.user.guild_permissions.administrator and not any(role.name == required_role for role in interaction.user.roles):
        await interaction.response.send_message(
            "<:Unamurice:1349309283669377064> I-I’m really sorry, but only an administrator may pull the threads of fate this way...\n"
            "Please speak to someone with the right permissions if you'd like this command woven into being.",
            ephemeral=True
        )
        return
    async def change_rating(
        self,
        interaction: Interaction,
        player: discord.Member,
        new_rating: int
    ):
        await interaction.response.defer()

        """Allows admins to manually adjust a player's ELO rating"""
        try:
            # Validate rating
            if new_rating < 0:
                await interaction.response.send_message("A gentle warning… a rating cannot slip beneath the surface. Let us lift it back above, where hope still shines.", ephemeral=False)
                return

            elo_data = load_elo_data()
            player_id = str(player.id)
            
            # Initialize player data if not exists
            if player_id not in elo_data:
                elo_data[player_id] = {
                    "elo": new_rating,  # Set to new value
                    "win_rate": 0.0,
                    "games_played": 0,
                    "uid": "Not Registered",
                    "mirror_id": "Not Set",
                    "points": 0
                }
            else:
                # Get old rating and update
                old_elo = elo_data[player_id]["elo"]
                elo_data[player_id]["elo"] = new_rating

            # Save changes
            save_elo_data(elo_data)

            # Create embed response
            embed = discord.Embed(
                title="Fate Has Shifted",
                description=f"{player.mention}'s ELO has been gracefully adjusted.",
                color=discord.Color.purple()
            )
            
            if player_id in elo_data: 
                embed.add_field(name="Past Rating", value=str(old_elo), inline=True)
            
            embed.add_field(name="New Rating", value=str(new_rating), inline=True)
            embed.set_footer(text=f"Gently updated by {interaction.user.display_name}")
            embed.timestamp = interaction.created_at

            await interaction.followup.send(embed=embed)

            try:
                previous_elo = old_elo if player_id in elo_data else 200
                old_rank = get_rank(previous_elo, player_id=player.id, elo_data=elo_data)

                await update_rank_role(
                    player,
                    new_rating,
                    elo_data,
                    channel=interaction.channel,
                    announce_demotions=True,
                    force_old_rank=old_rank
                )
            except Exception as e:
                print(f"⚠️ Failed to update role for {player.display_name}: {e}")

        except Exception as e:
            await interaction.response.send_message(
                f"A faint disturbance has occurred...\n `{str(e)}`\nThe change could not be completed. Please, forgive this failure — and try once more when ready.",
                ephemeral=True
            )

    @app_commands.command(name="reset", description="The threads of fate are reset for all players... A new season begins.")
    @app_commands.guilds(GUILD_ID)
    @app_commands.checks.has_permissions(administrator=True)
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message(
            "<:Unamurice:1349309283669377064> I-I’m really sorry, but only an administrator may pull the threads of fate this way...\n"
            "Please speak to someone with the right permissions if you'd like this command woven into being.",
            ephemeral=True
        )
        return
    async def reset_elo(self, interaction: Interaction):
        """Reset ELO, win rate, and games played for all players, keeping UID."""
        try:
            elo_data = load_elo_data()
            modal = ResetConfirmModal(interaction, elo_data)
            await interaction.response.send_modal(modal)
           
        except Exception as e:
            try:
                if interaction.response.is_done():
                    await interaction.followup.send(f"❌ Error: {str(e)}", ephemeral=True)
                else:
                    await interaction.response.send_message(f"❌ Error: {str(e)}", ephemeral=True)
            except Exception as inner:
                print(f"❌ Could not send error message: {inner}")

async def setup(bot):
    await bot.add_cog(AdminCommands(bot))