import discord
import asyncpg
import asyncio
from discord.ext import commands
from discord import app_commands 
from dotenv import load_dotenv
from commands.admin_commands import AdminCommands
from discord.ext import commands, tasks
import os
from utils.db_utils import initialize_db

# Load environment variables
load_dotenv()
TOKEN = os.getenv("DISCORD_BOT_TOKEN")
GUILD_ID = int(os.getenv("DISCORD_GUILD_ID"))
NEON_DATABASE_URL = os.getenv("DATABASE_URL")

# Bot setup
intents = discord.Intents.default()
intents.message_content = True
intents.presences = True
client = commands.Bot(command_prefix="c!", intents=intents)

async def get_db_connection():
    return await asyncpg.connect(NEON_DATABASE_URL)

# Get the count of games played from the database
async def get_games_played():
    conn = await get_db_connection()
    result = await conn.fetchval('SELECT COUNT(*) FROM matches')  # Adjust the query if your schema differs
    await conn.close()
    return result

async def get_member_counts():
    guild = client.get_guild(GUILD_ID)
    if guild:
        total_members = guild.member_count
        online_members = 0

        # Fetch all members asynchronously
        async for member in guild.fetch_members():
            if member.status != discord.Status.offline:
                online_members += 1

        return total_members, online_members
    return 0, 0

# Update the games played and member count
@tasks.loop(minutes=5)
async def update_stats():
    games_played = await get_games_played()
    total_members, online_members = await get_member_counts()
    
    # Update the 'Games Played' channel name
    games_channel = client.get_channel(1362383355290849450)  # Replace YOUR_CHANNEL_ID with the correct channel ID
    if games_channel:
        await games_channel.edit(name=f"Games Played: {games_played}")
    
    # Update the 'Members' channel name
    member_channel = client.get_channel(1362388485398593546)  # Replace YOUR_MEMBER_CHANNEL_ID with the correct channel ID
    if member_channel:
        await member_channel.edit(name=f"Members: {total_members} | Online: {online_members}")

@client.event
async def on_ready():
    print(f'Logged on as {client.user}! (ID: {client.user.id})')
    update_stats.start()
    # Load extensions
    extensions = [
        "commands.fun_commands",
        "commands.elo_commands",
        "commands.matchmaking",
        "commands.admin_commands",
        "commands.history_commands",
        "commands.show",
        "commands.sync",
        "commands.help",
        "commands.queue"
    ]
    
    for ext in extensions:
        try:
            await client.load_extension(ext)
            print(f"Loaded extension: {ext}")
        except Exception as e:
            print(f"Failed to load extension {ext}: {e}")
    
    # Sync ONLY guild-specific commands
    try:
        guild = discord.Object(id=GUILD_ID)  # Your guild ID
        synced = await client.tree.sync(guild=guild)
        print(f"Synced {len(synced)} guild commands to server ID {GUILD_ID}")
        
        # Debug: List all synced commands
        print("Commands in this guild:")
        for cmd in await client.tree.fetch_commands(guild=guild):
            print(f"- /{cmd.name}")
    except Exception as e:
        print(f"Error syncing guild commands: {e}")

# Run the bot
client.run(TOKEN)
