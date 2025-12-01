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
    
            @app_commands.command(
                name="sync_all_players",
                description="Force-sync every member in the server into the player database."
            )
            @app_commands.guilds(GUILD_ID)
            async def sync_all_players(self, interaction: Interaction):

                if interaction.user.id != OWNER_ID:
                    await interaction.response.send_message(
                        "<:Unamurice:1349309283669377064> O-oh… only Haya can weave the fates like this...",
                        ephemeral=True)
                    return

                await interaction.response.defer(ephemeral=True)

                guild = interaction.guild
                inserted = 0
                skipped = 0
                skipped_bots = 0

                # Load who already exists in the players table
                existing = load_elo_data()

                from bot import pool   

                for member in guild.members:
                    if member.bot:
                        skipped_bots += 1
                        continue

                    discord_id = str(member.id)
                    username = member.name

                    # Already exists in DB → skip
                    if discord_id in existing:
                        skipped += 1
                        continue

                    # Insert player entry & username on first sync
                    try:
                        async with pool.acquire() as conn:
                            # Insert into players table
                            await conn.execute(
                                """
                                INSERT INTO players (
                                    discord_id, nickname, elo, games_played, win_rate,
                                    uid, mirror_id, points, description, color, banner_url
                                )
                                VALUES ($1, $2, 200, 0, 0.0, 
                                        'Not Registered', 'Not Set', 0,
                                        'A glimpse into this soul’s gentle journey…', 
                                        11658748, NULL)
                                ON CONFLICT (discord_id) DO NOTHING
                                """,
                                discord_id, username
                            )

                            # Insert into username table
                            await conn.execute(
                                """
                                INSERT INTO discord_usernames (discord_id, username)
                                VALUES ($1, $2)
                                ON CONFLICT (discord_id) DO UPDATE SET username = EXCLUDED.username
                                """,
                                discord_id, username
                            )

                        inserted += 1

                    except Exception as e:
                        print(f"Failed to insert {discord_id}: {e}")

                await interaction.followup.send(
                    f" **Sync Complete** ✨\n\n"
                    f" Inserted new players: `{inserted}`\n"
                    f" Already existed: `{skipped}`\n"
                    f" Skipped bots: `{skipped_bots}`\n",
                    ephemeral=True
                )



async def setup(bot: commands.Bot):
    await bot.add_cog(AdminSync(bot))