import numpy as np


def simulate_match(home_xg, away_xg, simulations=20000):

    home_win = 0
    away_win = 0
    draw = 0
    over25 = 0
    btts = 0

    for _ in range(simulations):

        hg = np.random.poisson(home_xg)
        ag = np.random.poisson(away_xg)

        if hg > ag:
            home_win += 1
        elif ag > hg:
            away_win += 1
        else:
            draw += 1

        if hg + ag > 2:
            over25 += 1

        if hg > 0 and ag > 0:
            btts += 1

    sims = simulations

    return {
        "home": home_win / sims,
        "away": away_win / sims,
        "draw": draw / sims,
        "over25": over25 / sims,
        "btts": btts / sims
    }
