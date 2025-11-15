import discord
import asyncpg
import asyncio
import json
from discord.ext import commands, tasks
from discord import app_commands
from dotenv import load_dotenv
from commands.admin_commands import AdminCommands
import os
from utils.db_utils import initialize_db
import logging

# ───── Logging Setup ─────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s: %(message)s'
)

# ───── Environment Vars ──────────────────────────────────────────────────────
load_dotenv()
TOKEN = os.getenv("DISCORD_BOT_TOKEN")
GUILD_ID = int(os.getenv("DISCORD_GUILD_ID"))
NEON_DATABASE_URL = os.getenv("DATABASE_URL")

# ───── Bot Setup ─────────────────────────────────────────────────────────────
intents = discord.Intents.default()
intents.message_content = True
intents.presences = True
intents.members = True

client = commands.Bot(command_prefix="c!", intents=intents)


# ───── Database Connection Helper ────────────────────────────────────────────
async def get_db_connection():
    try:
        conn = await asyncpg.connect(NEON_DATABASE_URL)
        return conn
    except Exception as e:
        logging.error(f"[DB] Failed to connect: {e}")
        return None


# ───── DATABASE QUERIES ──────────────────────────────────────────────────────
async def get_games_played():
    logging.info("Fetching games played...")
    try:
        conn = await get_db_connection()
        if conn is None:
            logging.error("[DB] No DB connection for games played")
            return 0

        result = await conn.fetchval('SELECT COUNT(*) FROM matches')
        await conn.close()

        logging.info(f"Games Played = {result}")
        return result
    except Exception as e:
        logging.error(f"[DB ERROR] get_games_played: {e}")
        return 0


async def get_member_counts():
    logging.info("Fetching member counts...")

    guild = client.get_guild(GUILD_ID)
    if guild is None:
        logging.error("Guild not found! Check GUILD_ID.")
        return 0, 0

    try:
        await guild.chunk()

        total = guild.member_count
        online = sum(1 for m in guild.members if m.status != discord.Status.offline)

        logging.info(f"Members → Total={total}, Online={online}")
        return total, online

    except Exception as e:
        logging.error(f"Error in get_member_counts: {e}")
        return 0, 0


async def get_match_modes():
    logging.info("Fetching match modes...")

    try:
        conn = await get_db_connection()
        if conn is None:
            logging.error("[DB] No DB connection for match modes")
            return {"1v1": 0, "1v2": 0, "2v2": 0}

        result = await conn.fetch('SELECT elo_gains FROM matches')
        await conn.close()

        mode_count = {"1v1": 0, "1v2": 0, "2v2": 0}

        for row in result:
            try:
                elo_gains = json.loads(row["elo_gains"])
                num_players = len(elo_gains)

                if num_players == 2:
                    mode_count["1v1"] += 1
                elif num_players == 3:
                    mode_count["1v2"] += 1
                elif num_players == 4:
                    mode_count["2v2"] += 1
            except Exception as e:
                logging.error(f"Error parsing match mode: {e}")

        logging.info(f"Match Mode Counts: {mode_count}")
        return mode_count

    except Exception as e:
        logging.error(f"[DB ERROR] get_match_modes: {e}")
        return {"1v1": 0, "1v2": 0, "2v2": 0}


# ───── BACKGROUND TASK ───────────────────────────────────────────────────────
@tasks.loop(minutes=60)
async def update_stats():
    logging.info("Running update_stats...")

    try:
        games_played = await get_games_played()
        total_members, online_members = await get_member_counts()
        mode_count = await get_match_modes()

        games_channel = client.get_channel(1362383355290849450)
        member_channel = client.get_channel(1362388485398593546)
        match_mode_channel = client.get_channel(1362420110480113766)

        if not games_channel:
            logging.error("Games channel NOT FOUND!")
        if not member_channel:
            logging.error("Member channel NOT FOUND!")
        if not match_mode_channel:
            logging.error("Match mode channel NOT FOUND!")

        if games_channel:
            await games_channel.edit(name=f"Games Played: {games_played}")
            logging.info("Updated games channel")

        if member_channel:
            await member_channel.edit(name=f"Members: {total_members} | Online: {online_members}")
            logging.info("Updated member channel")

        if match_mode_channel:
            await match_mode_channel.edit(
                name=f"1v1: {mode_count['1v1']} | 1v2: {mode_count['1v2']} | 2v2: {mode_count['2v2']}"
            )
            logging.info("Updated match mode channel")

    except Exception as e:
        logging.error(f"[update_stats ERROR] {e}")


# ───── BOT READY EVENT ───────────────────────────────────────────────────────
@client.event
async def on_ready():
    logging.info(f"Logged in as {client.user} (ID: {client.user.id})")

    update_stats.start()

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
            logging.info(f"Loaded extension: {ext}")
        except Exception as e:
            logging.error(f"Failed to load extension {ext}: {e}")

    # Sync commands
    try:
        guild = discord.Object(id=GUILD_ID)
        synced = await client.tree.sync(guild=guild)
        logging.info(f"Synced {len(synced)} commands → Guild {GUILD_ID}")
    except Exception as e:
        logging.error(f"Error syncing commands: {e}")


# ───── MEMBER JOIN EVENT (username sync) ─────────────────────────────────────
@client.event
async def on_member_join(member):
    discord_id = str(member.id)
    username = str(member)

    logging.info(f"New member joined: {username}")

    conn = await get_db_connection()
    if conn is None:
        return

    try:
        await conn.execute(
            """
            INSERT INTO discord_usernames (discord_id, username)
            VALUES ($1, $2)
            ON CONFLICT (discord_id) DO UPDATE SET username = EXCLUDED.username
            """,
            discord_id, username
        )

        logging.info(f"Synced username → {username}")
    except Exception as e:
        logging.error(f"Error syncing member on join: {e}")
    finally:
        await conn.close()


# ───── START BOT ─────────────────────────────────────────────────────────────
client.run(TOKEN)
