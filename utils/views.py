import discord
import asyncio
from discord import ui
from discord import Interaction
from discord import Embed
from datetime import datetime
from utils.db_utils import ( 
    save_elo_data, 
    load_elo_data, 
    save_match_history,
    rollback_last_match,
    distribute_team_elo_change,
    calculate_team_elo_change 
)

class UpdateEloView(ui.View):
    def __init__(self, blue_team, red_team, blue_scores, red_scores, blue_cycle_penalty, red_cycle_penalty):
        super().__init__(timeout=None)
        self.blue_team = blue_team
        self.red_team = red_team
        self.blue_scores = blue_scores
        self.red_scores = red_scores
        self.blue_cycle_penalty = blue_cycle_penalty
        self.red_cycle_penalty = red_cycle_penalty
        self.elo_data = load_elo_data()
        self.elo_gains={}

    @ui.button(label="Submit", style=discord.ButtonStyle.green)
    async def submit(self, interaction: discord.Interaction, button: discord.ui.Button):
        for child in self.children:
            child.disabled = True
        await interaction.response.defer()
        await interaction.message.edit(view=self)

        blue_total_score = sum(self.blue_scores) + self.blue_cycle_penalty
        red_total_score = sum(self.red_scores) + self.red_cycle_penalty

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
            tiebreaker_view = TiebreakerView(
                blue_team=self.blue_team,
                red_team=self.red_team,
                blue_scores=self.blue_scores,
                red_scores=self.red_scores,
                blue_cycle_penalty=self.blue_cycle_penalty,
                red_cycle_penalty=self.red_cycle_penalty,
                blue_total_score=blue_total_score,
                red_total_score=red_total_score,
                elo_gains=self.elo_gains
            )
            await interaction.followup.send("Match is tied! Which team wins the tie breaker?", view=tiebreaker_view)
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

        base_gain = 20
        base_loss = 20
        variance_gain = 1.0
        variance_loss = 0.85

        per_player_gain, per_player_loss = calculate_team_elo_change(
            winner_avg_elo=avg_winner_elo,
            loser_avg_elo=avg_loser_elo,
            base_gain=base_gain,
            base_loss=base_loss,
            variance_gain=variance_gain,
            variance_loss=variance_loss
        )

        # Apply ELO changes
        winner_elo_changes = distribute_team_elo_change(winner_team, per_player_gain, self.elo_data, gain=True)
        loser_elo_changes = distribute_team_elo_change(loser_team, per_player_loss, self.elo_data, gain=False)

        # Combine for match record
        self.elo_gains = {**winner_elo_changes, **loser_elo_changes}

        save_elo_data(self.elo_data)

        match_data = {
            "date": datetime.now().strftime("%d/%m/%Y"),
            "blue_team": [{"id": str(p.id), "name": p.display_name, "cycles": s} for p, s in zip(self.blue_team, self.blue_scores)],
            "red_team": [{"id": str(p.id), "name": p.display_name, "cycles": s} for p, s in zip(self.red_team, self.red_scores)],
            "blue_score": blue_total_score,
            "red_score": red_total_score,
            "blue_penalty": self.blue_cycle_penalty,
            "red_penalty": self.red_cycle_penalty,
            "winner": "blue" if blue_total_score < red_total_score else "red" if red_total_score < blue_total_score else "tie",
            "elo_gains": self.elo_gains
        }

        save_match_history(match_data)

        embed = discord.Embed(
            title="Match Results",
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
            value=elo_changes_text or "No changes",
            inline=False
        )

        confirm_view = ConfirmRollbackView()
        await interaction.followup.send(embed=embed, view=confirm_view)

    @ui.button(label="Cancel", style=discord.ButtonStyle.red)
    async def cancel(self, interaction: Interaction, button: ui.Button):
        await interaction.response.send_message("❌ Match update canceled.", ephemeral=False)
        self.stop()

class TiebreakerView(ui.View):
    def __init__(self, blue_team, red_team, blue_scores, red_scores, blue_cycle_penalty, red_cycle_penalty, blue_total_score, red_total_score, elo_gains):
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
        self.elo_data = load_elo_data()

    @ui.button(label="Blue Team Won", style=discord.ButtonStyle.blurple)
    async def red_side_pick(self, interaction: Interaction, button: ui.Button):
        await self.handle_tiebreaker(interaction, winner_team=self.blue_team, loser_team=self.red_team)   

    @ui.button(label="Red Team Won", style=discord.ButtonStyle.red)
    async def blue_side_pick(self, interaction: Interaction, button: ui.Button):
        await self.handle_tiebreaker(interaction, winner_team=self.red_team, loser_team=self.blue_team)

    async def handle_tiebreaker(self, interaction: Interaction, winner_team, loser_team):
        processed_ids = set()
        self.elo_gains = {}

        winner_scores = self.blue_scores if winner_team == self.blue_team else self.red_scores
        loser_scores = self.red_scores if loser_team == self.red_team else self.blue_scores

        avg_team_cycle = (sum(self.blue_scores) + sum(self.red_scores)) / (len(winner_team) + len(loser_team))

        winner_elos = [self.elo_data.get(str(p.id), {"elo": 200})["elo"] for p in winner_team]
        loser_elos = [self.elo_data.get(str(p.id), {"elo": 200})["elo"] for p in loser_team]
        avg_winner_elo = sum(winner_elos) / len(winner_elos)
        avg_loser_elo = sum(loser_elos) / len(loser_elos)

        per_player_gain, per_player_loss = calculate_team_elo_change(
            winner_avg_elo=avg_winner_elo,
            loser_avg_elo=avg_loser_elo,
            base_gain=20,
            base_loss=20,
            variance_gain=1.0,
            variance_loss=0.85
        )

        winner_elo_changes = distribute_team_elo_change(winner_team, per_player_gain, self.elo_data, gain=True)
        loser_elo_changes = distribute_team_elo_change(loser_team, per_player_loss, self.elo_data, gain=False)

        self.elo_gains = {**winner_elo_changes, **loser_elo_changes}

        save_elo_data(self.elo_data)

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
            "elo_gains": self.elo_gains
        }

        save_match_history(match_data)

        embed = Embed(
            title="Match Results (Tiebreaker)",
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
            value=elo_changes_text or "No changes",
            inline=False
        )

        confirm_view = ConfirmRollbackView()
        if interaction.response.is_done():
            await interaction.followup.send(embed=embed, view=confirm_view)
        else:
            await interaction.response.send_message(embed=embed, view=confirm_view)
        self.stop()

class ConfirmRollbackView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)  # 5 minute timeout
        
    @discord.ui.button(label="⚠️ Undo Match", style=discord.ButtonStyle.red)
    async def undo_callback(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(
                "❌ Only administrators can undo matches!",
                ephemeral=True
            )
            return
            
        # Create a simple confirmation message instead of modal
        confirm_view = discord.ui.View(timeout=60)
        confirm_view.add_item(discord.ui.Button(
            style=discord.ButtonStyle.danger,
            label="CONFIRM UNDO",
            custom_id="confirm_undo"
        ))
        
        await interaction.response.send_message(
            "⚠️ This will permanently revert the last match! Click to confirm:",
            view=confirm_view,
            ephemeral=True
        )
        
        # Wait for confirmation
        try:
            confirm_interaction = await interaction.client.wait_for(
                "interaction",
                check=lambda i: (
                    i.data.get('custom_id') == "confirm_undo" and 
                    i.user.id == interaction.user.id
                ),
                timeout=60
            )
            
            # Perform rollback
            success, message = rollback_last_match()
            await confirm_interaction.response.send_message(
                f"✅ {message}" if success else f"❌ {message}",
                ephemeral=False
            )
            
            # Disable original button
            for item in self.children:
                item.disabled = True
            await interaction.message.edit(view=self)
            
        except asyncio.TimeoutError:
            await interaction.followup.send(
                "Undo confirmation timed out.",
                ephemeral=True
            )