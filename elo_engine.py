import math

K = 20

def expected_score(rating_a, rating_b):

    return 1 / (1 + 10 ** ((rating_b - rating_a) / 400))


def update_elo(rating_a, rating_b, result):

    expected = expected_score(rating_a, rating_b)

    new_rating = rating_a + K * (result - expected)

    return new_rating


class EloRatings:

    def __init__(self):

        self.ratings = {}

    def get(self, team):

        return self.ratings.get(team, 1500)

    def update_match(self, home, away, home_goals, away_goals):

        r_home = self.get(home)
        r_away = self.get(away)

        if home_goals > away_goals:
            result_home = 1
        elif home_goals < away_goals:
            result_home = 0
        else:
            result_home = 0.5

        new_home = update_elo(r_home, r_away, result_home)
        new_away = update_elo(r_away, r_home, 1 - result_home)

        self.ratings[home] = new_home
        self.ratings[away] = new_away
