import discord
from discord.utils import get

def get_rank(elo_score, player_id=None, elo_data=None):
    if player_id and elo_data:
        # Sort players by ELO descending
        top_players = sorted(
            elo_data.items(),
            key=lambda x: x[1].get("elo", 200),
            reverse=True
        )

        # Check if the player is within the top 3 and has at least 1400 ELO
        for pid, pdata in top_players[:3]:
            if str(player_id) == str(pid) and pdata.get("elo", 0) >= 1400:
                return "Akivili"
    if elo_score < 300:
        return "Trailblazer"
    elif 300 <= elo_score < 600:
        return "Memokeeper"
    elif 600 <= elo_score < 850:
        return "Genius Scholar"
    elif 850 <= elo_score < 1100:
        return "Arbitor General"
    elif 1100 <= elo_score < 1300:
        return "Emanator"
    else:
        return "Aeon"

async def update_rank_role(
    member: discord.Member,
    new_elo: int,
    elo_data: dict,
    channel: discord.TextChannel = None,
    announce_demotions: bool = False,
    force_old_rank: str = None
):
    guild = member.guild
    old_rank = force_old_rank if force_old_rank else get_rank(
        elo_data.get(str(member.id), {}).get("elo", 200),
        player_id=member.id,
        elo_data=elo_data
    )
    new_rank = get_rank(new_elo, player_id=member.id, elo_data=elo_data)

    rank_order = [
        "Trailblazer", "Memokeeper", "Genius Scholar",
        "Arbitor General", "Emanator", "Aeon", "Akivili"
    ]

    try:
        old_index = rank_order.index(old_rank)
        new_index = rank_order.index(new_rank)
    except ValueError:
        print(f"⚠️ Invalid rank order for {member.display_name}: {old_rank} → {new_rank}")
        return

    rank_role = get(guild.roles, name=new_rank)
    if not rank_role:
        print(f"⚠️ Role '{new_rank}' not found in guild {guild.name}")
        return

    # Already has correct role?
    has_rank_role = any(role.name == new_rank for role in member.roles)
    if old_rank == new_rank and has_rank_role:
        return

    # Check bot permissions
    bot_member = guild.me
    if not bot_member.guild_permissions.manage_roles:
        print(f"❌ Bot lacks 'Manage Roles' permission")
        return
    if rank_role.position >= bot_member.top_role.position:
        print(f"❌ Bot role is lower than '{new_rank}', cannot assign")
        return

    roles_to_remove = [role for role in member.roles if role.name in rank_order]
    try:
        await member.remove_roles(*roles_to_remove)
        await member.add_roles(rank_role)
    except discord.Forbidden:
        print(f"❌ Missing permission to update {member.display_name}'s roles")
        return

   
    if channel:
        try:
            if new_rank == "Akivili" and old_rank != "Akivili":
                await channel.send(
                    f"{member.mention} has ascended as the **Akivili**, Weaver of Fates!\n"
                    f"The loom bows to their threads — all destinies now orbit their will."
                )
            elif new_index > old_index:
                await channel.send(
                    f"{member.mention} has awakened as an **{new_rank}**!\n"
                    f"The threads of fate weave ever forward..."
                )
            elif announce_demotions and new_index < old_index:
                await channel.send(
                    f"{member.mention} has returned to the path of **{new_rank}**.\n"
                    f"The threads shift softly... but they never break."
                )
            else:
                print(f"Rank changed but no announcement made for {member.display_name}")
        except Exception as e:
            print(f"❌ Failed to send rank change message for {member.display_name}: {e}")