import math

def american_to_prob(odds):

    if odds is None:
        return None

    if odds > 0:
        return 100 / (odds + 100)

    return abs(odds) / (abs(odds) + 100)


def detect_edge_from_backend(prop):

    results=[]

    if prop["type"]=="total_goals":

        over_prob=prop.get("model_prob_over")
        under_prob=prop.get("model_prob_under")

        over_odds=prop.get("over_odds")
        under_odds=prop.get("under_odds")

        if over_prob and over_odds:

            market=american_to_prob(over_odds)

            edge=over_prob-market

            if edge>0.05:

                results.append({
                    "pick":"OVER",
                    "line":prop.get("line"),
                    "prob":over_prob,
                    "edge":edge,
                    "odds":over_odds
                })


        if under_prob and under_odds:

            market=american_to_prob(under_odds)

            edge=under_prob-market

            if edge>0.05:

                results.append({
                    "pick":"UNDER",
                    "line":prop.get("line"),
                    "prob":under_prob,
                    "edge":edge,
                    "odds":under_odds
                })


    if prop["type"]=="btts":

        yes_prob=prop.get("model_prob_yes")

        if yes_prob:

            market=0.5  # fallback

            edge=yes_prob-market

            if edge>0.07:

                results.append({
                    "pick":"BTTS YES",
                    "prob":yes_prob,
                    "edge":edge
                })


    return results
