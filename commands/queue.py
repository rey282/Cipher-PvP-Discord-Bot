import discord
import os
import asyncio
from discord.ext import commands
from discord import app_commands, Interaction
from dotenv import load_dotenv

load_dotenv()

GUILD_ID = int(os.getenv("DISCORD_GUILD_ID"))

class MatchmakingQueue(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.queue = []
        self.player_timers = {}
        self.voice_channel_monitor = {}

    async def check_voice_channel(self, user, interaction):
        """Check if the player is in the voice channel, and if not, kick them from the queue."""
        while user in self.queue:
            if user.voice is None:
                self.queue.remove(user)
                await interaction.channel.send(
                    f"**{user.display_name}** has gently slipped from the queue, as they are no longer in the voice channel. May the threads weave once more when you return."
                )
                break
            await asyncio.sleep(5)

    @app_commands.command(name="joinqueue", description="Tie your thread to the matchmaking queue.")
    @app_commands.guilds(GUILD_ID)
    async def join_queue(self, interaction: Interaction):
        user = interaction.user

        # Check if the user is in a voice channel
        if user.voice is None:
            await interaction.response.send_message(
                "Oops! You must be in a voice channel to join the queue. Please join a voice channel and try again.",
                ephemeral=True
            )
            return

        if user.id in [u.id for u in self.queue]:
            await interaction.response.send_message("You're already woven into the queue", ephemeral=True)
            return

        self.queue.append(user)
        self.voice_channel_monitor[user] = asyncio.create_task(self.check_voice_channel(user, interaction))
        await interaction.response.send_message(f"{user.display_name} has joined the queue. The threads of fate are being woven.", ephemeral=False)

        if len(self.queue) >= 4:
            players = self.queue[:4]
            self.queue = self.queue[4:]

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

            mentions = ", ".join(p.mention for p in players)
            await interaction.channel.send(
                f"**Match Found!**\n"
                f"**Players:** {mentions}\n"
                f"Fate has woven your paths together. Best of luck"
            )

    @app_commands.command(name="leavequeue", description="Untie your thread from the queue.")
    @app_commands.guilds(GUILD_ID)
    async def leave_queue(self, interaction: Interaction):
        user = interaction.user

        if user not in self.queue:
            await interaction.response.send_message("You were never in the thread to begin with.", ephemeral=True)
            return

        self.queue.remove(user)
        if user in self.voice_channel_monitor:
            self.voice_channel_monitor[user].cancel()
        await interaction.response.send_message("Your thread has been untied from the queue.", ephemeral=False)

    @app_commands.command(name="queue", description="Peek at those waiting in the thread.")
    @app_commands.guilds(GUILD_ID)
    async def show_queue(self, interaction: Interaction):
        if not self.queue:
            await interaction.response.send_message("It’s so quiet in here... The threads of fate are still at rest.", ephemeral=False)
            return

        embed = discord.Embed(
            title="🧵 Matchmaking Queue",
            description="\n".join(f"{i+1}. {u.display_name}" for i, u in enumerate(self.queue)),
            color=discord.Color.purple()
        )
        embed.set_footer(text="Kyasutorisu are watching over the threads of fate...")

        await interaction.response.send_message(embed=embed)

async def setup(bot: commands.Bot):
    await bot.add_cog(MatchmakingQueue(bot))
