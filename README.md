#  Cipher PvP Discord Bot

>  Designed for character-based gacha RPGs such as **Honkai: Star Rail**, **Genshin Impact**, **Wuthering Waves**, **Zenless Zone Zero**, and similar titles — any game where players build rosters, compete in PvP, and rely on detailed stat tracking.

A modular Discord bot powering the full Cipher PvP ecosystem: interactive match submission, ELO ranking, character statistics, roster card generation, matchmaking queues, tournaments, and automated Discord rank roles — all backed by PostgreSQL and JSON storage.

![Python](https://img.shields.io/badge/Python-3.10+-blue)
![discord.py](https://img.shields.io/badge/discord.py-2.x-blue)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-asyncpg/psycopg2-blue)

---

## 🚀 Overview

The **Cipher PvP Bot** serves as the automation backbone for the Cipher PvP community and integrates tightly with the Cipher.uno platform.

The bot handles:

- Interactive match submission with live ELO calculation  
- Player rankings and Discord role assignment  
- Character performance analytics (win/pick/ban/joker/appearance)  
- Match history and player summaries  
- Tournament submissions and archive  
- Roster card image generation (PIL-based)  
- Queue-style matchmaking with automatic team formation  
- Player profile customization (description, banner, profile color)  
- Cached external API usage for character/roster metadata  

This README includes **the full module-by-module documentation**, so you can understand every part of the bot in one file.

---

#  Project Structure 

```text
pvpbot/
│
├── bot.py                  # Bot entry point
├── requirements.txt        # Dependencies
├── Procfile                # For hosting 
│
├── commands/            
│   ├── __init__.py
│   ├── admin_commands.py
│   ├── character_stats.py
│   ├── elo_commands.py
│   ├── fun_commands.py
│   ├── help.py
│   ├── history_commands.py
│   ├── matchmaking.py
│   ├── queue.py
│   ├── roster.py
│   ├── shared_cache.py
│   ├── sync.py
│   └── tournament.py
│
└── utils/                 
    ├── __init__.py
    ├── db_utils.py
    ├── rank_utils.py
    └── views.py
```


#  Command Modules (Detailed Documentation)

Below is a full breakdown of every command module in the project, what it contains, and what it does.

---

## **admin_commands.py**
Admin-only utilities for managing the ELO ecosystem and leaderboard.

**Features include:**
- Modify player ELO directly  
- Apply rating boosts or nerfs  
- Reset system statistics  
- Show match distribution analytics  
- Refresh or repost leaderboard    
- Owner-protected using `OWNER_ID`

Used for maintenance, debugging, and manual overrides.

---

## **character_stats.py**
Connects to **PostgreSQL** via `asyncpg` to fetch real per-character PvP analytics.

**Commands:**

### `/stats`
Shows **top 10 characters**, with switchable buttons for:
- Win rate  
- Pick rate  
- Ban rate  
- Preban  
- Joker  
- Appearance  
- Lose rate  

Uses a `discord.ui.View` to update the embed dynamically without new commands.

### `/unit-info`
Provides a deep dive into a character’s:
- Wins / losses  
- Pick & ban counts  
- E0–E6 usage  
- Appearance %  
- Historical performance  

Backed entirely by the database.

---

## **elo_commands.py**
The main **match submission engine**.

### `/submit-match`
Runs a multi-step interactive flow:
1. Select players  
2. Choose winner  
3. Preview ELO changes  
4. Confirm or cancel through buttons  
5. Writes results to:
   - `elo_data.json`  
   - `match_history.json`  
   - PostgreSQL character stats (E0–E6, picks, bans, wins, etc.)

Uses interactive UI from `utils.views`.

---

## **fun_commands.py**
Lightweight prefix commands.

Examples:
- `!winddd`
- `!xiangling`
- `!e2herta`

These have:
- cooldowns  
- playful responses  
- minimal logic  

Purely for fun and community engagement.

---

## **help.py**
### `/help`
Displays a beautiful help embed containing:
- A categorized list of bot commands  
- Short explanations for each  
- Themed visuals consistent with Cipher PvP branding  

---

## **history_commands.py**
### `/match-history`
Searches `match_history.json` for matches involving a user.

Displays:
- Date  
- Opponents  
- Teammates  
- Win/loss  
- Summary of the match  

Handles missing/invalid entries gracefully.

---

## **matchmaking.py**
Provides:
- **Player profile customization**
- **Roster metadata fetching**
- **Shared caching utilities**

### Profile Customization
Users can set:
- Profile description  
- Banner image  
- Profile card color  

Validated via Discord modals.

### Metadata integration
Fetches roster & character data from:
- External API (`ROSTER_API`)
- Shared cache layer (`shared_cache.py`)

---

## **queue.py**
A full PvP **matchmaking queue system**.

### Commands:
- `/joinqueue`
- `/leavequeue`
- `/queue`
- `/clearqueue`

### Features:
- Ordered queue system  
- AFK/inactivity detection  
- Auto team formation  
- Voice channel monitoring  
- **PIL-based matchcards** showing the final match teams  

Includes:
- Font loading
- Image drawing helpers
- Queue management & cleanup

---

## **roster.py**
Generates a **visual roster card** for any player.

### `/roster`
- Fetches roster info from DB & API  
- Loads character images  
- Draws grid layout with:
  - Rarity borders  
  - Eidolon badges  
  - Portrait halos / effects  

Utilizes cached assets for performance (via `shared_cache.py`).

---

## **shared_cache.py**
A lightweight cache module storing:
- Character metadata (`char_map_cache`)  
- Icon images (`icon_cache`)  

Used by:
- `roster.py`
- `matchmaking.py`

Improves speed by avoiding duplicate API calls or reloading images.

---

## **sync.py**
### `/sync_ranks`
Recomputes rank roles for all guild members.

- Pulls ELO data  
- Determines rank using `rank_utils.py`  
- Identifies top 3 players → gives **Cipher Champion**  
- Removes outdated roles  
- Adds updated ones  
- Includes an announcement modal  

Admin-only.

---

## **tournament.py**
Handles submission and archival of tournament results.

### `/tournament-submit`
Stores:
- Tournament name  
- Winners list  
- Timestamp  

### `/tournament-archive`
Retrieves and displays historical tournament data.

Uses:
- `asyncpg` for reading  
- `psycopg2` for writing  
(maintained for legacy compatibility)

---

#  Utils Modules

---

## **db_utils.py**
The MOST important backend file.

Handles:

### JSON operations
- Load/save ELO (`elo_data.json`)
- Load/save match history (`match_history.json`)

### PostgreSQL operations
- Character stat updates (picks, bans, wins, E-level usage)
- Season-based tables  
- Player initialization  
- Match rollback system  
- Transaction-safe writes  

### Rollback Engine
Fully reverses:
- ELO changes  
- Character stat changes  
- Match history entries  

Ensures your ecosystem stays consistent.

---

## **rank_utils.py**
Defines how ranks are calculated and assigned.

### `get_rank()`
Converts ELO to rank tier

### `update_rank_role()`
- Removes outdated Discord roles  
- Adds new ones  
- Handles Cipher Champion priority  

---

## **views.py**
Contains all `discord.ui.View` components used during:

- Match submission  
- ELO confirmation  
- Tiebreaker resolution  
- Undo confirmation  
- Error-handling flows  

Used by `elo_commands.py` to build full interactive UI experiences.

---

#  End of Command Module Documentation

