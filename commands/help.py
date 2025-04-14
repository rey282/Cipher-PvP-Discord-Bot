import discord
import os
from discord.ext import commands
from discord import app_commands

GUILD_ID = int(os.getenv("DISCORD_GUILD_ID"))

class HelpCommand(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="help", description="Ah, you wish to know the paths before you? Here are the threads of destiny:")
    @app_commands.guilds(GUILD_ID)
    async def help(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="Kyasutorisu Help",
            description="Here are the commands you can use to interact with the bot. Please choose wisely, for each thread of fate has its purpose.",
            color=discord.Color.purple()
        )

        embed.add_field(
            name="/match-history",
            value="Let me gently reveal the echoes of a player's past battles.",
            inline=False
        )
        embed.add_field(
            name="/topwinrate",
            value="Would you like to glimpse the highest winning threads…?",
            inline=False
        )
        embed.add_field(
            name="/submit-match",
            value="Whisper the outcome... and I shall adjust the threads of fate.",
            inline=False
        )
        embed.add_field(
            name="/matchmaking",
            value="Allow me to gently weave a random 2v2 from the threads you've offered...",
            inline=False
        )
        embed.add_field(
            name="/register",
            value="Allow me to gently record or update your thread...",
            inline=False
        )
        embed.add_field(
            name="/playercard",
            value="Would you like to glimpse a player’s thread? I can show you their profile.",
            inline=False
        )
        embed.add_field(
            name="/prebans",
            value="Allow me to gently calculate the pre-bans, with teams woven into their fates.",
            inline=False
        )
        embed.add_field(
            name="/show-cipher",
            value="Gently unveiling the Mirror ID and Cipher Points for up to 4 players, woven by fate..",
            inline=False
        )
        embed.add_field(
            name="/setplayercard",
            value="Gently adjust your soul’s card — a new whisper, a new color…",
            inline=False
        )
        embed.add_field(
            name="/joinqueue",
            value="Tie your thread to the matchmaking queue.",
            inline=False
        )
        embed.add_field(
            name="/leavequeue",
            value="Untie your thread from the queue.",
            inline=False
        )
        embed.add_field(
            name="/queue",
            value="Peek at those waiting in the thread.",
            inline=False
        )

        embed.set_footer(text="Handled with care by Kyasutorisu")

        await interaction.response.send_message(embed=embed)

async def setup(bot):
    await bot.add_cog(HelpCommand(bot))
