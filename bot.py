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
    result = await conn.fetch('SELECT match_id, elo_gains FROM matches')  # Adjust the query as needed
    await conn.close()

    mode_count = {"1v1": 0, "1v2": 0, "2v2": 0}

    for match in result:
        elo_gains = match['elo_gains'] 
        total_players = len(elo_gains)

        if total_players == 2:
            mode_count["1v1"] += 1
        elif total_players == 3:
            mode_count["1v2"] += 1
        elif total_players == 4:
            mode_count["2v2"] += 1

    return mode_count

async def track_win_streak():
    conn = await get_db_connection()
    result = await conn.fetch('SELECT raw_data, elo_gains FROM matches')  # Query matches to get raw data and elo gains
    await conn.close()

    longest_streak_player = None
    longest_streak = 0
    current_streak_player = None
    current_streak = 0

    for match in result:
        # Parse the raw_data field to a dictionary
        raw_data = json.loads(match['raw_data'])  # This parses the string into a dictionary

        winner = raw_data['winner']
        # Parse the elo_gains field to a dictionary
        elo_gains = json.loads(match['elo_gains'])  # This parses the string into a dictionary

        for player_id, elo_gain in elo_gains.items():
            # You may need to adjust how you calculate the streak based on your logic
            if player_id == current_streak_player:
                current_streak += 1
            else:
                current_streak_player = player_id
                current_streak = 1

            if current_streak > longest_streak:
                longest_streak = current_streak
                longest_streak_player = player_id

    return longest_streak_player, longest_streak

# Update the games played and member count
@tasks.loop(minutes=7)
async def update_stats():
    games_played = await get_games_played()
    total_members, online_members = await get_member_counts()
    mode_count = await get_match_modes()
    longest_streak_player, longest_streak = await track_win_streak()

    games_channel = client.get_channel(1362383355290849450)
    member_channel = client.get_channel(1362388485398593546)
    match_mode_channel = client.get_channel(1362420110480113766)
    streak_channel = client.get_channel(1362421712540401734)

    try:
        if games_channel:
            await games_channel.edit(name=f"Games Played: {games_played}")
        if member_channel:
            await member_channel.edit(name=f"Members: {total_members} | Online: {online_members}")
        if match_mode_channel:
            await match_mode_channel.edit(
                name=f"1v1: {mode_count['1v1']} | 1v2: {mode_count['1v2']} | 2v2: {mode_count['2v2']}"
            )
        if streak_channel:
            await streak_channel.edit(name=f"Longest Win Streak: {longest_streak_player} - {longest_streak} wins")
        
    except discord.errors.HTTPException as e:
        retry_after = e.response.get('retry_after', 1) 
        await asyncio.sleep(retry_after)
        await update_stats()

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
