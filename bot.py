import discord
import asyncpg
import asyncio
import json
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
intents.members = True
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

        await guild.chunk()  
        
        for member in guild.members:
            if member.status != discord.Status.offline:
                online_members += 1

        print(f"Online members: {online_members}")
        return total_members, online_members
    return 0, 0

async def get_match_modes():
    conn = await get_db_connection()
    result = await conn.fetch('SELECT elo_gains FROM matches')  
    await conn.close()

    mode_count = {"1v1": 0, "1v2": 0, "2v2": 0}

    for match in result:
        elo_gains = json.loads(match['elo_gains'])  
        
        total_players = len(elo_gains)

        match total_players:
            case 2:
                mode_count["1v1"] += 1
            case 3:
                mode_count["1v2"] += 1
            case 4:
                mode_count["2v2"] += 1

    return mode_count

# Update the games played and member count
@tasks.loop(minutes=60)
async def update_stats():
    games_played = await get_games_played()
    total_members, online_members = await get_member_counts()
    mode_count = await get_match_modes()

    games_channel = client.get_channel(1362383355290849450)
    member_channel = client.get_channel(1362388485398593546)
    match_mode_channel = client.get_channel(1362420110480113766)

    try:
        if games_channel:
            await games_channel.edit(name=f"Games Played: {games_played}")
        if member_channel:
            await member_channel.edit(name=f"Members: {total_members} | Online: {online_members}")
        if match_mode_channel:
            await match_mode_channel.edit(
                name=f"1v1: {mode_count['1v1']} | 1v2: {mode_count['1v2']} | 2v2: {mode_count['2v2']}"
            )
        
    except discord.errors.HTTPException as e:
        print(f"Failed to update channel: {e}")

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
        "commands.sync",
        "commands.help",
        "commands.queue",
        "commands.character_stats",
        "commands.tournament",
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

@client.event
async def on_member_join(member: discord.Member):
    discord_id = str(member.id)
    username = str(member)
    conn = await get_db_connection()
    try:
        await conn.execute(
            """
            INSERT INTO discord_usernames (discord_id, username)
            VALUES ($1, $2)
            ON CONFLICT (discord_id) DO UPDATE SET username = EXCLUDED.username
            """,
            discord_id,
            username,
        )
        print(f"Synced new member: {username} ({discord_id})")
    finally:
        await conn.close()

# Run the bot
client.run(TOKEN)
