import discord
import asyncio
import logging
from discord import ui
from discord import Interaction
from discord import Embed
from datetime import datetime
from utils.rank_utils import update_rank_role, get_rank
from utils.db_utils import ( 
    save_elo_data, 
    load_elo_data, 
    save_match_history,
    rollback_match,
    calculate_team_elo_change,
    update_character_table_stats
)
logging.basicConfig(level=logging.DEBUG)
class UpdateEloView(ui.View):
    def __init__(self, blue_team, red_team, blue_scores, red_scores, blue_cycle_penalty, red_cycle_penalty, allowed_user_id, match_data):
        super().__init__(timeout=300)
        self.blue_team = blue_team
        self.red_team = red_team
        self.blue_scores = blue_scores
        self.red_scores = red_scores
        self.blue_cycle_penalty = blue_cycle_penalty
        self.red_cycle_penalty = red_cycle_penalty
        self.allowed_user_id = allowed_user_id
        self.elo_data = load_elo_data()
        self.elo_gains={}
        self.match_data = match_data

    async def interaction_check(self, interaction: Interaction) -> bool:
        if interaction.user.id != self.allowed_user_id:
            await interaction.response.send_message(
                "<:Unamurice:1349309283669377064> I’m sorry, but you’re not allowed to interact with this…\n"
                "I must respectfully ask for your understanding.",
                ephemeral=True
            )
            return False
        return True

    @ui.button(label="Submit", style=discord.ButtonStyle.green)
    async def submit(self, interaction: discord.Interaction, button: discord.ui.Button):
        for child in self.children:
            child.disabled = True
        await interaction.response.defer()
        await interaction.message.edit(view=self)

        blue_total_score = sum(self.blue_scores) + self.blue_cycle_penalty
        red_total_score = sum(self.red_scores) + self.red_cycle_penalty

        blue_points = self.match_data.get("blue_points", 0)
        red_points = self.match_data.get("red_points", 0)

        if blue_total_score < red_total_score:
            winner = "Blue Team"
            winner_team = self.blue_team
            winner_scores = self.blue_scores
            loser_team = self.red_team
            loser_scores = self.red_scores
        elif red_total_score < blue_total_score:
            winner = "Red Team"
            winner_team = self.red_team
            winner_scores = self.red_scores
            loser_team = self.blue_team
            loser_scores = self.blue_scores
        else:
            # Cycle clear is tied, check points
            if blue_points < red_points:
                winner = "Blue Team"
                winner_team = self.blue_team
                winner_scores = self.blue_scores
                loser_team = self.red_team
                loser_scores = self.red_scores
            elif red_points < blue_points:
                winner = "Red Team"
                winner_team = self.red_team
                winner_scores = self.red_scores
                loser_team = self.blue_team
                loser_scores = self.blue_scores
            else:
                # Both cycle clear and points are tied - show tiebreaker
                tiebreaker_view = TiebreakerView(
                    blue_team=self.blue_team,
                    red_team=self.red_team,
                    blue_scores=self.blue_scores,
                    red_scores=self.red_scores,
                    blue_cycle_penalty=self.blue_cycle_penalty,
                    red_cycle_penalty=self.red_cycle_penalty,
                    blue_total_score=blue_total_score,
                    red_total_score=red_total_score,
                    elo_gains=self.elo_gains,
                    allowed_user_id=interaction.user.id,
                    match_data=self.match_data
                )
                message = await interaction.followup.send(
                    "The threads of fate have tied these teams in both cycles and points...\n"
                    "Which side shall be favored by destiny? Please, choose with care.",
                    view=tiebreaker_view
                )
                tiebreaker_view.message = message
                return

        processed_ids = set()
        self.elo_gains = {}

        all_players = winner_team + loser_team
        all_scores = winner_scores + loser_scores
        avg_team_cycle = (sum(self.blue_scores) + sum(self.red_scores)) / len(all_players)

        # Get average ELO for each team
        winner_elos = [self.elo_data.get(str(p.id), {"elo": 200})["elo"] for p in winner_team]
        loser_elos = [self.elo_data.get(str(p.id), {"elo": 200})["elo"] for p in loser_team]
        avg_winner_elo = sum(winner_elos) / len(winner_elos)
        avg_loser_elo = sum(loser_elos) / len(loser_elos)

        base_gain = 25
        base_loss = 20
        variance_gain = 1.5
        variance_loss = 0.65

        self.elo_gains = calculate_team_elo_change(
            winning_team=winner_team,
            losing_team=loser_team,
            elo_data=self.elo_data,
            base_gain=25,
            base_loss=20,
            variance_gain=1.5,
            variance_loss=0.65
        )
        save_elo_data(self.elo_data)

        await asyncio.to_thread(
            update_character_table_stats,
            self.match_data,
            winning_team=self.match_data["winner"]
        )

        match_data = {
            "date": datetime.now().strftime("%d/%m/%Y"),
            "blue_team": [{"id": str(p.id), "name": p.display_name, "cycles": s} for p, s in zip(self.blue_team, self.blue_scores)],
            "red_team": [{"id": str(p.id), "name": p.display_name, "cycles": s} for p, s in zip(self.red_team, self.red_scores)],
            "blue_score": blue_total_score,
            "red_score": red_total_score,
            "blue_penalty": self.blue_cycle_penalty,
            "red_penalty": self.red_cycle_penalty,
            "winner": "blue" if winner_team == self.blue_team else "red",
            "elo_gains": self.elo_gains,
            "blue_picks": self.match_data["blue_picks"],
            "red_picks": self.match_data["red_picks"],
            "blue_bans": self.match_data["blue_bans"],
            "red_bans": self.match_data["red_bans"],
            "prebans": self.match_data.get("prebans", []),
            "jokers": self.match_data.get("jokers", [])
        }

        save_match_history(match_data)
        self.elo_data = load_elo_data()

        embed = discord.Embed(
            title="Threads of Victory",
            color=discord.Color.blue() if blue_total_score < red_total_score else discord.Color.red()
        )
        embed.add_field(
            name="Blue Team",
            value=f"{self.blue_team[0].display_name} ({self.blue_scores[0]}c)\n{self.blue_team[1].display_name} ({self.blue_scores[1]}c)",
            inline=False
        )
        embed.add_field(
            name="Red Team",
            value=f"{self.red_team[0].display_name} ({self.red_scores[0]}c)\n{self.red_team[1].display_name} ({self.red_scores[1]}c)",
            inline=False
        )
        embed.add_field(name="Total Scores", value=f"{blue_total_score} vs {red_total_score}", inline=False)
        embed.add_field(name="Winner", value=winner, inline=False)

        elo_changes_text = "\n".join(
            f"<@{player_id}>: {'+' if gain >= 0 else ''}{gain:.2f} ELO" if gain != 0 else f"<@{player_id}>: No change"
            for player_id, gain in sorted(self.elo_gains.items())
        )

        embed.add_field(
            name="ELO Changes",
            value=elo_changes_text or "No changes to the threads...",
            inline=False
        )

        match_id = save_match_history(match_data)
        confirm_view = ConfirmRollbackView(match_id=match_id)

        await interaction.followup.send(embed=embed, view=confirm_view)

        await asyncio.sleep(1)

        for player_id, change in self.elo_gains.items():
            member = interaction.guild.get_member(int(player_id))
            if member:
                previous_elo = self.elo_data[str(player_id)]["elo"] - change
                old_rank = get_rank(previous_elo, player_id=member.id, elo_data=self.elo_data)

                new_elo = self.elo_data[str(player_id)]["elo"]
                new_rank = get_rank(new_elo, player_id=member.id, elo_data=self.elo_data)

                await update_rank_role(
                    member,
                    new_elo,
                    self.elo_data,
                    channel=interaction.channel,
                    announce_demotions=True,
                    force_old_rank=old_rank 
                )


    @ui.button(label="Cancel", style=discord.ButtonStyle.red)
    async def cancel(self, interaction: Interaction, button: ui.Button):
        await interaction.response.send_message("❌ Match update canceled.", ephemeral=False)
        self.stop()

class TiebreakerView(ui.View):
    def __init__(self, blue_team, red_team, blue_scores, red_scores, blue_cycle_penalty, red_cycle_penalty, blue_total_score, red_total_score, elo_gains, allowed_user_id, match_data):
        super().__init__(timeout=300)
        self.blue_team = blue_team
        self.red_team = red_team
        self.blue_scores = blue_scores
        self.red_scores = red_scores
        self.blue_cycle_penalty = blue_cycle_penalty
        self.red_cycle_penalty = red_cycle_penalty
        self.blue_total_score = blue_total_score  
        self.red_total_score = red_total_score
        self.elo_gains = elo_gains
        self.allowed_user_id = allowed_user_id
        self.elo_data = load_elo_data()
        self.match_data = match_data
        self.message = None


    async def interaction_check(self, interaction: Interaction) -> bool:
        if interaction.user.id != self.allowed_user_id:
            await interaction.response.send_message(
                "<:Unamurice:1349309283669377064> I’m sorry, but you’re not allowed to interact with this…\n"
                "I must respectfully ask for your understanding.",
                ephemeral=True
            )
            return False
        return True

    @ui.button(label="Blue Team Won", style=discord.ButtonStyle.blurple)
    async def red_side_pick(self, interaction: Interaction, button: ui.Button):
        try:
            await interaction.response.defer()
        except discord.NotFound:
            print("Interaction expired.")
            return
        
        for item in self.children:
            item.disabled = True
        await interaction.message.edit(view=self)

        await self.handle_tiebreaker(interaction, winner_team=self.blue_team, loser_team=self.red_team) 
        self.stop()  

    @ui.button(label="Red Team Won", style=discord.ButtonStyle.red)
    async def blue_side_pick(self, interaction: Interaction, button: ui.Button):
        try:
            await interaction.response.defer()
        except discord.NotFound:
            print("Interaction expired.")
            return

        for item in self.children:
            item.disabled = True
        await interaction.message.edit(view=self)

        await self.handle_tiebreaker(interaction, winner_team=self.red_team, loser_team=self.blue_team)
        self.stop()

    async def handle_tiebreaker(self, interaction: Interaction, winner_team, loser_team):
        if not interaction.response.is_done():
            await interaction.response.defer()
        processed_ids = set()
        self.elo_gains = {}

        winner_scores = self.blue_scores if winner_team == self.blue_team else self.red_scores
        loser_scores = self.red_scores if loser_team == self.red_team else self.blue_scores

        avg_team_cycle = (sum(self.blue_scores) + sum(self.red_scores)) / (len(winner_team) + len(loser_team))

        winner_elos = [self.elo_data.get(str(p.id), {"elo": 200})["elo"] for p in winner_team]
        loser_elos = [self.elo_data.get(str(p.id), {"elo": 200})["elo"] for p in loser_team]
        avg_winner_elo = sum(winner_elos) / len(winner_elos)
        avg_loser_elo = sum(loser_elos) / len(loser_elos)

        self.elo_gains = calculate_team_elo_change(
            winning_team=winner_team,
            losing_team=loser_team,
            elo_data=self.elo_data,
            base_gain=25,
            base_loss=20,
            variance_gain=1.5,
            variance_loss=0.65
        )
        save_elo_data(self.elo_data)

        await asyncio.to_thread(
            update_character_table_stats,
            self.match_data,
            winning_team=self.match_data["winner"]
        )

        match_data = {
            "date": datetime.now().strftime("%d/%m/%Y"),
            "blue_team": [
                {"id": str(p.id), "name": p.display_name, "cycles": s} 
                for p, s in zip(self.blue_team, self.blue_scores)
            ],
            "red_team": [
                {"id": str(p.id), "name": p.display_name, "cycles": s} 
                for p, s in zip(self.red_team, self.red_scores)
            ],
            "blue_score": sum(self.blue_scores) + self.blue_cycle_penalty,
            "red_score": sum(self.red_scores) + self.red_cycle_penalty,
            "blue_penalty": self.blue_cycle_penalty,
            "red_penalty": self.red_cycle_penalty,
            "winner": "blue" if winner_team == self.blue_team else "red",
            "elo_gains": self.elo_gains,
            "blue_picks": self.match_data["blue_picks"],
            "red_picks": self.match_data["red_picks"],
            "blue_bans": self.match_data["blue_bans"],
            "red_bans": self.match_data["red_bans"],
            "prebans": self.match_data.get("prebans", []),
            "jokers": self.match_data.get("jokers", [])
        }

        save_match_history(match_data)
        self.elo_data = load_elo_data()

        embed = Embed(
            title="Tiebreaker Results: Fate Has Decided",
            color=discord.Color.blue() if winner_team == self.blue_team else discord.Color.red()
        )
        embed.add_field(
            name="Blue Team",
            value=f"{self.blue_team[0].display_name} ({self.blue_scores[0]}c) & {self.blue_team[1].display_name} ({self.blue_scores[1]}c)",
            inline=False
        )
        embed.add_field(
            name="Red Team",
            value=f"{self.red_team[0].display_name} ({self.red_scores[0]}c) & {self.red_team[1].display_name} ({self.red_scores[1]}c)",
            inline=False
        )
        embed.add_field(
            name="Total Scores",
            value=(
                f"Blue: {sum(self.blue_scores)} + {self.blue_cycle_penalty} penalty = {sum(self.blue_scores) + self.blue_cycle_penalty}\n"
                f"Red: {sum(self.red_scores)} + {self.red_cycle_penalty} penalty = {sum(self.red_scores) + self.red_cycle_penalty}"
            ),
            inline=False
        )
        embed.add_field(
            name="Winner",
            value="Blue Team" if winner_team == self.blue_team else "Red Team",
            inline=False
        )

        elo_changes_text = "\n".join(
            f"<@{player_id}>: {'+' if gain >= 0 else ''}{gain:.2f} ELO" if gain != 0 else f"<@{player_id}>: No change"
            for player_id, gain in sorted(self.elo_gains.items())
        )

        embed.add_field(
            name="ELO Changes",
            value=elo_changes_text or "No changes to the threads...",
            inline=False
        )

        match_id = save_match_history(match_data)
        confirm_view = ConfirmRollbackView(match_id=match_id)

        if interaction.response.is_done():
            await interaction.followup.send(embed=embed, view=confirm_view)
        else:
            await interaction.response.send_message(embed=embed, view=confirm_view)

        await asyncio.sleep(1)

        for player_id, change in self.elo_gains.items():
            member = interaction.guild.get_member(int(player_id))
            if member:
                previous_elo = self.elo_data[str(player_id)]["elo"] - change
                old_rank = get_rank(previous_elo, player_id=member.id, elo_data=self.elo_data)

                new_elo = self.elo_data[str(player_id)]["elo"]
                new_rank = get_rank(new_elo, player_id=member.id, elo_data=self.elo_data)

                await update_rank_role(
                    member,
                    new_elo,
                    self.elo_data,
                    channel=interaction.channel,
                    announce_demotions=True,
                    force_old_rank=old_rank 
                )
        
        self.stop()

class ConfirmRollbackView(discord.ui.View):
    def __init__(self, match_id: int):
        super().__init__(timeout=None)
        self.match_id = match_id  # ✅ Store match ID for targeted rollback
        self.confirmation_active = False
        self.message = None

    @discord.ui.button(label="⚠️ Undo Match", style=discord.ButtonStyle.red)
    async def undo_callback(self, interaction: discord.Interaction, button: discord.ui.Button):
        required_role = "Stonehearts" 

        # 🔐 Permission check
        if not interaction.user.guild_permissions.administrator and not any(role.name == required_role for role in interaction.user.roles):
            await interaction.response.send_message(
                "Oh… I’m afraid only administrators can undo matches. I apologize for the inconvenience.",
                ephemeral=True
            )
            return

        if self.confirmation_active:
            await interaction.response.send_message(
                "Oh, it seems a confirmation is already pending... Please give it a moment, and then you may proceed.",
                ephemeral=True
            )
            return

        self.confirmation_active = True
        # ✅ Pass match_id to ConfirmUndoView
        confirm_view = ConfirmUndoView(parent_view=self, match_id=self.match_id)

        try:
            # Disable all buttons in this view
            for item in self.children:
                item.disabled = True
            await interaction.message.edit(view=self)

            # Show confirmation prompt
            await interaction.response.send_message(
                "⚠️ This action will permanently revert the match you just submitted... Are you sure?",
                view=confirm_view,
                ephemeral=True
            )
            confirm_view.message = await interaction.original_response()
        except Exception as e:
            self.confirmation_active = False
            logging.error(f"Initial response failed: {e}")
            raise


class ConfirmUndoView(discord.ui.View):
    def __init__(self, parent_view: discord.ui.View, match_id: int):
        super().__init__(timeout=300)
        self.parent_view = parent_view
        self.match_id = match_id
        self.message = None

    @discord.ui.button(label="CONFIRM UNDO", style=discord.ButtonStyle.danger)
    async def confirm_callback(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.response.is_done():
            try:
                await interaction.response.defer()
            except discord.NotFound:
                print("Interaction expired or already acknowledged.")
                return

        try:
            # ✅ Perform rollback of the specific match
            success, message = rollback_match(self.match_id)

            # Disable all buttons in this view
            for item in self.children:
                item.disabled = True

            # Disable all buttons in parent_view manually
            for item in self.parent_view.children:
                item.disabled = True

            # Update messages
            try:
                await interaction.edit_original_response(
                    content=f"✅ {message}" if success else f"❌ {message}",
                    view=self
                )
                if self.parent_view.message:
                    await self.parent_view.message.edit(view=self.parent_view)

                await interaction.channel.send(
                    f"✅ {interaction.user.mention} has gracefully undone the match. Fate has been restored."
                    if success else f"❌ {interaction.user.mention} tried to reverse the match, but it failed: `{message}`"
                )

                try:
                    await interaction.delete_original_response()
                except discord.NotFound:
                    pass
            except discord.NotFound:
                pass

        except Exception as e:
            logging.error(f"Rollback failed: {e}")
            await interaction.followup.send("❌ Something went wrong while trying to undo the match. Please try again shortly.", ephemeral=True)
        finally:
            self.parent_view.confirmation_active = False

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True
        try:
            if self.message:
                await self.message.edit(view=self)
        except discord.NotFound:
            pass
        self.parent_view.confirmation_active = False
