import discord
from discord.utils import get

def get_rank(elo_score, player_id=None, elo_data=None):
    if elo_data and player_id and elo_score >= 1000:
    
        top_players = sorted(
            elo_data.items(),
            key=lambda x: x[1].get("elo", 200),
            reverse=True
        )[:3]
        if any(pid == str(player_id) for pid, _ in top_players):
            return "Cipher Champion"

    if elo_score < 300:
        return "Trailblazer"
    elif 300 <= elo_score < 500:
        return "Memokeeper"
    elif 500 <= elo_score < 650:
        return "Genius Scholar"
    elif 650 <= elo_score < 800:
        return "Arbiter-Generals"
    elif 800 <= elo_score < 900:
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
    player_id = str(member.id)

    old_rank = force_old_rank if force_old_rank else get_rank(
        elo_data.get(player_id, {}).get("elo", 200),
        player_id=player_id,
        elo_data=elo_data
    )
    new_rank = get_rank(new_elo, player_id=player_id, elo_data=elo_data)

    was_CipherChampion = "Cipher Champion" in [r.name for r in member.roles]

    rank_order = [
        "Trailblazer", "Memokeeper", "Genius Scholar",
        "Arbiter-Generals", "Emanator", "Aeon", "Cipher Champion"
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

    has_rank_role = any(role.name == new_rank for role in member.roles)
    if old_rank == new_rank and has_rank_role:
        return

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

    top_CipherChampions = sorted(
        [(pid, pdata) for pid, pdata in elo_data.items() if pdata.get("elo", 0) >= 1000],
        key=lambda x: x[1].get("elo", 200),
        reverse=True
    )[:3]
    top_CipherChampion_ids = [pid for pid, _ in top_CipherChampions]

    if new_rank == "Cipher Champion" and old_rank != "Cipher Champion":
        for pid, _ in elo_data.items():
            if pid not in top_CipherChampion_ids:
                user = guild.get_member(int(pid))
                if user and any(role.name == "Cipher Champion" for role in user.roles):
                    CipherChampion_role = get(guild.roles, name="Cipher Champion")
                    fallback_rank = get_rank(
                        elo_score=elo_data[pid]["elo"],
                        player_id=pid,
                        elo_data=elo_data
                    )
                    fallback_role = get(guild.roles, name=fallback_rank)
                    try:
                        await user.remove_roles(CipherChampion_role)
                        if fallback_role:
                            await user.add_roles(fallback_role)
                        if channel and announce_demotions:
                            await channel.send(
                                f"{user.mention} has stepped down from **Cipher Champion**.\n"
                                f"Even the fates must bow to the ever-changing threads…"
                            )
                    except Exception as e:
                        print(f"❌ Failed to adjust {user.display_name}: {e}")


    if channel:
        try:
            if new_rank == "Cipher Champion" and old_rank != "Cipher Champion":
                await channel.send(
                    f"{member.mention} has ascended as the **Cipher Champion**, Weaver of Fates!\n"
                    f"The loom bows to their threads — all destinies now orbit their will."
                )
            elif new_index > old_index:
                await channel.send(
                    f"{member.mention} has awakened as an **{new_rank}**!\n"
                    f"The threads of fate weave ever forward..."
                )
            elif announce_demotions and (
                new_index < old_index or
                (was_CipherChampion and new_rank != "Cipher Champion")
            ):
                if old_rank == "Cipher Champion" and new_rank != "Cipher Champion":
                    await channel.send(
                        f"{member.mention} has stepped down from **Cipher Champion**.\n"
                        f"Even the fates must bow to the ever-changing threads…"
                    )
                else:
                    await channel.send(
                        f"{member.mention} has returned to the path of **{new_rank}**.\n"
                        f"The threads shift softly... but they never break."
                    )
            else:
                print(f"Rank changed but no announcement made for {member.display_name}")
        except Exception as e:
            print(f"❌ Failed to send rank change message for {member.display_name}: {e}")
