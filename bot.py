import discord
from discord.ext import commands
from discord import app_commands 
from dotenv import load_dotenv
from commands.admin_commands import AdminCommands
import os
from utils.db_utils import initialize_db

# Load environment variables
load_dotenv()
TOKEN = os.getenv("DISCORD_BOT_TOKEN")
GUILD_ID = int(os.getenv("DISCORD_GUILD_ID"))

# Bot setup
intents = discord.Intents.default()
intents.message_content = True
client = commands.Bot(command_prefix="c!", intents=intents)

@client.event
async def on_ready():
    print(f'Logged on as {client.user}! (ID: {client.user.id})')
    
    # Load extensions
    extensions = [
        "commands.fun_commands",
        "commands.elo_commands",
        "commands.matchmaking",
        "commands.admin_commands",
        "commands.history_commands",
        "commands.topwinrate",
        "commands.sync",
        "commands.help"
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

def get_bot():
    return client
