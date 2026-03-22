from edge_engine import detect_edge

home_attack = 1.25
away_attack = 1.10

home_def = 0.90
away_def = 1.05

league_avg = 2.6

home_xg = home_attack * away_def * league_avg
away_xg = away_attack * home_def * league_avg

odds = -120

edge = detect_edge(home_xg, away_xg, odds)

print(edge)
