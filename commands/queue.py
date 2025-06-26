import discord
import os
import asyncio
import random
from discord.ext import commands
from discord import app_commands, Interaction
from dotenv import load_dotenv

load_dotenv()

GUILD_ID = int(os.getenv("DISCORD_GUILD_ID"))

class MatchmakingQueue(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.queue = []
        self.queue_lock = asyncio.Lock()
        self.player_timers = {}
        self.voice_channel_monitor = {}
        self.afk_monitor = {}
        self.queue_inactivity_monitor = None

    async def check_queue_inactivity(self, channel: discord.abc.Messageable):
        await asyncio.sleep(45 * 60)
        async with self.queue_lock:
            if len(self.queue) > 0:
                await channel.send(
                    f"The threads of fate have not woven any new paths for 45 minutes... As a result, the queue has been gently disbanded. May your threads intertwine again when the time is right."
                )
                self.queue.clear()
                self.queue_inactivity_monitor = None

    async def check_afk(self, user: discord.User, channel: discord.abc.Messageable):
        afk_timeout = 15 * 60
        await asyncio.sleep(afk_timeout)

        async with self.queue_lock:
            if user in self.queue:
                # If user is not in VC and hasn't sent a message recently
                if user.voice is None and (not user.last_message or (discord.utils.utcnow() - user.last_message.created_at).total_seconds() > afk_timeout):
                    await channel.send(
                        f"**{user.display_name}** ,I’m afraid your thread has been gently unraveled from the queue. You’ve drifted away from the voice and text realms for too long..."
                    )
                    self.queue.remove(user)
                    self.afk_monitor.pop(user, None)
                    self.voice_channel_monitor.pop(user, None)

    async def check_single_player_in_queue(self, channel: discord.abc.Messageable):
        await asyncio.sleep(15 * 60)
        async with self.queue_lock:
            if len(self.queue) == 1:
                user = self.queue[0]
                self.queue.remove(user)
                await channel.send(
                    f"**{user.display_name}** , alas, your thread has been gently unwoven from the queue. You've waited with patience, but fate has not yet woven your match. Please return soon, dear one..."
                )
                self.afk_monitor.pop(user, None)
                self.voice_channel_monitor.pop(user, None)

    async def check_voice_channel(self, user: discord.User, channel: discord.abc.Messageable):
        await asyncio.sleep(10)
        async with self.queue_lock:
            if user in self.queue and user.voice is None:
                self.queue.remove(user)
                await channel.send(
                    f"**{user.display_name}**, your thread has been gently unwoven from the queue, as you are no longer in the voice channel. May the threads weave once more when you return."
                )
                self.afk_monitor.pop(user, None)
                self.voice_channel_monitor.pop(user, None)

    @app_commands.command(name="joinqueue", description="Tie your thread to the matchmaking queue.")
    @app_commands.guilds(GUILD_ID)
    async def join_queue(self, interaction: Interaction):
        user = interaction.user

        if user.voice is None:
            await interaction.response.send_message(
                "Oops! You must be in a voice channel to join the queue. Please join a voice channel and try again.",
                ephemeral=True
            )
            return

        async with self.queue_lock:
            if user in self.queue:
                await interaction.response.send_message("You're already woven into the queue", ephemeral=True)
                return

            self.queue.append(user)

            # Start voice and afk monitors
            self.voice_channel_monitor[user] = asyncio.create_task(self.check_voice_channel(user, interaction.channel))
            self.afk_monitor[user] = asyncio.create_task(self.check_afk(user, interaction.channel))

            if len(self.queue) == 1:
                self.queue_inactivity_monitor = asyncio.create_task(self.check_queue_inactivity(interaction.channel))
                asyncio.create_task(self.check_single_player_in_queue(interaction.channel))

        await interaction.response.send_message(f"{user.display_name} has joined the queue. The threads of fate are being woven.", ephemeral=False)

        # Form a match
        async with self.queue_lock:
            if len(self.queue) >= 4:
                players = self.queue[:4]
                self.queue = self.queue[4:]

                for p in players:
                    if p in self.afk_monitor:
                        self.afk_monitor[p].cancel()
                        del self.afk_monitor[p]
                    if p in self.voice_channel_monitor:
                        self.voice_channel_monitor[p].cancel()
                        del self.voice_channel_monitor[p]

                random.shuffle(players)
                team1, team2 = players[:2], players[2:]

                mentions = ", ".join(p.mention for p in players)
                await interaction.channel.send(
                    f"**Match Found!**\n"
                    f"**Players:** {mentions}\n"
                    f"Fate has woven your paths together. Best of luck"
                )

                embed = discord.Embed(
                    title="Threads Aligned",
                    description="The threads have been gently woven… Here is your match.",
                    color=discord.Color.blue()
                )
                embed.add_field(name="Team 1", value=f"{team1[0].mention} & {team1[1].mention}", inline=False)
                embed.add_field(name="Team 2", value=f"{team2[0].mention} & {team2[1].mention}", inline=False)
                embed.set_footer(text="Woven gently by Kyasutorisu")
                await interaction.followup.send(embed=embed)

    @app_commands.command(name="leavequeue", description="Untie your thread from the queue.")
    @app_commands.guilds(GUILD_ID)
    async def leave_queue(self, interaction: Interaction):
        user = interaction.user

        async with self.queue_lock:
            if user not in self.queue:
                await interaction.response.send_message("You were never in the thread to begin with.", ephemeral=True)
                return

            self.queue.remove(user)

            if user in self.voice_channel_monitor:
                self.voice_channel_monitor[user].cancel()
                del self.voice_channel_monitor[user]
            if user in self.afk_monitor:
                self.afk_monitor[user].cancel()
                del self.afk_monitor[user]

        await interaction.response.send_message("Your thread has been untied from the queue.", ephemeral=False)

    @app_commands.command(name="queue", description="Peek at those waiting in the thread.")
    @app_commands.guilds(GUILD_ID)
    async def show_queue(self, interaction: Interaction):
        async with self.queue_lock:
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

    @app_commands.command(name="clearqueue", description="Gently unravel all threads from the queue.")
    @app_commands.guilds(GUILD_ID)
    @app_commands.checks.has_permissions(administrator=True)
    async def clear_queue(self, interaction: Interaction):
        async with self.queue_lock:
            self.queue.clear()
            for task in self.voice_channel_monitor.values():
                task.cancel()
            for task in self.afk_monitor.values():
                task.cancel()
            self.voice_channel_monitor.clear()
            self.afk_monitor.clear()
            if self.queue_inactivity_monitor:
                self.queue_inactivity_monitor.cancel()
                self.queue_inactivity_monitor = None

        await interaction.response.send_message("The threads of fate have been gently unraveled. The queue is now empty.", ephemeral=False)

async def setup(bot: commands.Bot):
    await bot.add_cog(MatchmakingQueue(bot))
