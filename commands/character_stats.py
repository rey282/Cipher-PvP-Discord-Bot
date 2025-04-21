import discord
import asyncpg
import time
from datetime import date, datetime
from discord import app_commands, Interaction, Embed
from discord.ext import commands
from typing import List
import os
from dotenv import load_dotenv

load_dotenv()
POSTGRES_URL = os.getenv("DATABASE_URL")
GUILD_ID = int(os.getenv("DISCORD_GUILD_ID"))


class StatsView(discord.ui.View):
    def __init__(self, cog, mode, data, user_id):
        super().__init__(timeout=60)
        self.cog = cog
        self.mode = mode
        self.data = data
        self.user_id = user_id
        self.add_item(StatsButton("Win Rate", "winrate", mode == "winrate"))
        self.add_item(StatsButton("Pick Rate", "pickrate", mode == "pickrate"))
        self.add_item(StatsButton("Ban Rate", "banrate", mode == "banrate"))
        self.add_item(StatsButton("Preban", "prebanrate", mode == "prebanrate"))
        self.add_item(StatsButton("Joker", "jokerrate", mode == "jokerrate"))
        self.add_item(StatsButton("Appearance", "appearancerate", mode == "appearancerate"))
        self.add_item(StatsButton("Lose Rate", "loserate", mode == "loserate"))

    def get_embed(self):
        embed = discord.Embed(
            title=f"Top 10 Units by {self.mode.title().replace('rate', ' Rate')}",
            color=0xB197FC
        )
        for i, row in enumerate(self.data, start=1):
            rate = f"{round(row['rate'] * 100)}%" if row['rate'] is not None else "0%"
            embed.add_field(
                name=f"{i}. {row['name']}",
                value=f"{self.mode.title().replace('rate', ' Rate')}: {rate}",
                inline=False
            )
        embed.set_footer(text="Handled with love by Kyasutorisu")
        return embed


class StatsButton(discord.ui.Button):
    def __init__(self, label, mode, disabled=False):
        super().__init__(label=label, style=discord.ButtonStyle.primary, custom_id=mode, disabled=disabled)

    async def callback(self, interaction: discord.Interaction):
        view: StatsView = self.view
        if interaction.user.id != view.user_id:
            await interaction.response.send_message("A-ack, it seems like you can’t interact with this menu... P-please, use the appropriate command yourself to unlock the threads of fate!", ephemeral=True)
            return
        new_data = await view.cog.fetch_stats_data(mode=self.custom_id)
        new_view = StatsView(view.cog, self.custom_id, new_data)
        await interaction.response.edit_message(embed=new_view.get_embed(), view=new_view)


class UnitInfo(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db_pool = None
        self.cached_names = []
        self.name_lookup_map = {}
        self.last_cache_time = 0
        self.cache_duration = 300  # 5 minutes

    async def get_pool(self):
        if self.db_pool is None:
            self.db_pool = await asyncpg.create_pool(POSTGRES_URL)
        return self.db_pool

    async def fetch_cached_names(self):
        now = time.time()
        if not self.cached_names or now - self.last_cache_time > self.cache_duration:
            pool = await self.get_pool()
            rows = await pool.fetch("SELECT name, subname FROM characters")
            name_map = {}
            for row in rows:
                name = row["name"]
                subname = row["subname"]
                name_map[name.lower()] = name
                if subname:
                    name_map[subname.lower()] = name
            self.cached_names = sorted(set(name_map.values()))
            self.name_lookup_map = name_map
            self.last_cache_time = now

    async def unit_autocomplete(self, interaction: Interaction, current: str) -> List[app_commands.Choice[str]]:
        try:
            await self.fetch_cached_names()
            current_lower = current.lower()
            matched_names = {
                original_name
                for key, original_name in self.name_lookup_map.items()
                if current_lower in key
            }
            return [
                app_commands.Choice(name=name, value=name)
                for name in sorted(matched_names)[:25]
            ]
        except Exception as e:
            print(f"[Autocomplete Error] {e}")
            return []

    async def get_total_tracked_matches(self, debut_date):
        pool = await self.get_pool()
        async with pool.acquire() as conn:
            return await conn.fetchval("""
                SELECT COUNT(*) FROM matches 
                WHERE has_character_data = TRUE AND timestamp::DATE >= $1
            """, debut_date)

    async def get_total_preban_matches(self, debut_date):
        pool = await self.get_pool()
        async with pool.acquire() as conn:
            return await conn.fetchval("""
                SELECT COUNT(*) FROM matches
                WHERE has_character_data = TRUE
                AND timestamp::DATE >= $1
                AND jsonb_array_length(raw_data->'prebans') > 0
            """, debut_date)

    async def get_total_joker_matches(self, debut_date):
        pool = await self.get_pool()
        async with pool.acquire() as conn:
            return await conn.fetchval("""
                SELECT COUNT(*) FROM matches
                WHERE has_character_data = TRUE
                AND timestamp::DATE >= $1
                AND jsonb_array_length(raw_data->'jokers') > 0
            """, debut_date)

    async def fetch_stats_data(self, mode: str):
        pool = await self.get_pool()
        async with pool.acquire() as conn:
            if mode == "winrate":
                return await conn.fetch("""
                    SELECT name,
                        (e0_wins + e1_wins + e2_wins + e3_wins + e4_wins + e5_wins + e6_wins)::FLOAT /
                        NULLIF(e0_uses + e1_uses + e2_uses + e3_uses + e4_uses + e5_uses + e6_uses, 0) AS rate
                    FROM characters
                    WHERE (e0_uses + e1_uses + e2_uses + e3_uses + e4_uses + e5_uses + e6_uses) >= 5
                    ORDER BY rate DESC
                    LIMIT 10
                """)
            elif mode in ["pickrate", "banrate", "appearancerate"]:
                column_map = {
                    "pickrate": "pick_count",
                    "banrate": "ban_count",
                    "appearancerate": "appearance_count"
                }
                column = column_map[mode]
                return await conn.fetch(f"""
                    SELECT name,
                        {column}::FLOAT / NULLIF((
                            SELECT COUNT(*) FROM matches
                            WHERE has_character_data = TRUE AND timestamp >= characters.debut_date::DATE
                        ), 0) AS rate
                    FROM characters
                    WHERE {column} > 0
                    ORDER BY rate DESC
                    LIMIT 10
                """)

            elif mode == "prebanrate":
                return await conn.fetch("""
                    SELECT name,
                        preban_count::FLOAT / NULLIF((
                            SELECT COUNT(*) FROM matches
                            WHERE has_character_data = TRUE AND timestamp >= characters.debut_date
                            AND jsonb_array_length(raw_data->'prebans') > 0
                        ), 0) AS rate
                    FROM characters
                    WHERE preban_count > 0
                    ORDER BY rate DESC
                    LIMIT 10
                """)

            elif mode == "jokerrate":
                return await conn.fetch("""
                    SELECT name,
                        joker_count::FLOAT / NULLIF((
                            SELECT COUNT(*) FROM matches
                            WHERE has_character_data = TRUE AND timestamp >= characters.debut_date
                            AND jsonb_array_length(raw_data->'jokers') > 0
                        ), 0) AS rate
                    FROM characters
                    WHERE joker_count > 0
                    ORDER BY rate DESC
                    LIMIT 10
                """)
        
            elif mode == "loserate":
                return await conn.fetch("""
                    SELECT name,
                        1 - ((e0_wins + e1_wins + e2_wins + e3_wins + e4_wins + e5_wins + e6_wins)::FLOAT /
                        NULLIF(e0_uses + e1_uses + e2_uses + e3_uses + e4_uses + e5_uses + e6_uses, 0)) AS rate
                    FROM characters
                    WHERE (e0_uses + e1_uses + e2_uses + e3_uses + e4_uses + e5_uses + e6_uses) >= 5
                    ORDER BY rate DESC
                    LIMIT 10
                """)

    @app_commands.command(name="unit-info", description="Let's explore this unit info.")
    @app_commands.describe(unit="The unit to display.")
    @app_commands.guilds(GUILD_ID)
    @app_commands.autocomplete(unit=unit_autocomplete)
    async def unit_info(self, interaction: Interaction, unit: str):
        await interaction.response.defer()
        pool = await self.get_pool()
        row = await pool.fetchrow("SELECT * FROM characters WHERE name ILIKE $1 OR subname ILIKE $1 LIMIT 1", unit)

        if not row:
            await interaction.followup.send("I-I couldn’t find data for that unit… maybe check the spelling?", ephemeral=True)
            return

        def percent(value, total):
            return f"{round(100 * value / total)}%" if total else "0%"

        pick = row["pick_count"]
        ban = row["ban_count"]
        preban = row.get("preban_count", 0)
        joker = row.get("joker_count", 0)
        appearance = row.get("appearance_count", 0)
        total_wins = sum(row.get(f"e{i}_wins", 0) for i in range(7))
        debut_date = row.get("debut_date", "2025-04-19")

        if isinstance(debut_date, str):
            debut_date = datetime.strptime(debut_date, "%Y-%m-%d").date()

        if debut_date > date.today():
            await interaction.followup.send(
                f"I-I’m sorry! {row['name']} hasn’t debuted yet... Please check back after {debut_date.strftime('%B %d, %Y')}!",
                ephemeral=True
            )
            return
        total_tracked_matches = await self.get_total_tracked_matches(debut_date)
        total_preban_matches = await self.get_total_preban_matches(debut_date)
        total_joker_matches = await self.get_total_joker_matches(debut_date)


        embed = Embed(
            title=f"Unit Info for {row['name']}",
            color=0xB197FC
        )
        embed.set_thumbnail(url=row["image_url"])
        embed.add_field(name="Pick Rate", value=percent(pick, total_tracked_matches), inline=True)
        embed.add_field(name="Ban Rate", value=percent(ban, total_tracked_matches), inline=True)
        embed.add_field(name="Win Rate", value=percent(total_wins, pick), inline=True)
        embed.add_field(name="Preban Rate", value=percent(preban, total_preban_matches), inline=True)
        embed.add_field(name="Joker Rate", value=percent(joker, total_joker_matches), inline=True)
        embed.add_field(name="Appearance Rate", value=percent(appearance, total_tracked_matches), inline=True)
        embed.add_field(name="\u200b", value="\u200b", inline=False)

        # Eidolon Win Breakdown
        eidolon_lines = []
        for i in range(7):
            wins = row.get(f"e{i}_wins", 0)
            uses = row.get(f"e{i}_uses", 0)
            eidolon_lines.append(f"**E{i}:** {wins} / {uses} ({percent(wins, uses)})")

        embed.add_field(name="Win Rate by Eidolon", value="\n".join(eidolon_lines), inline=True)
        embed.set_footer(text="Handled with care by Kyasutorisu")
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="stats", description="See the top 10 units by win, pick, and ban rates!")
    @app_commands.guilds(GUILD_ID)
    async def stats(self, interaction: Interaction):
        await interaction.response.defer()
        data = await self.fetch_stats_data("winrate")
        view = StatsView(self, "winrate", data, user_id=interaction.user.id)
        await interaction.followup.send(embed=view.get_embed(), view=view)


async def setup(bot):
    await bot.add_cog(UnitInfo(bot))
