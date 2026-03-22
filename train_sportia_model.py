import requests
import pandas as pd
import time

BASE_URL="https://site.api.espn.com/apis/site/v2/sports/soccer"

LEAGUES=[
"eng.1",
"eng.2",
"esp.1",
"ger.1",
"ita.1",
"fra.1",
"usa.1",
"mex.1",
"ned.1",
"uefa.champions",
"uefa.europa"
]

DATASET="sportia_dataset.csv"


def get_scoreboard(league):

    url=f"{BASE_URL}/{league}/scoreboard"

    try:
        r=requests.get(url,timeout=20)
        return r.json()
    except:
        return None


def get_summary(league,event_id):

    url=f"{BASE_URL}/{league}/summary?event={event_id}"

    try:
        r=requests.get(url,timeout=20)
        return r.json()
    except:
        return None


def build_dataset():

    rows=[]

    for league in LEAGUES:

        print("League:",league)

        data=get_scoreboard(league)

        if not data:
            continue

        events=data.get("events",[])

        for event in events:

            event_id=event["id"]

            summary=get_summary(league,event_id)

            if not summary:
                continue

            try:

                comp=summary["header"]["competitions"][0]

                home=comp["competitors"][0]
                away=comp["competitors"][1]

                home_score=int(home["score"])
                away_score=int(away["score"])

                total=home_score+away_score

                rows.append({

                    "home_goals":home_score,
                    "away_goals":away_score,
                    "goal_diff":home_score-away_score,
                    "total_goals":total,

                    "home_win":1 if home_score>away_score else 0,
                    "over25":1 if total>2 else 0,
                    "under35":1 if total<4 else 0,
                    "btts":1 if home_score>0 and away_score>0 else 0
                })

                print("match:",event_id)

                time.sleep(0.2)

            except:
                pass

    df=pd.DataFrame(rows)

    df.to_csv(DATASET,index=False)

    print("Dataset size:",len(df))


if __name__=="__main__":

    build_dataset()
