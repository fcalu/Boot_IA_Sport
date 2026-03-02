import requests
import time
import csv
import os
from datetime import datetime, timedelta
from dotenv import load_dotenv
from zoneinfo import ZoneInfo
load_dotenv()

class SportiaSecureScanner:
    def __init__(self):
        
        
        # --- CONFIGURACIÓN ---
        self.api_base = "https://sportia-api.onrender.com/api/v1"
        self.espn_api = "https://site.api.espn.com/apis/site/v2/sports"

        self.token = os.getenv("TELEGRAM_TOKEN")
        self.chat_id = os.getenv("TELEGRAM_CHAT_ID")

        if not self.token or not self.chat_id:
            raise ValueError("Faltan variables TELEGRAM_TOKEN o TELEGRAM_CHAT_ID")

        # Parámetros de Estrategia
        self.min_edge = 0.05
        self.secure_edge = 0.12
        self.stake_base = 10.0
        self.use_kelly = True
        self.unit_size_mxn = 100  # 1 unidad = $100 MXN
        self.kelly_multiplier = 0.5  # 50% Kelly
        # Archivos y Memoria
        self.history_file = "auditoria_ganancias.csv"
        self.sent_ids = set()

        self._init_history()
        self._load_sent_ids()

        self.sports_config = {
            "soccer": ["ENG.1", "ESP.1", "GER.1", "ITA.1", "FRA.1", "POR.1",
                    "UEFA.CHAMPIONS", "UEFA.EUROPA", "UEFA.CONFERENCE",
                    "MEX.1", "USA.1", "BRA.1", "CONMEBOL.LIBERTADORES"],
            "basketball": ["nba"]
        }

    # ===============================
    # GESTIÓN DE DATOS
    # ===============================

    def _init_history(self):
        if not os.path.exists(self.history_file):
            with open(self.history_file, mode="w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow([
                    "ID", "Fecha", "Partido", "Pick",
                    "Momio", "Prob_Modelo", "Edge", "Stake",
                    "Resultado", "Ganancia_Neta", "Deporte", "Liga"
                ])

    def _load_sent_ids(self):
        if not os.path.exists(self.history_file): return
        with open(self.history_file, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                self.sent_ids.add(f"{row['ID']}_{row['Pick']}")

    # ===============================
    # CÁLCULOS MATEMÁTICOS
    # ===============================

    def american_to_decimal(self, odds):
        return 1 + (odds / 100) if odds > 0 else 1 + (100 / abs(odds))

    def implied_prob(self, odds):
        if odds > 0: return 100 / (odds + 100)
        return abs(odds) / (abs(odds) + 100)

    def kelly_fraction(self, prob, decimal_odds):
        b = decimal_odds - 1
        q = 1 - prob
        return max((b * prob - q) / b, 0)
    
    def safe_get(self, url, retries=3, timeout=40):
        for attempt in range(retries):
            try:
                response = requests.get(url, timeout=timeout)
                response.raise_for_status()
                return response.json()
            except requests.exceptions.Timeout:
                print(f"⏳ Timeout GET intento {attempt+1}/{retries}")
                time.sleep(3)
            except requests.exceptions.RequestException as e:
                print(f"❌ Error GET: {e}")
                time.sleep(2)
        return None


    def safe_post(self, url, payload, retries=3, timeout=40):
        for attempt in range(retries):
            try:
                response = requests.post(url, json=payload, timeout=timeout)
                response.raise_for_status()
                return response.json()
            except requests.exceptions.Timeout:
                print(f"⏳ Timeout POST intento {attempt+1}/{retries}")
                time.sleep(3)
            except requests.exceptions.RequestException as e:
                print(f"❌ Error POST: {e}")
                time.sleep(2)
        return None
    # ===============================
    # AUDITORÍA DE RESULTADOS
    # ===============================

    def check_results_and_report(self):
        """Busca resultados de partidos pendientes en ESPN y genera resumen."""
        print("🔄 Revisando resultados pendientes en ESPN...")
        updated_rows = []
        new_settled_count = 0
        profit_session = 0

        if not os.path.exists(self.history_file): return

        with open(self.history_file, mode="r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        for row in rows:
            if row["Resultado"] == "PENDIENTE":
                try:
                    # Buscamos el evento en ESPN
                    sport = row.get("Deporte", "soccer")
                    liga = row.get("Liga", "mex.1").lower()
                    res = requests.get(f"{self.espn_api}/{sport}/{liga}/scoreboard", timeout=10).json()
                    
                    event = next((e for e in res.get('events', []) if e['id'] == row['ID']), None)
                    
                    if event and event['status']['type']['state'] == 'post':
                        # Determinar ganador
                        winner = self._determine_winner(event, row['Pick'])
                        stake = float(row['Stake'])
                        odds = float(row['Momio'])
                        
                        if winner == "WIN":
                            row["Resultado"] = "GANADA ✅"
                            net_profit = stake * (self.american_to_decimal(odds) - 1)
                            row["Ganancia_Neta"] = round(net_profit, 2)
                        else:
                            row["Resultado"] = "PERDIDA ❌"
                            row["Ganancia_Neta"] = -stake
                        
                        profit_session += float(row["Ganancia_Neta"])
                        new_settled_count += 1
                except Exception as e:
                    print(f"Error auditando ID {row['ID']}: {e}")
            
            updated_rows.append(row)

        if new_settled_count > 0:
            with open(self.history_file, mode="w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=updated_rows[0].keys())
                writer.writeheader()
                writer.writerows(updated_rows)
            
            self.send_alert(f"💰 *CIERRE DE JORNADA*\nPartidos liquidados: {new_settled_count}\nGanancia neta: `${profit_session:.2f}`")

    def _determine_winner(self, event, pick):
    
        comp = event['competitions'][0]
        home_score = int(comp['competitors'][0]['score'])
        away_score = int(comp['competitors'][1]['score'])
        total = home_score + away_score

        pick_lower = pick.lower()

        # TOTAL GOALS
        if "total goals" in pick_lower:
            if "under" in pick_lower:
                line = float(pick_lower.split("under")[1].strip())
                return "WIN" if total < line else "LOSS"
            if "over" in pick_lower:
                line = float(pick_lower.split("over")[1].strip())
                return "WIN" if total > line else "LOSS"

        # MONEYLINE
        if "home" in pick_lower and home_score > away_score:
            return "WIN"
        if "away" in pick_lower and away_score > home_score:
            return "WIN"
        if "draw" in pick_lower and home_score == away_score:
            return "WIN"

        return "LOSS"

    # ===============================
    # SCANNER
    # ===============================
    def calibrate_probability(self, prob):
        shrink = 0.97
        return prob * shrink


    def scan_all(self):
        print(f"\n🔎 [{datetime.now().strftime('%H:%M:%S')}] Escaneando...")
        picks_found = 0
        daily_exposure = 0
        max_daily_units = 12
        max_units_per_bet = 3

        for sport in self.sports_config.keys():

            matches = self.safe_get(
                f"{self.api_base}/matches/upcoming?sport={sport if sport!='basketball' else 'nba'}"
            )

            if not matches:
                continue

            for match in matches:

                if match.get("status") in ["FT", "Final"]:
                    continue

                match_date_raw = match.get("start_time")

                if match_date_raw:
                    try:
                        match_date = datetime.fromisoformat(
                            match_date_raw.replace("Z", "+00:00")
                        )
                        match_date_str = match_date.strftime("%d %b %Y %H:%M")
                    except:
                        match_date_str = "Fecha no disponible"
                else:
                    match_date_str = "Fecha no disponible"

                payload = {
                    "sport": sport,
                    "league": match.get("league", sport),
                    "event_id": str(match["event_id"]),
                    "home_team": match["home"],
                    "away_team": match["away"]
                }

                pred = self.safe_post(f"{self.api_base}/ai/predict", payload)
                if not pred:
                    continue

                for prop in pred.get("player_props", []):

                    if prop.get("bet_tier") != "VALUE_BET":
                        continue

                    confidence = prop.get("confidence", 0)
                    if confidence < 60:
                        continue

                    decision = prop.get("bet_decision")
                    if decision == "PASS":
                        continue

                    if decision == "OVER":
                        my_prob = prop.get("model_prob_over")
                        market_odds = prop.get("over_odds")
                    elif decision == "UNDER":
                        my_prob = prop.get("model_prob_under")
                        market_odds = prop.get("under_odds")
                    else:
                        my_prob = prop.get("model_prob")
                        market_odds = None

                    if not my_prob or not market_odds:
                        continue

                    # Calibración
                    my_prob = self.calibrate_probability(my_prob)

                    # Probabilidad de mercado
                    market_prob = self.implied_prob(market_odds)

                    # Edge real
                    real_edge = my_prob - market_prob

                    if real_edge < 0.03:
                        continue

                    # Filtro momios extremos
                    if market_odds < -200 or market_odds > 350:
                        continue

                    decimal_odds = self.american_to_decimal(market_odds)

                    # Kelly dinámico por confianza
                    if confidence >= 80:
                        kelly_mult = 0.7
                    elif confidence >= 70:
                        kelly_mult = 0.5
                    else:
                        kelly_mult = 0.3

                    kelly_raw = self.kelly_fraction(my_prob, decimal_odds)
                    kelly = kelly_raw * kelly_mult

                    units = round(kelly * self.stake_base, 2)

                    if units <= 0:
                        continue

                    # Limitar riesgo
                    units = min(units, max_units_per_bet)

                    if daily_exposure + units > max_daily_units:
                        continue

                    daily_exposure += units

                    stake_mxn = round(units * self.unit_size_mxn, 2)

                    ev = (my_prob * decimal_odds) - 1
                    ev_percent = ev * 100

                    line = prop.get("line")
                    pick_text = f"{decision} {line}" if line else decision

                    emoji = "⚽" if sport == "soccer" else "🏀"

                    msg = (
                        f"📊 VALUE PROFESIONAL\n"
                        f"{emoji} *{match['home']} vs {match['away']}*\n"
                        f"🗓 {match_date_str}\n\n"
                        f"📌 Pick: *{pick_text}*\n"
                        f"📊 Prob Ajustada: {my_prob*100:.1f}%\n"
                        f"🔥 Edge Real: +{real_edge*100:.2f}%\n"
                        f"📈 EV: +{ev_percent:.2f}%\n"
                        f"💰 Momio: {market_odds}\n\n"
                        f"💎 Stake: {units}u\n"
                        f"💵 Apostar: ${stake_mxn} MXN"
                    )

                    self.send_alert(msg)
                    picks_found += 1

        self.send_status(f"Escaneo OK. Picks nuevos: {picks_found}")

    # ===============================
    # TELEGRAM & LOOP
    # ===============================

    def send_alert(self, msg):
        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        try: requests.post(url, json={"chat_id": self.chat_id, "text": msg, "parse_mode": "Markdown"}, timeout=10)
        except: pass

    def send_status(self, text):
        self.send_alert(f"🤖 {text}")

    def run(self):
        self.send_status("Bot iniciado correctamente ✅")
        while True:
            try:
                self.scan_all()
                self.check_results_and_report() # Audita ganancias automáticamente
            except Exception as e:
                print(f"Error en loop: {e}")
            
            print("💤 Esperando 15 min...")
            time.sleep(900)

if __name__ == "__main__":
    SportiaSecureScanner().run()