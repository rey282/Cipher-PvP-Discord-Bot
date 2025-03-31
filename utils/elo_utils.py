import os
import json
import logging
from datetime import datetime

# Set up logging
logging.basicConfig(filename='elo.log', level=logging.INFO)

ELO_FILE = "elo_data.json"
MATCH_HISTORY_FILE = "match_history.json"

def rollback_last_match():
    """Rollback the most recent match and return success status."""
    try:
        history = load_match_history()
        
        # Validate history is a list and not empty
        if not isinstance(history, list) or len(history) == 0:
            return False, "Oh, it seems there are no matches to revert, or the history format is incorrect."

        # Get most recent match (first item in list)
        last_match = history[0]
        
        # Validate match structure
        if not isinstance(last_match, dict) or 'elo_gains' not in last_match:
            return False, "The match data seems to be malformed. Please ensure it's formatted correctly."

        elo_data = load_elo_data()
        changes_made = False

        # Revert ELO changes for all players
        for player_id, gain in last_match['elo_gains'].items():
            if str(player_id) in elo_data:  # Ensure player_id is string
                changes_made = True
                player_data = elo_data[str(player_id)]
                player_data['elo'] -= gain
                games = player_data['games_played'] - 1
                player_data['games_played'] = max(0, games)

                # Recalculate win rate
                if games > 0:
                    current = player_data['win_rate']
                    if gain > 0:  # Was winner
                        player_data['win_rate'] = ((current * (games + 1)) - 1) / games
                    else:  # Was loser
                        player_data['win_rate'] = (current * (games + 1)) / games
                else:
                    player_data['win_rate'] = 0.0

        if changes_made:
            # Remove the match from history
            updated_history = history[1:] if len(history) > 1 else []
            
            # Save changes
            save_elo_data(elo_data)
            
            # Save updated history
            with open(MATCH_HISTORY_FILE, 'w', encoding='utf-8') as f:
                json.dump(updated_history, f, indent=4, ensure_ascii=False)
            
            return True
            
        return False
        
    except Exception as e:
        logging.error(f"Rollback failed: {str(e)}", exc_info=True)
        return False, f"Error during rollback: {str(e)}"

def save_match_history(match_data):
    """Save match data with proper structure including ELO gains"""
    history = load_match_history()
    
    # Ensure history is a list
    if not isinstance(history, list):
        history = []
    
    # Prepare the properly structured match data
    formatted_match = {
        "date": datetime.now().strftime("%d/%m/%Y"),
        "blue_team": [
            {
                "id": str(player['id']),
                "name": player['name'],
                "cycles": player['cycles']
            } for player in match_data['blue_team']
        ],
        "red_team": [
            {
                "id": str(player['id']),
                "name": player['name'],
                "cycles": player['cycles']
            } for player in match_data['red_team']
        ],
        "blue_score": match_data['blue_score'],
        "red_score": match_data['red_score'],
        "blue_penalty": match_data.get('blue_penalty', 0),
        "red_penalty": match_data.get('red_penalty', 0),
        "winner": match_data['winner'],
        "elo_gains": match_data.get('elo_gains', {})  # Add this line
    }
    
    # Add to beginning of history (newest first)
    history.insert(0, formatted_match)
    
    # Save to file
    with open(MATCH_HISTORY_FILE, 'w', encoding='utf-8') as f:
        json.dump(history, f, indent=4, ensure_ascii=False)

def load_match_history():
    """Load match history from JSON file. Returns a list of matches."""
    if not os.path.exists(MATCH_HISTORY_FILE):
        return []
    
    try:
        with open(MATCH_HISTORY_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            
            # Handle all possible cases of loaded data
            if data is None:
                return []
            if isinstance(data, list):
                return data
            if isinstance(data, dict):
                # Convert single match dict to list
                return [data]
            
            # If we get here, the data format is unexpected
            logging.error(f"Unexpected match history format: {type(data)}")
            return []
            
    except Exception as e:
        logging.error(f"Error loading match history: {e}")
        return []

def load_elo_data():
    """Load ELO data from JSON file. Returns empty dict if file is missing/corrupt."""
    if os.path.exists(ELO_FILE):
        if os.stat(ELO_FILE).st_size == 0:
            print("Warning: JSON file is empty. Initializing with empty data.")
            return {}

        with open(ELO_FILE, "r", encoding="utf-8") as f:
            try:
                return json.load(f)
            except json.JSONDecodeError:
                print("Error: Invalid JSON format. Initializing with empty data.")
                return {}
    return {}

def save_elo_data(data):
    """Save ELO data to JSON file with indentation."""
    with open(ELO_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

def initialize_player_data(player_id=None, uid="Not Registered"):
    """Initialize new player data with defaults. Preserves UID if provided."""
    return {
        "elo": 200,          # Default ELO
        "win_rate": 0.0,     # Default win rate
        "games_played": 0,   # Track total matches
        "uid": uid           # Linked in-game UID
    }

def calculate_team_elo_change(
    winner_avg_elo: float,
    loser_avg_elo: float,
    base_gain: float = 20,
    base_loss: float = 20,
    variance_gain: float = 1.0,
    variance_loss: float = 0.85
):
    """Returns total team gain for winners and loss for losers."""
    ratio = loser_avg_elo / winner_avg_elo
    per_player_gain = base_gain * variance_gain * ratio
    per_player_loss = base_loss * variance_loss * ratio
    return per_player_gain, per_player_loss


def distribute_team_elo_change(team, per_player_change, elo_data, gain=True):
    print("[DEBUG] >>> ENTERED distribute_team_elo_change FUNCTION <<<")
    seen_ids = set()
    changes = {}

    original_elos = {
        str(player.id): elo_data.get(str(player.id), {"elo": 200})["elo"]
        for player in team
    }
    print("[DEBUG] === ORIGINAL ELO SNAPSHOT ===")
    for pid, elo in original_elos.items():
        print(f"[DEBUG] Player ID: {pid} | Original ELO: {elo}")

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

            print(f"[DEBUG] Processing {player.display_name} ({player_id})")
            print(f"         Original ELO: {player_elo}")
            print(f"         Teammate: {teammate.display_name} ({teammate_id})")
            print(f"         Teammate ELO: {teammate_elo}")
            print(f"         Calculated Ratio: {ratio:.4f}")
            print(f"         Per-Player Base Change: {per_player_change}")
            print(f"         Final Individual Change: {individual_change:.4f}")
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

        changes[player_id] = round(individual_change if gain else -individual_change, 2)

    return changes



