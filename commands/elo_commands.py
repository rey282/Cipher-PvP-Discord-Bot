import discord
import os
import json
from discord.ext import commands
from discord import ui
from discord import app_commands
from discord import Interaction, Embed, Color
from discord import Object
from utils.db_utils import load_elo_data, save_elo_data
from utils.views import UpdateEloView, TiebreakerView
from dotenv import load_dotenv

load_dotenv()

GUILD_ID = int(os.getenv("DISCORD_GUILD_ID"))

# --- PARSE SUBMISSION STRING ---
def parse_submission_string(submission: str):
    # Slot map by position
    slot_map = {
        1: ("blue_bans", 2),
        2: ("red_bans", 2),
        3: ("blue_picks", 4),
        4: ("red_picks", 4),
        5: ("red_picks", 4),
        6: ("blue_picks", 4),
        7: ("blue_bans", 2),
        8: ("red_bans", 2),
        9: ("red_picks", 4),
        10: ("blue_picks", 4),
        11: ("blue_picks", 4),
        12: ("red_picks", 4),
        13: ("red_picks", 4),
        14: ("blue_picks", 4),
        15: ("blue_picks", 4),
        16: ("red_picks", 4),
        17: ("red_picks", 4),
        18: ("blue_picks", 4),
        19: ("blue_picks", 4),
        20: ("red_picks", 4)
    }

    index = 0
    parsed = {
        "blue_bans": [], "red_bans": [],
        "blue_picks": [], "red_picks": []
    }

    for slot in range(1, 21):
        key, length = slot_map[slot]
        raw = submission[index:index + length]
        if length == 2:
            parsed[key].append({"code": raw})
        else:
            parsed[key].append({
                "code": raw[:2],
                "eidolon": int(raw[2]),
                "superimposition": int(raw[3])
            })
        index += length
        
    blue_first = int(submission[index:index+2])
    index += 2
    blue_second = int(submission[index:index+2])
    index += 2
    red_first = int(submission[index:index+2])
    index += 2
    red_second = int(submission[index:index+2])
    index += 2

    for name, value in zip(["blue_first", "blue_second", "red_first", "red_second"],
                           [blue_first, blue_second, red_first, red_second]):
        if value < 0 or value > 15:
            raise ValueError(
                f"U-Um… `{name}` was `{value}`, but only 0 to 15 cycles are allowed! "
                "I’m really sorry… could you double-check your code?"
            )

    blue_cycle_penalty = int(submission[index:index+2])
    index += 2
    red_cycle_penalty = int(submission[index:index+2])
    index += 2

    blue_time_penalty = int(submission[index:index+2])
    index += 2
    red_time_penalty = int(submission[index:index+2])
    index += 2

    blue_penalty = blue_cycle_penalty + blue_time_penalty
    red_penalty = red_cycle_penalty + red_time_penalty

    blue_points = int(submission[index:index+2])
    index += 2
    red_points = int(submission[index:index+2])
    index += 2

    side_selector = submission[index]  # 'b' or 'r'
    index += 1

    # Parse prebans and jokers
    split = submission[index:].split("|")
    prebans = [split[0][i:i + 2] for i in range(0, len(split[0]), 2)] if split and split[0] else []
    jokers = [split[1][i:i + 2] for i in range(0, len(split[1]), 2)] if len(split) > 1 else []

    total_blue_cycles = blue_first + blue_second + blue_penalty
    total_red_cycles = red_first + red_second + red_penalty

    if total_blue_cycles < total_red_cycles:
        winner = "blue"
    elif total_red_cycles < total_blue_cycles:
        winner = "red"
    else:
        # Cycle clear is tied, check points
        if blue_points > red_points:
            winner = "blue"
        elif red_points > blue_points:
            winner = "red"
        else:
            # Both cycle clear and points are tied
            winner = "tie"

    parsed.update({
        "blue_cycles": [blue_first, blue_second],
        "red_cycles": [red_first, red_second],
        "blue_penalty": blue_penalty,
        "red_penalty": red_penalty,
        "blue_points": blue_points,
        "red_points": red_points,
        "winner": winner,
        "prebans": prebans,
        "jokers": jokers,
        "total_blue_cycles": total_blue_cycles,
        "total_red_cycles": total_red_cycles,
        "side_selector": side_selector
    })

    return parsed

class EloCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="submit-match", description="Whisper the outcome... and I shall adjust the threads of fate (ELO).")
    @app_commands.guilds(GUILD_ID)
    @app_commands.describe(
        blue_player_1="Blue Team Player 1",
        blue_player_2="Blue Team Player 2",
        red_player_1="Red Team Player 1",
        red_player_2="Red Team Player 2",
        submission_string="Paste the code from the match website",
    )

    async def update_elo(
        self,
        interaction: Interaction,
        blue_player_1: discord.Member,
        blue_player_2: discord.Member,
        red_player_1: discord.Member,
        red_player_2: discord.Member,
        submission_string: str
    ):
        await interaction.response.defer()

        try:
            # Validate no duplicate players
            players = [blue_player_1, blue_player_2, red_player_1, red_player_2]
            if (blue_player_1 in [red_player_1, red_player_2]) or (blue_player_2 in [red_player_1, red_player_2]):
                await interaction.followup.send("<:Unamurice:1349309283669377064> U-Um… I think you might’ve listed the same soul on both teams... I’m sorry, but each thread must belong to just one side.", ephemeral=False)
                return
            try:
                data = parse_submission_string(submission_string)
            except ValueError as e:
                await interaction.followup.send(f"{e}", ephemeral=True)
                return
            data = parse_submission_string(submission_string)

            # Create an embed to display the results
            embed = discord.Embed(
                title="Threads of Fate: Match Summary",
                color=discord.Color.blue() if data["total_blue_cycles"] < data["total_red_cycles"] else discord.Color.red(),
                description="The threads have crossed... and a tale unfolds."
            )

            # Add Blue Team field
            embed.add_field(
                name="Blue Team",
                value=f"{blue_player_1.display_name} & {blue_player_2.display_name}\n"
                    f"Cycles: {data['blue_cycles'][0]} + {data['blue_cycles'][1]}\n"
                    f"Penalty: {data['blue_penalty']}\n"
                    f"Points: {data['blue_points']}",
                inline=False
            )

            # Add Red Team field
            embed.add_field(
                name="Red Team",
                value=f"{red_player_1.display_name} & {red_player_2.display_name}\n"
                    f"Cycles: {data['red_cycles'][0]} + {data['red_cycles'][1]}\n"
                    f"Penalty: {data['red_penalty']}\n"
                    f"Points: {data['red_points']}",
                inline=False
            )

            if data['total_blue_cycles'] < data['total_red_cycles']:
                embed.add_field(name="Victor", value="Blue Team — the tide favored them today.", inline=False)
            elif data['total_red_cycles'] < data['total_blue_cycles']:
                embed.add_field(name="Victor", value="Red Team — their resolve carved the path.", inline=False)
            else:
                # Cycle clear is tied, check points
                if data['blue_points'] < data['red_points']:
                    embed.add_field(
                        name="Victor", 
                        value="Blue Team — though cycles were equal, their superior points broke the tie.", 
                        inline=False
                    )
                elif data['red_points'] < data['blue_points']:
                    embed.add_field(
                        name="Victor", 
                        value="Red Team — though cycles were equal, their superior points broke the tie.", 
                        inline=False
                    )
                else:
                    # Both cycle clear and points are tied
                    embed.add_field(
                        name="Outcome", 
                        value="A perfect tie in both cycles and points... as if destiny itself hesitated.", 
                        inline=False
                    )

            embed.set_footer(text="Threads arranged with care… by Kyasutorisu")

            # Create view with buttons
            match_data = {
                "blue_team": [...],
                "red_team": [...],
                "blue_picks": data["blue_picks"],
                "red_picks": data["red_picks"],
                "blue_bans": data["blue_bans"],
                "red_bans": data["red_bans"],
                "winner": data["winner"],
                "elo_gains": {},  # to be filled later
                "blue_score": data["total_blue_cycles"],
                "red_score": data["total_red_cycles"],
                "blue_penalty": data["blue_penalty"],
                "red_penalty": data["red_penalty"],
                "prebans": data.get("prebans", []),
                "jokers": data.get("jokers", []),
                "blue_points": data["blue_points"],
                "red_points": data["red_points"]
            }

            view = UpdateEloView(
                blue_team=[blue_player_1, blue_player_2],
                red_team=[red_player_1, red_player_2],
                blue_scores=data['blue_cycles'],
                red_scores=data['red_cycles'],
                blue_cycle_penalty=data['blue_penalty'],
                red_cycle_penalty=data['red_penalty'],
                allowed_user_id=interaction.user.id,
                match_data=match_data
            )

            # Handle duplicate mentions
            mentioned_users = set()  # Use a set to avoid duplicate mentions
            mentioned_users.add(blue_player_1)
            if blue_player_2 != blue_player_1:  # Only add if it's a different user
                mentioned_users.add(blue_player_2)
            mentioned_users.add(red_player_1)
            if red_player_2 != red_player_1:  # Only add if it's a different user
                mentioned_users.add(red_player_2)

            # Create the mention string
            user_mentions = " ".join(user.mention for user in mentioned_users)
            message_content = f"{user_mentions}\nHave the threads been woven as intended...? If something feels off, I shall mend it with care."

            # Send the embed with buttons
            await interaction.followup.send(content=message_content, embed=embed, view=view)
            

        except Exception as e:
            print(f"A quiet fracture in update-elo command: {e}")
            await interaction.followup.send("I-I'm so sorry… something went wrong while adjusting the threads.\nPlease try again in a moment — I’ll stay right here.", ephemeral=True)

async def setup(bot):
    await bot.add_cog(EloCommands(bot))