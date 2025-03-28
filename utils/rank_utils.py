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
