import os
import json
import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv
from datetime import datetime

load_dotenv()

GUILD_ID = int(os.getenv("DISCORD_GUILD_ID"))
DATABASE_URL = os.getenv("DATABASE_URL")


def get_connection():
    return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)


def initialize_db():
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS players (
                discord_id TEXT PRIMARY KEY,
                nickname TEXT,
                elo INTEGER NOT NULL,
                games_played INTEGER NOT NULL,
                win_rate REAL NOT NULL,
                uid TEXT,
                mirror_id TEXT,
                points INTEGER DEFAULT 0,
                description TEXT DEFAULT 'A glimpse into this soul’s gentle journey…',
                color INTEGER DEFAULT 11658748,  -- 0xB197FC in decimal
                banner_url TEXT
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS matches (
                match_id SERIAL PRIMARY KEY,
                timestamp TEXT NOT NULL,
                elo_gains JSONB NOT NULL,
                raw_data JSONB
            )
        ''')
        conn.commit()


def load_elo_data():
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM players")
        rows = cursor.fetchall()
        return {
            row['discord_id']: {
                "nickname": row.get('nickname', ''),
                "elo": row['elo'],
                "games_played": row['games_played'],
                "win_rate": row['win_rate'],
                "uid": row.get('uid', 'Not Registered'),
                "mirror_id": row.get('mirror_id', 'Not Set'),
                "points": row.get('points', 0),
                "description": row.get('description', ''),
                "color": row.get('color', 0xB197FC),
                "banner_url": row.get('banner_url', None)
            } for row in rows
        }


def save_elo_data(data):
    from bot import get_bot
    
    bot = get_bot()
    guild = bot.get_guild(GUILD_ID)

    with get_connection() as conn:
        cursor = conn.cursor()
        for discord_id, stats in data.items():
            if guild:
                member = guild.get_member(int(discord_id))
                if member:
                    stats["nickname"] = member.nick or member.name
            cursor.execute('''
                INSERT INTO players (discord_id, nickname, elo, games_played, win_rate, uid, mirror_id, points, description, color, banner_url)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (discord_id) DO UPDATE SET
                    nickname = EXCLUDED.nickname,
                    elo = EXCLUDED.elo,
                    games_played = EXCLUDED.games_played,
                    win_rate = EXCLUDED.win_rate,
                    uid = EXCLUDED.uid,
                    mirror_id = EXCLUDED.mirror_id,
                    points = EXCLUDED.points,
                    description = EXCLUDED.description,
                    color = EXCLUDED.color,
                    banner_url = EXCLUDED.banner_url
            ''', (
                discord_id,
                stats.get("nickname", ""),
                stats.get("elo", 200),
                stats.get("games_played", 0),
                stats.get("win_rate", 0.0),
                stats.get("uid", "Not Registered"),
                stats.get("mirror_id", "Not Set"),
                stats.get("points", 0),
                stats.get("description", ""),
                stats.get("color", 0xB197FC),
                stats.get("banner_url", None)
            ))
        conn.commit()


def load_match_history():
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT raw_data FROM matches ORDER BY match_id DESC")
        rows = cursor.fetchall()
        return [json.loads(row['raw_data']) if isinstance(row['raw_data'], str) else row['raw_data'] for row in rows]



def save_match_history(match_data):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO matches (timestamp, elo_gains, raw_data)
            VALUES (%s, %s, %s)
        ''', (
            datetime.now().isoformat(),
            json.dumps(match_data.get("elo_gains", {})),  # store as JSON
            json.dumps(match_data)  # full match_data as raw_data
        ))
        conn.commit()

def initialize_player_data(player_id):
    return {
        "elo": 200,
        "games_played": 0,
        "win_rate": 0.0,
        "uid": "Not Registered",
        "mirror_id": "Not Set",
        "points": 0,
        "description": "A glimpse into this soul’s gentle journey…",
        "color": 0xB197FC,  
    }


def rollback_last_match():
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT match_id, elo_gains FROM matches ORDER BY match_id DESC LIMIT 1")
        match = cursor.fetchone()
        if not match:
            return False, "No matches to rollback"

        match_id = match['match_id']
        elo_gains = match['elo_gains']
        elo_data = load_elo_data()
        changes_made = False

        for player_id, gain in elo_gains.items():
            if str(player_id) in elo_data:
                changes_made = True
                player_data = elo_data[str(player_id)]
                player_data['elo'] -= gain
                games = player_data['games_played'] - 1
                player_data['games_played'] = max(0, games)

                if games > 0:
                    current = player_data['win_rate']
                    if gain > 0:
                        player_data['win_rate'] = ((current * (games + 1)) - 1) / games
                    else:
                        player_data['win_rate'] = (current * (games + 1)) / games
                else:
                    player_data['win_rate'] = 0.0

        if changes_made:
            updated_history = load_match_history()[1:]
            save_elo_data(elo_data)
            cursor.execute("DELETE FROM matches WHERE match_id = %s", (match_id,))
            conn.commit()
            return True, "Match rollback successful"

    return False, "No changes were made"


def calculate_team_elo_change(
    winner_avg_elo: float,
    loser_avg_elo: float,
    base_gain: float = 20,
    base_loss: float = 20,
    variance_gain: float = 1.2,
    variance_loss: float = 0.65
):
    ratio = loser_avg_elo / winner_avg_elo
    per_player_gain = base_gain * variance_gain * ratio
    per_player_loss = base_loss * variance_loss * ratio
    return per_player_gain, per_player_loss


def distribute_team_elo_change(team, per_player_change, elo_data, gain=True):
    seen_ids = set()
    changes = {}

    original_elos = {
        str(player.id): elo_data.get(str(player.id), {"elo": 200})["elo"]
        for player in team
    }

    for i, player in enumerate(team):
        player_id = str(player.id)
        if player_id in seen_ids:
            continue
        seen_ids.add(player_id)

        if player_id not in elo_data:
            elo_data[player_id] = initialize_player_data(player_id)

        player_data = elo_data[player_id]
        player_elo = original_elos[player_id]

        # Determine teammate's ELO (for 2v2 logic)
        if len(team) == 2:
            teammate = team[1 - i]
            teammate_id = str(teammate.id)
            teammate_elo = original_elos.get(teammate_id, 200)

            # Handle rounding imprecision
            if abs(teammate_elo - player_elo) < 0.01:
                ratio = 1.0
            else:
                ratio = teammate_elo / player_elo if gain else player_elo / teammate_elo

            individual_change = per_player_change * ratio
        else:
            individual_change = per_player_change

            
        # Apply ELO adjustment
        new_elo = player_elo + individual_change if gain else player_elo - individual_change
        player_data["elo"] = max(100, round(new_elo, 2))

        player_data["games_played"] += 1
        wins = player_data["win_rate"] * (player_data["games_played"] - 1)
        if gain:
            wins += 1
        player_data["win_rate"] = wins / player_data["games_played"]

        # Now apply the tapering after the teammate ELO logic
        if abs(individual_change) > 30:
            taper_factor = max(0.7 - (abs(individual_change) - 30) * 0.01, 0.2)
            individual_change = individual_change * taper_factor

        final_elo = player_elo + individual_change if gain else player_elo - individual_change
        player_data["elo"] = max(100, round(final_elo, 2))

        changes[player_id] = round(individual_change if gain else -individual_change, 2)

    return changes
