import os
import json
import psycopg2
from psycopg2.extras import RealDictCursor
from psycopg2 import sql
from dotenv import load_dotenv
from datetime import datetime
from contextlib import contextmanager

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

@contextmanager
def get_connection():
    """Context manager for database connections to ensure proper closing."""
    conn = None
    try:
        conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
        yield conn
    finally:
        if conn is not None:
            conn.close()


@contextmanager
def get_cursor(commit=False):
    """Context manager for database cursors with optional commit."""
    with get_connection() as conn:
        cursor = conn.cursor()
        try:
            yield cursor
            if commit:
                conn.commit()
        except Exception:
            conn.rollback()
            raise


def initialize_db():
    with get_cursor(commit=True) as cursor:
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
                raw_data JSONB,
                has_character_data BOOLEAN DEFAULT FALSE
            )
        ''')


def load_elo_data():
    with get_cursor() as cursor:
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
    with get_cursor(commit=True) as cursor:
        for discord_id, stats in data.items():
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


def load_match_history():
    with get_cursor() as cursor:
        cursor.execute("SELECT raw_data FROM matches ORDER BY match_id DESC")
        rows = cursor.fetchall()
        return [json.loads(row['raw_data']) if isinstance(row['raw_data'], str) else row['raw_data'] for row in rows]

def save_match_history(match_data):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO matches (timestamp, elo_gains, raw_data, has_character_data)
            VALUES (%s, %s, %s, %s)
        ''', (
            datetime.now().isoformat(),
            json.dumps(match_data.get("elo_gains", {})),
            json.dumps(match_data) ,
            True
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
        cursor.execute("SELECT match_id, elo_gains, raw_data FROM matches ORDER BY match_id DESC LIMIT 1")
        match = cursor.fetchone()

        if not match:
            return False, "No matches to rollback"

        match_id = match['match_id']
        elo_gains = match['elo_gains']
        match_data = match['raw_data'] if isinstance(match['raw_data'], dict) else json.loads(match['raw_data'])
        winner = match_data.get("winner")

        print(f"DEBUG: Full match data: {json.dumps(match_data, indent=2)}")
        print(f"DEBUG: Winner value: {winner} (type: {type(winner)})")

        # --- Revert ELO Data ---
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

        if not changes_made:
            return False, "No ELO data was affected."

        # --- Revert Character Table Stats ---
        seen_codes = set()

        for team_key in ["blue_picks", "red_picks"]:
            picks = match_data.get(team_key, [])
            team_won = False
            if team_key == "blue_picks":
                team_won = winner == "blue"
                print(f"DEBUG: Blue team won? {team_won} (winner: {winner})")
            elif team_key == "red_picks":
                team_won = winner == "red"
                print(f"DEBUG: Red team won? {team_won} (winner: {winner})")

            for pick in picks:
                code = pick.get("code")
                eid = pick.get("eidolon")
                print(f"DEBUG: Processing pick: {code} eidolon {eid}")

                if not code or eid is None:
                    print(f"DEBUG: Skipping pick - missing code or eidolon")
                    continue

                if code not in seen_codes:
                    seen_codes.add(code)
                    cursor.execute(
                        "UPDATE characters SET appearance_count = GREATEST(appearance_count - 1, 0) WHERE code = %s", (code,)
                    )

                cursor.execute("UPDATE characters SET pick_count = GREATEST(pick_count - 1, 0) WHERE code = %s", (code,))

                cursor.execute(
                    sql.SQL("UPDATE characters SET {} = GREATEST({} - 1, 0) WHERE code = %s").format(
                        sql.Identifier(f"e{eid}_uses"),
                        sql.Identifier(f"e{eid}_uses")
                    ),
                    (code,)
                )

                if team_won:
                    print(f"DEBUG: Decrementing wins for {code} eidolon {eid}")
                    cursor.execute(
                        sql.SQL("UPDATE characters SET {} = GREATEST({} - 1, 0) WHERE code = %s").format(
                            sql.Identifier(f"e{eid}_wins"),
                            sql.Identifier(f"e{eid}_wins")
                        ),
                        (code,)
                    )

        for team_key in ["blue_bans", "red_bans"]:
            bans = match_data.get(team_key, [])
            for ban in bans:
                code = ban.get("code")
                if code:
                    if code not in seen_codes:
                        seen_codes.add(code)
                        cursor.execute(
                            "UPDATE characters SET appearance_count = GREATEST(appearance_count - 1, 0) WHERE code = %s", (code,)
                        )
                    cursor.execute("UPDATE characters SET ban_count = GREATEST(ban_count - 1, 0) WHERE code = %s", (code,))

        for field, column in [("prebans", "preban_count"), ("jokers", "joker_count")]:
            for code in match_data.get(field, []):
                if code not in seen_codes:
                    seen_codes.add(code)
                    cursor.execute(
                        "UPDATE characters SET appearance_count = GREATEST(appearance_count - 1, 0) WHERE code = %s", (code,)
                    )
                cursor.execute(
                    sql.SQL("UPDATE characters SET {} = GREATEST({} - 1, 0) WHERE code = %s").format(
                        sql.Identifier(column),
                        sql.Identifier(column)
                    ),
                    (code,)
                )

        # Finalize rollback
        save_elo_data(elo_data)
        cursor.execute("DELETE FROM matches WHERE match_id = %s", (match_id,))
        conn.commit()
        return True, "Match rollback successful"


def calculate_team_elo_change(
    winner_avg_elo: float,
    loser_avg_elo: float,
    base_gain: float = 25,
    base_loss: float = 20,
    variance_gain: float = 1.5,
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

        if abs(individual_change) > 30:
            excess = abs(individual_change) - 30
            if gain:  # Winning (gain)
                excess_multiplier = 0.5  
            else:     # Losing (loss)
                excess_multiplier = 0.2
            
            tapered_change = 30 + (excess * excess_multiplier)
            individual_change = tapered_change if individual_change > 0 else -tapered_change
        final_elo = player_elo + individual_change if gain else player_elo - individual_change
        player_data["elo"] = max(100, round(final_elo, 2))

        changes[player_id] = round(individual_change if gain else -individual_change, 2)

    return changes


def update_character_table_stats(match_data, winning_team: str):
    with get_cursor(commit=True) as cursor:
        all_codes = set()

        for team_key in ["blue_picks", "red_picks"]:
            picks = match_data.get(team_key, [])
            team_won = (team_key == "blue_picks" and winning_team == "blue") or (team_key == "red_picks" and winning_team == "red")

            for pick in picks:
                code = pick["code"]
                eid = pick["eidolon"]

                all_codes.add(code)

                # Fetch or create metadata
                cursor.execute("SELECT name, subname, rarity, image_url FROM characters WHERE code = %s", (code,))
                existing = cursor.fetchone()
                if not existing:
                    print(f"[WARNING] Character '{code}' not found. Skipping.")
                    continue

                name = existing["name"]
                subname = existing.get("subname", "")
                rarity = existing["rarity"]
                image_url = existing["image_url"]

                cursor.execute("""
                    INSERT INTO characters (code, name, subname, rarity, image_url)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (code) DO NOTHING
                """, (code, name, subname, rarity, image_url))

                cursor.execute("UPDATE characters SET pick_count = pick_count + 1 WHERE code = %s", (code,))
                cursor.execute(
                    sql.SQL("UPDATE characters SET e{}_uses = e{}_uses + 1 WHERE code = %s").format(
                        sql.Literal(eid), sql.Literal(eid)
                    ),
                    (code,)
                )
                if team_won:
                    cursor.execute(
                        sql.SQL("UPDATE characters SET e{}_wins = e{}_wins + 1 WHERE code = %s").format(
                            sql.Literal(eid), sql.Literal(eid)
                        ),
                        (code,)
                    )

        for team_key in ["blue_bans", "red_bans"]:
            bans = match_data.get(team_key, [])
            for ban in bans:
                code = ban["code"]
                all_codes.add(code)

                cursor.execute("SELECT name, subname, rarity, image_url FROM characters WHERE code = %s", (code,))
                existing = cursor.fetchone()
                if not existing:
                    print(f"[WARNING] Character '{code}' not found. Skipping.")
                    continue

                name = existing["name"]
                subname = existing.get("subname", "")
                rarity = existing["rarity"]
                image_url = existing["image_url"]

                cursor.execute("""
                    INSERT INTO characters (code, name, subname, rarity, image_url)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (code) DO NOTHING
                """, (code, name, subname, rarity, image_url))

                cursor.execute("UPDATE characters SET ban_count = ban_count + 1 WHERE code = %s", (code,))
            
        for code in match_data.get("prebans", []):
            all_codes.add(code)
            cursor.execute("UPDATE characters SET preban_count = preban_count + 1 WHERE code = %s", (code,))

        for code in match_data.get("jokers", []):
            all_codes.add(code)
            cursor.execute("UPDATE characters SET joker_count = joker_count + 1 WHERE code = %s", (code,))

        for code in all_codes:
            cursor.execute("UPDATE characters SET appearance_count = appearance_count + 1 WHERE code = %s", (code,))


def get_match_distribution():
    with get_cursor() as cursor: 
            cursor.execute("""
                SELECT 
                    COUNT(*) FILTER (WHERE jsonb_array_length(raw_data->'prebans') = 0) AS preban_0,
                    COUNT(*) FILTER (WHERE jsonb_array_length(raw_data->'prebans') = 1) AS preban_1,
                    COUNT(*) FILTER (WHERE jsonb_array_length(raw_data->'prebans') = 2) AS preban_2,
                    COUNT(*) FILTER (
                        WHERE jsonb_array_length(raw_data->'prebans') = 3 AND COALESCE(jsonb_array_length(raw_data->'jokers'), 0) = 0
                    ) AS preban_3_joker_0,
                    COUNT(*) FILTER (
                        WHERE jsonb_array_length(raw_data->'prebans') = 3 AND COALESCE(jsonb_array_length(raw_data->'jokers'), 0) = 1
                    ) AS preban_3_joker_1,
                    COUNT(*) FILTER (
                        WHERE jsonb_array_length(raw_data->'prebans') = 3 AND COALESCE(jsonb_array_length(raw_data->'jokers'), 0) = 2
                    ) AS preban_3_joker_2,
                    COUNT(*) FILTER (
                        WHERE jsonb_array_length(raw_data->'prebans') = 3 AND COALESCE(jsonb_array_length(raw_data->'jokers'), 0) = 3
                    ) AS preban_3_joker_3,
                    COUNT(*) FILTER (
                        WHERE jsonb_array_length(raw_data->'prebans') = 3 AND COALESCE(jsonb_array_length(raw_data->'jokers'), 0) = 4
                    ) AS preban_3_joker_4,
                    COUNT(*) FILTER (
                        WHERE jsonb_array_length(raw_data->'prebans') = 3 AND COALESCE(jsonb_array_length(raw_data->'jokers'), 0) >= 5
                    ) AS preban_3_joker_5plus
                FROM matches
                WHERE has_character_data = TRUE
            """)
            return cursor.fetchone()

