import discord
import asyncpg
import asyncio
import json
from discord.ext import commands, tasks
from dotenv import load_dotenv
import os
import logging

# ───────────────────────────────────────────────────────────────
# LOGGING
# ───────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s: %(message)s'
)

# ───────────────────────────────────────────────────────────────
# ENVIRONMENT VARIABLES
# ───────────────────────────────────────────────────────────────
load_dotenv()
TOKEN = os.getenv("DISCORD_BOT_TOKEN")
GUILD_ID = int(os.getenv("DISCORD_GUILD_ID"))
DATABASE_URL = os.getenv("DATABASE_URL")  # Supabase DB URL

# ───────────────────────────────────────────────────────────────
# DISCORD BOT SETUP
# ───────────────────────────────────────────────────────────────
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.presences = True

client = commands.Bot(command_prefix="c!", intents=intents)

# ───────────────────────────────────────────────────────────────
# GLOBAL ASYNCPG POOL (Supabase FIX)
# ───────────────────────────────────────────────────────────────
pool = None

async def init_db_pool():
    global pool
    try:
        pool = await asyncpg.create_pool(
            dsn=DATABASE_URL,
            min_size=1,
            max_size=5,
            command_timeout=5
        )
        logging.info("[DB] Pool initialized successfully")
    except Exception as e:
        logging.error(f"[DB ERROR] Could not create connection pool: {e}")


# ───────────────────────────────────────────────────────────────
# DATABASE HELPERS USING CONNECTION POOL
# ───────────────────────────────────────────────────────────────
async def get_games_played():
    logging.info("Fetching games played...")
    try:
        async with pool.acquire() as conn:
            result = await conn.fetchval("SELECT COUNT(*) FROM matches")
            logging.info(f"Games Played = {result}")
            return result
    except Exception as e:
        logging.error(f"[DB ERROR] get_games_played: {e}")
        return 0


async def get_member_counts():
    logging.info("Fetching member counts...")

    guild = client.get_guild(GUILD_ID)
    if guild is None:
        logging.error("Guild not found! Check GUILD_ID")
        return 0, 0

    try:
        await guild.chunk()

        total = guild.member_count
        online = sum(1 for m in guild.members if m.status != discord.Status.offline)

        logging.info(f"Members → Total={total} Online={online}")
        return total, online

    except Exception as e:
        logging.error(f"Error in get_member_counts: {e}")
        return 0, 0


async def get_match_modes():
    logging.info("Fetching match modes...")

    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch("SELECT elo_gains FROM matches")
    except Exception as e:
        logging.error(f"[DB ERROR] get_match_modes: {e}")
        return {"1v1": 0, "1v2": 0, "2v2": 0}

    mode_count = {"1v1": 0, "1v2": 0, "2v2": 0}

    for row in rows:
        try:
            data = json.loads(row["elo_gains"])
            n = len(data)

            if n == 2:
                mode_count["1v1"] += 1
            elif n == 3:
                mode_count["1v2"] += 1
            elif n == 4:
                mode_count["2v2"] += 1

        except Exception as e:
            logging.error(f"Error parsing match row: {e}")

    logging.info(f"Match Modes: {mode_count}")
    return mode_count


# ───────────────────────────────────────────────────────────────
# BACKGROUND TASK — Updates stats every 60 minutes
# ───────────────────────────────────────────────────────────────
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

        # Channel exist checks
        if not games_channel:
            logging.error("Games channel NOT FOUND!")
        if not member_channel:
            logging.error("Members channel NOT FOUND!")
        if not match_mode_channel:
            logging.error("Match mode channel NOT FOUND!")

        # Update channels
        if games_channel:
            await games_channel.edit(name=f"Games Played: {games_played}")
            logging.info("Updated Games Played channel")

        if member_channel:
            await member_channel.edit(
                name=f"Members: {total_members} | Online: {online_members}"
            )
            logging.info("Updated Member Count channel")

        if match_mode_channel:
            await match_mode_channel.edit(
                name=f"1v1: {mode_count['1v1']} | "
                     f"1v2: {mode_count['1v2']} | "
                     f"2v2: {mode_count['2v2']}"
            )
            logging.info("Updated Match Mode channel")

    except Exception as e:
        logging.error(f"[update_stats ERROR] {e}")


# ───────────────────────────────────────────────────────────────
# BOT READY — START POOL & TASKS
# ───────────────────────────────────────────────────────────────
@client.event
async def on_ready():
    logging.info(f"Logged in as {client.user} (ID: {client.user.id})")

    await init_db_pool()   
    client.pool = pool
    update_stats.start()   

    # Load command extensions
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
        "commands.roster",
    ]

    for ext in extensions:
        try:
            await client.load_extension(ext)
            logging.info(f"Loaded extension: {ext}")
        except Exception as e:
            logging.error(f"Failed to load extension {ext}: {e}")

    # Sync guild commands
    try:
        guild = discord.Object(id=GUILD_ID)
        synced = await client.tree.sync(guild=guild)
        logging.info(f"Synced {len(synced)} commands to Guild {GUILD_ID}")
    except Exception as e:
        logging.error(f"Error syncing commands: {e}")


# ───────────────────────────────────────────────────────────────
# MEMBER JOIN EVENT — SYNC USERNAMES
# ───────────────────────────────────────────────────────────────
@client.event
async def on_member_join(member):
    discord_id = str(member.id)
    username = str(member)

    logging.info(f"Member joined: {username}")

    try:
        async with pool.acquire() as conn:
            # ───────────────────────────────────────────────
            # 1. Sync username (already existed in your code)
            # ───────────────────────────────────────────────
            await conn.execute(
                """
                INSERT INTO discord_usernames (discord_id, username)
                VALUES ($1, $2)
                ON CONFLICT (discord_id) DO UPDATE SET 
                username = EXCLUDED.username
                """,
                discord_id, username
            )

            logging.info("Username synced")

            # ───────────────────────────────────────────────
            # 2. Initialize PLAYER DATA on join
            # ───────────────────────────────────────────────
            await conn.execute(
                """
                INSERT INTO players (discord_id, nickname, elo, games_played, win_rate, uid, mirror_id, points, description, color, banner_url)
                VALUES ($1, $2, 200, 0, 0.0, 'Not Registered', 'Not Set', 0,
                        'A glimpse into this soul’s gentle journey…', 11658748, NULL)
                ON CONFLICT (discord_id) DO NOTHING
                """,
                discord_id, username
            )

            logging.info(f"[PLAYER INIT] Created player row for {discord_id}")

    except Exception as e:
        logging.error(f"Error syncing username or initializing player data: {e}")

@client.event
async def on_member_update(before: discord.Member, after: discord.Member):
    old_nick = before.nick
    new_nick = after.nick

    old_username = before.name
    new_username = after.name

    discord_id = str(after.id)

    # ───────────────────────────────────────────────
    # 1. Nickname change (players.nickname)
    # ───────────────────────────────────────────────
    if old_nick != new_nick:
        logging.info(f"[NICKNAME UPDATE] {old_nick} → {new_nick}")

        try:
            async with pool.acquire() as conn:
                await conn.execute(
                    """
                    UPDATE players
                    SET nickname = $1
                    WHERE discord_id = $2
                    """,
                    new_nick or new_username,  # fallback if nickname cleared
                    discord_id
                )

            logging.info(f"[SYNCED] Updated players.nickname for {discord_id}")

        except Exception as e:
            logging.error(f"[DB ERROR] Failed to update nickname: {e}")

    # ───────────────────────────────────────────────
    # 2. Username change (discord_usernames.username)
    # ───────────────────────────────────────────────
    if old_username != new_username:
        logging.info(f"[USERNAME UPDATE] {old_username} → {new_username}")

        try:
            async with pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO discord_usernames (discord_id, username)
                    VALUES ($1, $2)
                    ON CONFLICT (discord_id) DO UPDATE SET 
                        username = EXCLUDED.username
                    """,
                    discord_id, new_username
                )

            logging.info(f"[SYNCED] Updated discord_usernames for {discord_id}")

        except Exception as e:
            logging.error(f"[DB ERROR] Failed to update username: {e}")


# ───────────────────────────────────────────────────────────────
# START BOT
# ───────────────────────────────────────────────────────────────
client.run(TOKEN)
