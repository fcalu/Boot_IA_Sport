import requests
import time
import csv
import os
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

class SportiaSecureScanner:

    def __init__(self):

        self.api_base = "https://sportia-api.onrender.com/api/v1"

        self.espn_api = "https://site.api.espn.com/apis/site/v2/sports"
        self.espn_core = "https://sports.core.api.espn.com/v2/sports"

        self.token = os.getenv("TELEGRAM_TOKEN")
        self.chat_id = os.getenv("TELEGRAM_CHAT_ID")

        if not self.token or not self.chat_id:
            raise ValueError("Faltan TELEGRAM_TOKEN o TELEGRAM_CHAT_ID")

        # bankroll
        self.bankroll = 500
        self.stake_base = 10
        self.kelly_multiplier = 0.25

        self.history_file = "auditoria_ganancias.csv"

        self.sent_ids = set()

        self._init_history()
        self._load_sent_ids()

        self.soccer_leagues = {
            "eng.1": "Premier League",
            "eng.2": "Championship",
            "esp.1": "La Liga",
            "ger.1": "Bundesliga",
            "ita.1": "Serie A",
            "fra.1": "Ligue 1",
            "usa.1": "MLS",
            "usa.nwsl": "NWSL",
            "uefa.champions": "Champions League",
            "uefa.europa": "Europa League",
            "fifa.world": "World Cup",
            "mex.1": "Liga MX",
            "ned.1": "Eredivisie",
            "por.1": "Primeira Liga",
            "sco.1": "Scottish Premiership",
            "bra.1": "Brasileirão",
            "conmebol.libertadores": "Copa Libertadores"
        }

        self.sports_config = {
            "soccer": list(self.soccer_leagues.keys()),
            "basketball": ["nba"]
        }

    # =================================================
    # ESPN VALIDATION
    # =================================================

    def validate_with_espn(self,event_id,sport,league,model_prob):
    
        try:

            # ESPN no soporta predictor para soccer
            if sport == "soccer":
                return True

            url = f"{self.espn_core}/{sport}/leagues/{league.lower()}/events/{event_id}/competitions/{event_id}/predictor"

            data = self._safe_request("GET",url)

            if not data:
                return True

            espn_prob = data.get("homeTeamPercentage")

            if espn_prob is None:
                return True

            espn_prob = float(espn_prob)/100

            diff = abs(model_prob-espn_prob)

            if diff > 0.18:
                print("⚠️ ESPN predictor divergence:",diff)
                return False

            return True

        except:
            return True

    # =================================================
    # CSV INIT
    # =================================================

    def _init_history(self):

        header = [
            "ID","Fecha","Partido","Pick","Momio",
            "Prob_Modelo","Edge","Stake",
            "Resultado","Ganancia_Neta","Deporte","Liga"
        ]

        if not os.path.exists(self.history_file):

            with open(self.history_file,"w",newline="",encoding="utf-8") as f:

                writer = csv.writer(f)

                writer.writerow(header)

    def _load_sent_ids(self):

        if not os.path.exists(self.history_file):
            return

        try:

            with open(self.history_file,newline="",encoding="utf-8") as f:

                reader = csv.DictReader(f)

                for row in reader:

                    self.sent_ids.add(f"{row['ID']}_{row['Pick']}")

        except:
            pass


    # =================================================
    # MATH
    # =================================================

    def american_to_decimal(self,odds):

        if odds>0:
            return 1+(odds/100)

        return 1+(100/abs(odds))


    def implied_prob(self,odds):

        if odds>0:
            return 100/(odds+100)

        return abs(odds)/(abs(odds)+100)


    def kelly_fraction(self,prob,decimal_odds):

        b = decimal_odds-1

        if b<=0:
            return 0

        return max((b*prob-(1-prob))/b,0)


    # =================================================
    # SCANNER
    # =================================================

    def scan_all(self):

        print("\n🔎 Escaneando mercados...")

        for sport in self.sports_config:

            sport_query = sport if sport!="basketball" else "nba"

            matches = self._safe_request(
                "GET",
                f"{self.api_base}/matches/upcoming?sport={sport_query}"
            )

            if not matches:
                continue

            for match in matches:

                payload = {
                    "sport":sport,
                    "league":match.get("league",sport_query),
                    "event_id":str(match["event_id"]),
                    "home_team":match["home"],
                    "away_team":match["away"]
                }

                pred = self._safe_request(
                    "POST",
                    f"{self.api_base}/ai/predict",
                    payload
                )

                if not pred:
                    continue

                root_odds = pred.get("odds",{})

                for prop in pred.get("player_props",[]):

                    if prop.get("bet_tier")!="VALUE_BET":
                        continue

                    if prop.get("confidence",0)<60:
                        continue


                    decision = prop.get("bet_decision")

                    prop_type = prop.get("type","").lower()

                    name = prop.get("name","Team")

                    line = prop.get("line","")


                    odds = prop.get("over_odds") if decision=="OVER" else prop.get("under_odds")

                    prob = prop.get("model_prob_over") if decision=="OVER" else prop.get("model_prob_under")


                    if odds is None:

                        if "moneyline" in prop_type:

                            prob = prop.get("model_prob")

                            if "home" in prop_type:
                                odds = root_odds.get("home_moneyline")

                            elif "away" in prop_type:
                                odds = root_odds.get("away_moneyline")

                        elif "total" in prop_type:

                            odds = root_odds.get("over_odds") if decision=="OVER" else root_odds.get("under_odds")


                    if prob is None or odds is None:
                        continue


                    prob_calibrada = prob*0.98

                    edge = prob_calibrada-self.implied_prob(odds)

                    if edge < 0.04:
                        continue


                    # ESPN VALIDATION
                    if not self.validate_with_espn(
                        match["event_id"],
                        sport,
                        match.get("league",""),
                        prob_calibrada
                    ):
                        continue


                    decimal = self.american_to_decimal(odds)

                    units = min(
                        self.kelly_fraction(prob_calibrada,decimal)
                        *self.kelly_multiplier
                        *self.stake_base,
                        2
                    )

                    units = round(units,2)

                    if units<0.1:
                        continue


                    pick_label = f"{name} | {prop_type} {decision} {line}"

                    if f"{match['event_id']}_{pick_label}" in self.sent_ids:
                        continue


                    emoji = "⚽" if sport=="soccer" else "🏀"


                    message = f"""
🎯 **{emoji} VALUE DETECTADO**

🏆 {match['home']} vs {match['away']}

📌 Pick: {pick_label}

💰 Momio: {odds}

📊 Prob: {prob_calibrada*100:.1f}%
Edge: +{edge*100:.1f}%

💎 Stake: {units}u
"""

                    self._send_telegram(message)

                    self.sent_ids.add(f"{match['event_id']}_{pick_label}")

                    self._save_to_csv(
                        match,
                        pick_label,
                        odds,
                        prob_calibrada,
                        edge,
                        units,
                        sport
                    )


    # =================================================
    # CSV SAVE
    # =================================================

    def _save_to_csv(self,match,pick,odds,prob,edge,stake,sport):

        with open(self.history_file,"a",newline="",encoding="utf-8") as f:

            writer = csv.writer(f)

            writer.writerow([
                match["event_id"],
                datetime.now().strftime("%Y-%m-%d"),
                f"{match['home']} vs {match['away']}",
                pick,
                odds,
                prob,
                edge,
                stake,
                "PENDIENTE",
                0,
                sport,
                match.get("league","N/A")
            ])


    # =================================================
    # SAFE REQUEST
    # =================================================

    def _safe_request(self,method,url,payload=None):

        try:

            if method=="POST":

                r = requests.post(url,json=payload,timeout=25)

            else:

                r = requests.get(url,timeout=20)

            if r.status_code==200:
                return r.json()

        except:
            return None


    # =================================================
    # TELEGRAM
    # =================================================

    def _send_telegram(self,msg):

        try:

            requests.post(
                f"https://api.telegram.org/bot{self.token}/sendMessage",
                json={
                    "chat_id":self.chat_id,
                    "text":msg,
                    "parse_mode":"Markdown"
                }
            )

        except:
            pass


    # =================================================
    # RUN
    # =================================================

    def run(self):

        self._send_telegram("🤖 Sportia V4 + ESPN Validation ONLINE")

        while True:

            self.scan_all()

            time.sleep(900)


if __name__=="__main__":

    SportiaSecureScanner().run()