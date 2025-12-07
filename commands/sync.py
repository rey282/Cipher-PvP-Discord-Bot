import discord
import os
from discord.ext import commands
from discord import app_commands, Interaction
from utils.db_utils import load_elo_data, save_elo_data
from utils.rank_utils import update_rank_role
from dotenv import load_dotenv

load_dotenv()
OWNER_ID = int(os.getenv("OWNER_ID"))
GUILD_ID = int(os.getenv("DISCORD_GUILD_ID"))


class AnnouncementModal(discord.ui.Modal, title="Compose Announcement"):
    title_input = discord.ui.TextInput(
        label="Announcement Title",
        placeholder="Website Update, Patch Notes, etc.",
        max_length=100,
        style=discord.TextStyle.short
    )

    message_input = discord.ui.TextInput(
        label="Announcement Message",
        placeholder="Type your full announcement here...\nFeel free to press Enter.",
        style=discord.TextStyle.paragraph,
        max_length=3000,
        required=True
    )

    def __init__(self, interaction):
        super().__init__()
        self.interaction = interaction

    async def on_submit(self, interaction: Interaction):
        title = str(self.title_input)
        message = str(self.message_input)

        embed = discord.Embed(
            title=title,
            description=message,
            color=0x5865F2
        )

        embed.set_footer(text="Gently carried by Kyasutorisu")
        embed.timestamp = discord.utils.utcnow()

        await interaction.channel.send(embed=embed)
        await interaction.response.send_message(
            "Your announcement has been gently delivered.",
            ephemeral=True
        )

class AdminSync(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ───────────── SYNC RANKS ─────────────
    @app_commands.command(
        name="sync_ranks",
        description="Gently realign everyone’s role with their thread of fate (based on ELO)."
    )
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
                continue

            player_id = str(member.id)
            if player_id not in elo_data:
                skipped += 1
                continue

            new_elo = elo_data[player_id].get("elo", 200)
            try:
                await update_rank_role(
                    member, new_elo, elo_data,
                    channel=interaction.channel,
                    announce_demotions=True
                )
                updated += 1
            except Exception as e:
                print(f"❌ Failed to update {member.display_name}: {e}")

        await interaction.followup.send(
            f"Kyasutorisu has gently restored the threads of fate.\n"
            f"Updated: `{updated}` members\n"
            f"Skipped (not registered): `{skipped}`",
            ephemeral=True
        )

    @app_commands.command(
        name="announce",
        description="Compose and send a multi-line announcement (Owner only)."
    )
    @app_commands.guilds(GUILD_ID)
    async def announce(self, interaction: Interaction):
        if interaction.user.id != OWNER_ID:
            return await interaction.response.send_message(
                "O-Oh… only Haya may weave announcements like this…",
                ephemeral=True
            )

        modal = AnnouncementModal(interaction)
        await interaction.response.send_modal(modal)


async def setup(bot: commands.Bot):
    await bot.add_cog(AdminSync(bot))
