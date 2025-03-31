import discord
import os
from discord.ext import commands
from discord import app_commands, Interaction
from utils.db_utils import load_elo_data
from utils.rank_utils import update_rank_role
from dotenv import load_dotenv

load_dotenv()

GUILD_ID = int(os.getenv("DISCORD_GUILD_ID"))
class AdminSync(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="sync_ranks", description="Gently realign everyone’s role with their thread of fate (based on ELO).")
    @app_commands.guilds(GUILD_ID)
    async def sync_ranks(self, interaction: Interaction):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(
                "<:Unamurice:1349309283669377064> I-I’m really sorry, but only an administrator may pull the threads of fate this way...\n"
                "Please speak to someone with the right permissions if you'd like this command woven into being.",
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

async def setup(bot: commands.Bot):
    await bot.add_cog(AdminSync(bot))