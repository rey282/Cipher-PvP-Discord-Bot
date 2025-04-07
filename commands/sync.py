import discord
import os
from discord.ext import commands
from discord import app_commands, Interaction
from utils.db_utils import load_elo_data
from utils.rank_utils import update_rank_role
from dotenv import load_dotenv

load_dotenv()
OWNER_ID = int(os.getenv("OWNER_ID"))
GUILD_ID = int(os.getenv("DISCORD_GUILD_ID"))
class AdminSync(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="sync_ranks", description="Gently realign everyone’s role with their thread of fate (based on ELO).")
    @app_commands.guilds(GUILD_ID)
    async def sync_ranks(self, interaction: Interaction):
        if interaction.user.id != OWNER_ID:
            await interaction.response.send_message(
                "<:Unamurice:1349309283669377064> O-oh… I’m sorry, but only Haya may realign the threads of fate like this...\n"
                "*You’re not Haya, are you…?*",
                ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        elo_data = load_elo_data()
        updated = 0
        skipped = 0

        for member in guild.members:
            if member.bot:
                continue  # Skip bots

            player_id = str(member.id)
            if player_id not in elo_data:
                skipped += 1
                continue  # Not registered

            new_elo = elo_data[player_id].get("elo", 200)
            try:
                await update_rank_role(member, new_elo, elo_data, channel=interaction.channel, announce_demotions=True)
                updated += 1
            except Exception as e:
                print(f"❌ Failed to update {member.display_name}: {e}")

        await interaction.followup.send(
            f"Kyasutorisu has gently restored the threads of fate.\n"
            f"Updated: `{updated}` members\n"
            f"Skipped (not registered): `{skipped}`",
            ephemeral=True
        )

class RefreshNickname(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="refresh_nickname", description="Update nicknames in the database")
    @app_commands.guilds(GUILD_ID)
    async def refresh_nickname(self, interaction: discord.Interaction):
        if interaction.user.id != OWNER_ID:
            await interaction.response.send_message(
                "<:Unamurice:1349309283669377064> O-oh… I’m sorry, but only Haya may realign the threads of fate like this...\n"
                "*You’re not Haya, are you…?*",
                ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        guild = interaction.guild
        if guild is None:
            await interaction.followup.send("This command must be run in a server.")
            return

        data = load_elo_data()  
        updated = 0

        for discord_id in data:
            member = guild.get_member(int(discord_id))
            if member:
                nickname = member.nick or member.name
                data[discord_id]["nickname"] = nickname
                updated += 1

        save_elo_data(data)
        await interaction.followup.send(f"✅ Updated nicknames for {updated} members.")

async def setup(bot: commands.Bot):
    await bot.add_cog(AdminSync(bot))