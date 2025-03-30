from discord.utils import get

async def update_rank_role(member: discord.Member, new_elo: int, elo_data: dict, channel: discord.TextChannel = None):
    guild = member.guild
    old_rank = get_rank(elo_data.get(str(member.id), {}).get("elo", 200), player_id=member.id, elo_data=elo_data)
    new_rank = get_rank(new_elo, player_id=member.id, elo_data=elo_data)

    if old_rank == new_rank:
        return  # No rank change

    # Update roles
    rank_names = [
        "Trailblazer", "Memokeeper", "Genius Scholar",
        "Arbitor General", "Emanator", "Aeon", "Akivili"
    ]
    rank_role = discord.utils.get(guild.roles, name=new_rank)
    if not rank_role:
        print(f"⚠️ Role '{new_rank}' not found.")
        return

    roles_to_remove = [role for role in member.roles if role.name in rank_names]
    await member.remove_roles(*roles_to_remove)
    await member.add_roles(rank_role)

    # 🌟 Send promotion message
    if channel:
        await channel.send(
            f" {member.mention} has awakened as an **{new_rank}**!\n"
            f"The threads of fate weave ever forward..."
        )


def get_rank(elo_score, player_id=None, elo_data=None):
    if player_id and elo_data:
        top_player = max(elo_data.items(), key=lambda x: x[1].get("elo", 200), default=None)
        top_elo = float(top_player[1].get("elo", 0))
        if str(player_id) == str(top_player[0]) and top_elo >= 1300:
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
