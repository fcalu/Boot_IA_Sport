import requests
import time
import csv
import os
from datetime import datetime, timedelta
from dotenv import load_dotenv
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

load_dotenv()

class SportiaSecureScanner:

    def __init__(self):

        self.daily_picks=0
        self.max_daily_picks=5
        self.current_day=datetime.utcnow().date()

        self.session = requests.Session()

        retry = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[500,502,503,504]
        )

        adapter = HTTPAdapter(max_retries=retry)

        self.session.mount("http://",adapter)
        self.session.mount("https://",adapter)

        self.api_base="https://sportia-api.onrender.com/api/v1"
        self.espn_api="https://site.api.espn.com/apis/site/v2/sports"

        self.token=os.getenv("TELEGRAM_TOKEN")
        self.chat_id=os.getenv("TELEGRAM_CHAT_ID")

        if not self.token or not self.chat_id:
            raise ValueError("Faltan TELEGRAM_TOKEN o TELEGRAM_CHAT_ID")

        self.stake_base=10
        self.kelly_multiplier=0.25

        self.history_file="auditoria_ganancias.csv"

        self.sent_ids=set()
        self.sent_matches=set()

        # CONTROL DE PICKS DIARIOS
        self.daily_picks=0
        self.max_daily_picks=5
        self.current_day=datetime.utcnow().date()


        self._init_history()
        self._load_sent_ids()

        self.sports_config={
            "soccer":["eng.1","esp.1","ger.1","ita.1","mex.1"]
        }

    # =====================================================
    # CSV
    # =====================================================

    def _init_history(self):

        header=[
            "ID","Fecha","Partido","Pick","Momio",
            "Prob_Modelo","Edge","Stake",
            "Resultado","Ganancia_Neta","Deporte","Liga",
            "Momio_Inicial","Timestamp_Pick"
        ]

        if not os.path.exists(self.history_file):

            with open(self.history_file,"w",newline="",encoding="utf-8") as f:
                csv.writer(f).writerow(header)

    def _load_sent_ids(self):

        if not os.path.exists(self.history_file):
            return

        with open(self.history_file,newline="",encoding="utf-8") as f:

            reader=csv.DictReader(f)

            for row in reader:

                key=f"{row['ID']}_{row['Pick']}"
                self.sent_ids.add(key)

    # =====================================================
    # MATH
    # =====================================================

    def american_to_decimal(self,odds):

        if odds>0:
            return 1+odds/100

        return 1+100/abs(odds)

    def implied_prob(self,odds):

        if odds>0:
            return 100/(odds+100)

        return abs(odds)/(abs(odds)+100)

    def kelly_fraction(self,prob,decimal_odds):

        b=decimal_odds-1

        if b<=0:
            return 0

        return max((b*prob-(1-prob))/b,0)

    # =====================================================
    # REQUEST
    # =====================================================

    def _safe_request(self,method,url,payload=None):

        try:

            if method=="POST":
                r=self.session.post(url,json=payload,timeout=25)
            else:
                r=self.session.get(url,timeout=60)

            if r.status_code==200:
                return r.json()

        except Exception as e:
            print("Request error:",e)

        return None

    # =====================================================
    # MATCH TIME
    # =====================================================

    def _format_match_time(self,match):

        try:

            date_str=match.get("date") or match.get("start_time")

            if not date_str:
                return None,None

            dt=datetime.fromisoformat(date_str.replace("Z",""))

            now=datetime.utcnow()

            if dt>now+timedelta(days=2):
                return None,None

            if dt<now:
                return None,None

            dt_local=dt-timedelta(hours=6)

            return dt,dt_local.strftime("%d %b %H:%M")

        except:
            return None,None

    # =====================================================
    # TELEGRAM
    # =====================================================

    def _send_telegram(self,msg):

        try:

            self.session.post(
                f"https://api.telegram.org/bot{self.token}/sendMessage",
                json={
                    "chat_id":self.chat_id,
                    "text":msg,
                    "parse_mode":"Markdown"
                }
            )

        except Exception as e:
            print("Telegram error:",e)

    # =====================================================
    # RESULT CHECK (ESPN)
    # =====================================================

    def check_results(self):

        if not os.path.exists(self.history_file):
            return

        updated=[]
        settled=0
        session_profit=0

        with open(self.history_file,newline="",encoding="utf-8") as f:
            rows=list(csv.DictReader(f))

        for row in rows:

            if row["Resultado"]!="PENDIENTE":
                updated.append(row)
                continue

            sport=row.get("Deporte","soccer")
            league=row.get("Liga","mex.1")

            res=self._safe_request(
                "GET",
                f"{self.espn_api}/{sport}/{league}/summary?event={row['ID']}"
            )

            if not res:
                updated.append(row)
                continue

            try:

                event=res["header"]["competitions"][0]
                status=event["status"]["type"]["state"]

                if status!="post":
                    updated.append(row)
                    continue

                home=int(event["competitors"][0]["score"])
                away=int(event["competitors"][1]["score"])

                total=home+away

                pick=row["Pick"].lower()

                stake=float(row["Stake"])
                odds=float(row["Momio"])

                win=False

                if "over" in pick:
                    line=2.5
                    win=total>line

                elif "btts" in pick:
                    win=(home>0 and away>0)

                elif "home" in pick:
                    win=home>away

                elif "away" in pick:
                    win=away>home

                if win:

                    profit=stake*(self.american_to_decimal(odds)-1)

                    row["Resultado"]="GANADA"
                    row["Ganancia_Neta"]=round(profit,2)

                    session_profit+=profit

                else:

                    row["Resultado"]="PERDIDA"
                    row["Ganancia_Neta"]=-stake

                    session_profit-=stake

                settled+=1

            except:
                pass

            updated.append(row)

        if settled>0:

            with open(self.history_file,"w",newline="",encoding="utf-8") as f:

                writer=csv.DictWriter(f,fieldnames=updated[0].keys())
                writer.writeheader()
                writer.writerows(updated)

            self._send_telegram(
f"""📊 RESULTADOS ACTUALIZADOS

Partidos liquidados: {settled}

Profit sesión: {session_profit:.2f}u"""
            )

    # =====================================================
    # SCANNER
    # =====================================================

    def scan_all(self):
    
        # ===============================
        # RESET DIARIO DE PICKS
        # ===============================

        if not hasattr(self,"current_day"):
            self.current_day=datetime.utcnow().date()
            self.daily_picks=0

        if datetime.utcnow().date()!=self.current_day:
            self.current_day=datetime.utcnow().date()
            self.daily_picks=0

        print(f"\n🔎 [{datetime.now().strftime('%H:%M:%S')}] Escaneando")

        for sport in self.sports_config:

            matches=self._safe_request(
                "GET",
                f"{self.api_base}/matches/upcoming?sport={sport}"
            )

            if not matches:
                continue

            for match in matches:

                # ===============================
                # LIMITE DE PICKS DIARIOS
                # ===============================

                if self.daily_picks>=5:
                    print("⚠️ Límite diario de picks alcanzado")
                    return

                try:

                    dt,match_time=self._format_match_time(match)

                    if match_time is None:
                        continue

                    match_id=match["event_id"]

                    if match_id in self.sent_matches:
                        continue

                    # ===============================
                    # FILTRO DE LIGAS DEBILES
                    # ===============================

                    weak_leagues=["bra.1", "usa.nwsl", "eng.2"]

                    if match.get("league") in weak_leagues:
                        continue

                    payload={
                        "sport":sport,
                        "league":match.get("league",sport),
                        "event_id":str(match_id),
                        "home_team":match["home"],
                        "away_team":match["away"]
                    }

                    pred=self._safe_request(
                        "POST",
                        f"{self.api_base}/ai/predict",
                        payload
                    )

                    if not pred:
                        continue

                    odds_data=pred.get("odds",{})

                    home_odds=odds_data.get("home_moneyline")
                    away_odds=odds_data.get("away_moneyline")
                    over_odds=odds_data.get("over_odds")

                    for prop in pred.get("player_props",[]):

                        prob=None
                        edge=None
                        odds=None
                        pick=None

                        prop_type=prop.get("type")

                        confidence=prop.get("confidence",0)

                        if confidence<60:
                            continue

                        # ===============================
                        # OVER 2.5
                        # ===============================

                        if prop_type=="total_goals":

                            prob=prop.get("model_prob_over")
                            edge=prop.get("edge_over")
                            odds=over_odds
                            pick="OVER 2.5"

                            if prob is None or prob<0.63:
                                continue

                        # ===============================
                        # BTTS
                        # ===============================

                        elif prop_type=="btts":

                            prob=prop.get("model_prob_yes")
                            odds=over_odds
                            pick="BTTS YES"

                            if prob is None or prob<0.60:
                                continue

                            edge=prob-self.implied_prob(odds)

                        # ===============================
                        # HOME ML
                        # ===============================

                        elif prop_type=="moneyline_home":

                            prob=prop.get("model_prob")
                            edge=prop.get("edge")
                            odds=home_odds
                            pick="HOME ML"

                            if prob is None or prob<0.58:
                                continue

                        # ===============================
                        # AWAY ML
                        # ===============================

                        elif prop_type=="moneyline_away":

                            prob=prop.get("model_prob")
                            edge=prop.get("edge")
                            odds=away_odds
                            pick="AWAY ML"

                            if prob is None or prob<0.55:
                                continue

                        else:
                            continue

                        if odds is None:
                            continue

                        # ===============================
                        # FILTRO ODDS PELIGROSOS
                        # ===============================

                        if odds<-300:
                            continue

                        if odds>350:
                            continue

                        if edge is None:
                            edge=prob-self.implied_prob(odds)

                        # ===============================
                        # FILTRO EDGE
                        # ===============================

                        if edge<0.05 or edge>0.20:
                            continue

                        dec_odds=self.american_to_decimal(odds)

                        stake=self.kelly_fraction(
                            prob,
                            dec_odds
                        )*self.kelly_multiplier*self.stake_base

                        if stake<0.15:
                            continue

                        key=f"{match_id}_{pick}"

                        if key in self.sent_ids:
                            continue

                        # ===============================
                        # TIMESTAMP PICK
                        # ===============================

                        pick_timestamp=datetime.utcnow().isoformat()

                        # ===============================
                        # MENSAJE PREMIUM
                        # ===============================

                        market_prob=self.implied_prob(odds)

                        message=(

    f"🔥 SPORTIA VALUE BET\n\n"
    f"🏆 {match['home']} vs {match['away']}\n"
    f"🕒 {match_time} (CDMX)\n\n"

    f"📌 PICK: {pick}\n"
    f"💰 Odds: {odds}\n\n"

    f"📊 Model Probability: {prob*100:.1f}%\n"
    f"📉 Market Probability: {market_prob*100:.1f}%\n"
    f"📈 Edge: +{edge*100:.1f}%\n"

    f"💎 Stake: {stake:.2f}u\n\n"

    f"━━━━━━━━━━━━━━\n"
    f"🤖 Sportia AI Syndicate\n"
    f"📊 Edge Model Engine"

                        )

                        self._send_telegram(message)

                        self.sent_ids.add(key)
                        self.sent_matches.add(match_id)

                        self.daily_picks+=1

                        self._save_to_csv(
                            match,
                            pick,
                            odds,
                            prob,
                            edge,
                            stake,
                            sport
                        )

                        break

                except Exception as e:

                    print("Match error:",e)


    # =====================================================
    # SAVE CSV
    # =====================================================

    def _save_to_csv(self,match,pick,odds,prob,edge,stake,sport):

        with open(self.history_file,"a",newline="",encoding="utf-8") as f:

            csv.writer(f).writerow([
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
                match.get("league","N/A"),
                odds,
                datetime.utcnow().isoformat()
            ])


    # =====================================================
    # RUN
    # =====================================================

    def wake_backend(self):

        print("☕ Despertando backend...")

        try:
            self.session.get(
                f"{self.api_base}/matches/upcoming?sport=soccer",
                timeout=60
            )

        except:
            print("Backend despertando")

    def run(self):

        self._send_telegram("🤖 Sportia V9.5 Syndicate Scanner ONLINE")

        self.wake_backend()

        while True:

            self.scan_all()

            self.check_results()

            time.sleep(900)

if __name__=="__main__":
    SportiaSecureScanner().run()
