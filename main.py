import requests
import time
import csv
import os
from datetime import datetime, timedelta
from dotenv import load_dotenv
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import psycopg
load_dotenv()


class SportiaSecureScanner:

    def __init__(self):

        import pytz
        self.cdmx = pytz.timezone("America/Mexico_City")

        self.session = requests.Session()

        retry = Retry(total=3, backoff_factor=1, status_forcelist=[500,502,503,504])
        adapter = HTTPAdapter(max_retries=retry)

        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)

        self.api_base = "https://sportia-api.onrender.com/api/v1"
        self.espn_api = "https://site.api.espn.com/apis/site/v2/sports"

        self.token = os.getenv("TELEGRAM_TOKEN")
        self.chat_id = os.getenv("TELEGRAM_CHAT_ID")

        if not self.token or not self.chat_id:
            raise ValueError("Faltan TELEGRAM_TOKEN o TELEGRAM_CHAT_ID")
        # =========================
        # DB (Railway PostgreSQL)
        # =========================
        self.conn = psycopg.connect(os.getenv("DATABASE_URL"))
        self.cursor = self.conn.cursor()
        self.conn.autocommit = True
        self._init_db()

        self.stake_base = 10
        self.kelly_multiplier = 0.25

        self.history_file = "auditoria_ganancias.csv"    

        self.sent_ids = set()

        self.daily_picks = 0
        self.max_daily_picks = 12  # 🔥 subido para fusión

        self.current_day = datetime.utcnow().date()
        self.last_report_day = None

        self._init_history()
        self._load_sent_ids()

        self.sports_config = {
            "soccer": ["eng.1","esp.1","ger.1","ita.1","mex.1"]
        }

    # =====================================================
    # CSV
    # =====================================================

    def _init_history(self):

        header = [
            "ID","Fecha","Fecha_Partido","Hora_Partido","Partido","Pick","Tipo","Momio",
            "Prob_Modelo","Edge","Stake",
            "Resultado","Ganancia_Neta","Deporte","Liga",
            "Timestamp"
        ]

        if not os.path.exists(self.history_file):
            with open(self.history_file,"w",newline="",encoding="utf-8") as f:
                csv.writer(f).writerow(header)

    def _load_sent_ids(self):

        try:
            self.cursor.execute("SELECT id, pick FROM picks")

            for row in self.cursor.fetchall():
                key = f"{row[0]}_{row[1]}".lower()
                self.sent_ids.add(key)

        except:
            pass

    def _save_pick(self,match,match_date,match_time,pick,tipo,odds,prob,edge,stake):
    
        self.cursor.execute("""
            INSERT INTO picks VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """, (
            str(match["event_id"]),
            datetime.utcnow().strftime("%Y-%m-%d"),
            match_date,
            match_time,
            f"{match['home']} vs {match['away']}",
            pick,
            tipo,
            odds,
            round(prob,4),
            round(edge,4),
            round(stake,2),
            "PENDIENTE",
            0,
            "soccer",
            match.get("league"),
            datetime.utcnow().isoformat()
        ))

        self.conn.commit()

    # =====================================================
    # MATH
    # =====================================================

    def american_to_decimal(self,odds):
        return 1 + (odds/100 if odds>0 else 100/abs(odds))

    def implied_prob(self,odds):
        return 100/(odds+100) if odds>0 else abs(odds)/(abs(odds)+100)

    def kelly_fraction(self,prob,decimal_odds):
        b = decimal_odds - 1
        if b <= 0:
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

    def convert_to_cdmx(self, utc_time):
    
        try:
            if not utc_time:
                return "N/A", "Hora N/D"

            # 🔥 FIX ISO ZULU
            utc_time = utc_time.replace("Z", "+00:00")

            dt = datetime.fromisoformat(utc_time)

            if dt.tzinfo is None:
                dt = pytz.utc.localize(dt)

            local = dt.astimezone(self.cdmx)

            return local.strftime("%Y-%m-%d"), local.strftime("%d %b %H:%M")

        except Exception as e:
            print("Error fecha:", utc_time, e)
            return "N/A", "Hora N/D"

    # =====================================================
    # SCANNER FUSIONADO
    # =====================================================

    def scan_all(self):

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

                if self.daily_picks>=self.max_daily_picks:
                    return
                match_date, match_time = self.convert_to_cdmx(
                        match.get("start_time") or match.get("date")
                    )
                payload={
                    "sport":sport,
                    "league":match.get("league",sport),
                    "event_id":str(match["event_id"]),
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

                for prop in pred.get("player_props",[]):

                    if not prop.get("is_active"):
                        continue

                    if prop.get("type")!="total_goals":
                        continue

                    line=prop.get("line")

                    # ======================
                    # OVER
                    # ======================
                    over_prob=prop.get("model_prob_over")
                    over_odds=prop.get("over_odds")

                    if over_prob and over_odds:

                        market=self.implied_prob(over_odds)
                        edge=over_prob-market

                        tipo=None

                        # 🔵 SEGURO
                        if over_prob>=0.60 and edge>=0.04:
                            tipo="SEGURO"

                        # 🔴 AGRESIVO
                        elif edge>=0.05:
                            tipo="AGRESIVO"

                        if tipo:

                            pick=f"OVER {line}"
                            key=f"{match['event_id']}_{pick}".lower()

                            if key not in self.sent_ids:

                                stake=self.kelly_fraction(
                                    over_prob,
                                    self.american_to_decimal(over_odds)
                                )*self.kelly_multiplier*self.stake_base

                                if stake<0.2:
                                    continue

                                msg=f"""
🔥 SPORTIA FUSION

🏆 {match['home']} vs {match['away']}
🕒 {match_time} (CDMX)
📌 {pick} ({tipo})
💰 {over_odds}

📊 Model: {over_prob*100:.1f}%
📈 Edge: +{edge*100:.2f}%

💎 Stake: {stake:.2f}u
"""

                                self._send_telegram(msg)

                                self._save_pick(
                                                match,
                                                match_date,
                                                match_time,
                                                pick,
                                                tipo,
                                                over_odds,
                                                over_prob,
                                                edge,
                                                stake
                                            )

                                self.sent_ids.add(key)
                                self.daily_picks+=1

                    # ======================
                    # UNDER (solo seguro)
                    # ======================
                    under_prob=prop.get("model_prob_under")
                    under_odds=prop.get("under_odds")

                    if under_prob and under_odds:

                        market=self.implied_prob(under_odds)
                        edge=under_prob-market

                        if under_prob>=0.60 and edge>=0.04:

                            pick=f"UNDER {line}"
                            key=f"{match['event_id']}_{pick}".lower()

                            if key not in self.sent_ids:

                                stake=self.kelly_fraction(
                                    under_prob,
                                    self.american_to_decimal(under_odds)
                                )*self.kelly_multiplier*self.stake_base

                                msg=f"""
🧊 SPORTIA SAFE

🏆 {match['home']} vs {match['away']}
🕒 {match_time} (CDMX)
📌 {pick}
💰 {under_odds}

📊 Model: {under_prob*100:.1f}%
📈 Edge: +{edge*100:.2f}%

💎 Stake: {stake:.2f}u
"""

                                self._send_telegram(msg)

                                self._save_pick(
                                            match,
                                            match_date,
                                            match_time,
                                            pick,
                                            "SEGURO",
                                            under_odds,
                                            under_prob,
                                            edge,
                                            stake
                                        )

                                self.sent_ids.add(key)
                                self.daily_picks+=1

    def _init_db(self):
    
        self.cursor.execute("""
        CREATE TABLE IF NOT EXISTS picks (
            id TEXT,
            fecha TEXT,
            fecha_partido TEXT,
            hora_partido TEXT,
            partido TEXT,
            pick TEXT,
            tipo TEXT,
            momio REAL,
            prob REAL,
            edge REAL,
            stake REAL,
            resultado TEXT,
            ganancia REAL,
            deporte TEXT,
            liga TEXT,
            timestamp TEXT
        )
        """)

        self.conn.commit()

    # =====================================================
    # LIQUIDACIÓN (MEJORADA)
    # =====================================================

    def resolve_finished_matches(self):
    
        if not os.path.exists(self.history_file):
            return

        rows = []

        with open(self.history_file, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)

            for row in reader:

                # 🔒 Solo procesar pendientes
                if row["Resultado"] != "PENDIENTE":
                    rows.append(row)
                    continue

                event_id = row["ID"]

                url = f"{self.espn_api}/soccer/all/scoreboard?event={event_id}"
                data = self._safe_request("GET", url)

                if not data:
                    rows.append(row)
                    continue

                events = data.get("events", [])
                if not events:
                    rows.append(row)
                    continue

                try:
                    comp = events[0]["competitions"][0]

                    status_info = comp.get("status", {}).get("type", {})
                    status = status_info.get("state")
                    completed = status_info.get("completed")

                    home_score = comp["competitors"][0].get("score")
                    away_score = comp["competitors"][1].get("score")

                    # ==========================================
                    # 🔒 VALIDACIONES FUERTES (ANTI ERRORES ESPN)
                    # ==========================================

                    # 1. Debe estar terminado
                    if status != "post":
                        rows.append(row)
                        continue

                    # 2. Debe estar confirmado como completado
                    if not completed:
                        rows.append(row)
                        continue

                    # 3. Scores deben existir
                    if home_score is None or away_score is None:
                        rows.append(row)
                        continue

                    home = int(home_score)
                    away = int(away_score)

                    # 4. Evitar falsos 0-0 (muy común en ESPN prematch bug)
                    if home == 0 and away == 0:
                        rows.append(row)
                        continue

                    # ==========================================
                    # 🔢 EVALUACIÓN DEL PICK
                    # ==========================================

                    total = home + away
                    pick = row["Pick"].lower()

                    try:
                        line = float(pick.split()[-1])
                    except:
                        rows.append(row)
                        continue

                    win = False

                    if "over" in pick:
                        win = total > line

                    elif "under" in pick:
                        win = total < line

                    stake = float(row["Stake"])
                    odds = float(row["Momio"])

                    if win:
                        profit = stake * (self.american_to_decimal(odds) - 1)
                        row["Resultado"] = "GANADA"
                        row["Ganancia_Neta"] = round(profit, 2)
                    else:
                        row["Resultado"] = "PERDIDA"
                        row["Ganancia_Neta"] = -stake

                except Exception as e:
                    print(f"Error procesando {row['ID']}: {e}")

                rows.append(row)

        # 🔄 REESCRIBIR CSV
        with open(self.history_file, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=rows[0].keys())
            writer.writeheader()
            writer.writerows(rows)

        print("✅ Liquidación segura aplicada")

    # =====================================================
    # REPORTE SEMANAL PRO
    # =====================================================

    def weekly_report(self):

        total_stake=0
        total_profit=0
        wins=0
        losses=0

        with open(self.history_file,newline="",encoding="utf-8") as f:

            for row in csv.DictReader(f):

                if row["Resultado"] in ["GANADA","PERDIDA"]:

                    stake=float(row["Stake"])
                    profit=float(row["Ganancia_Neta"])

                    total_stake+=stake
                    total_profit+=profit

                    if profit>0:
                        wins+=1
                    else:
                        losses+=1

        if total_stake==0:
            return

        roi=(total_profit/total_stake)*100

        msg=f"""
📊 REPORTE SEMANAL SPORTIA

Picks: {wins+losses}
Wins: {wins}
Losses: {losses}

Stake Total: {total_stake:.2f}u
Profit: {total_profit:.2f}u

ROI: {roi:.2f}%
"""

        self._send_telegram(msg)

    # =====================================================
    # RUN
    # =====================================================

    def run(self):

        self._send_telegram("🤖 SPORTIA FUSION BOT ACTIVO")

        while True:

            self.scan_all()
            self.resolve_finished_matches()

            now=datetime.utcnow()

            if now.weekday()==6 and now.hour==23:
                if self.last_report_day!=now.date():
                    self.weekly_report()
                    self.last_report_day=now.date()

            time.sleep(900)


if __name__=="__main__":
    SportiaSecureScanner().run()