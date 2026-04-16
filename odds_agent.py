"""
odds_agent.py  (v2 – median consensus + outlier protection)
────────────────────────────────────────────────────────────
Holt Quoten von The Odds API, parst sie und berechnet einen
robusten Konsens (Median) mit Outlier-Filterung.

Änderungen vs. v1:
  - Median statt Mittelwert als Konsens (robust gegen Daten-Ausreißer)
  - Bookie-Outlier werden verworfen, bevor max() die "beste Quote" nimmt
  - Robustere Bookie-Zuordnung (kein list.index()-Problem bei Gleichständen)
  - Exponential Backoff bei Rate-Limits (bis zu 3 Retries)
  - fetch_results() nutzt den sport-Parameter korrekt
  - Logging für Outlier-Verwerfungen
  - Nur SHARP Bookies beim Konsens (optional via ENV)
"""

import httpx
import asyncio
import os
import logging
from statistics import median
from datetime import datetime, timezone, timedelta

log = logging.getLogger(__name__)

# ─── Konfiguration ────────────────────────────────────────────────────────────
ODDS_API_KEY     = os.getenv("ODDS_API_KEY", "")
BASE_URL         = "https://api.the-odds-api.com/v4"
STUNDEN_VORAUS   = int(  os.getenv("STUNDEN_VORAUS",   "24"))
MIN_BOOKIE       = int(  os.getenv("MIN_BUCHMACHER",   "5"))
BOOKIE_OUTLIER   = float(os.getenv("BOOKIE_OUTLIER",   "0.20"))  # ±20% vom Median = Outlier

SPORT_KEYS = [
    "soccer_epl",
    "soccer_germany_bundesliga",
    "soccer_spain_la_liga",
    "soccer_italy_serie_a",
    "soccer_france_ligue_one",
    "soccer_uefa_champs_league",
    "soccer_austria_bundesliga",
]

# Optional: nur "sharp" Bookies für Konsens verwenden (Pinnacle, Bet365, etc.)
# Wenn leer, werden alle verwendet. Empfohlen für stabileren Konsens.
SHARP_BOOKIES = set(filter(None, os.getenv("SHARP_BOOKIES", "").split(",")))
# Beispiel: SHARP_BOOKIES="pinnacle,betfair,williamhill,bet365,marathonbet"


# ─── API-Fetch mit Retry ──────────────────────────────────────────────────────

async def _fetch_with_retry(client: httpx.AsyncClient, url: str, params: dict,
                            max_retries: int = 3) -> httpx.Response | None:
    """Exponential Backoff bei Rate-Limits (5s, 15s, 45s)."""
    for attempt in range(max_retries):
        try:
            resp = await client.get(url, params=params, timeout=20)
            if resp.status_code == 200:
                return resp
            if resp.status_code == 429:
                wait = 5 * (3 ** attempt)  # 5, 15, 45 sec
                log.warning("429 Rate-Limit, warte %ds (Versuch %d/%d)", wait, attempt+1, max_retries)
                await asyncio.sleep(wait)
                continue
            log.error("HTTP %d: %s", resp.status_code, resp.text[:200])
            return None
        except Exception as e:
            log.error("Fetch-Fehler: %s", e)
            await asyncio.sleep(2)
    return None


async def fetch_fixtures_with_odds() -> list:
    alle_spiele = []
    async with httpx.AsyncClient() as client:
        for sport_key in SPORT_KEYS:
            resp = await _fetch_with_retry(
                client,
                f"{BASE_URL}/sports/{sport_key}/odds",
                {
                    "apiKey":     ODDS_API_KEY,
                    "regions":    "eu",
                    "markets":    "h2h",
                    "oddsFormat": "decimal",
                },
            )
            if resp is None:
                print(f"  ❌ {sport_key}: übersprungen nach Retries")
                await asyncio.sleep(1)
                continue

            spiele = resp.json()
            alle_spiele.extend(spiele)
            print(f"  ✅ {sport_key}: {len(spiele)} Spiele")
            await asyncio.sleep(1)  # sanft zur API
    return alle_spiele


# ─── Zeit-Filter ──────────────────────────────────────────────────────────────

def ist_in_naechsten_stunden(start_time: str, stunden: int = 24) -> bool:
    try:
        dt = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
        jetzt  = datetime.now(timezone.utc)
        grenze = jetzt + timedelta(hours=stunden)
        return jetzt <= dt <= grenze
    except Exception:
        return False


# ─── Outlier-Schutz ───────────────────────────────────────────────────────────

def _filter_outliers(bookies: list, key: str) -> list:
    """
    Entfernt Bookies, deren Quote zu weit vom Median abweicht.
    Schützt vor Daten-Fehlern (Quote 15.0 statt 1.50 etc.).
    """
    quoten = [b[key] for b in bookies if b.get(key, 0) > 1.01]
    if len(quoten) < 3:
        return bookies  # zu wenig Daten für sinnvollen Outlier-Check

    med = median(quoten)
    lower = med * (1 - BOOKIE_OUTLIER)
    upper = med * (1 + BOOKIE_OUTLIER)

    gefiltert = []
    for b in bookies:
        q = b.get(key, 0)
        if q < 1.01:
            continue
        if q < lower or q > upper:
            log.warning("Outlier verworfen [%s]: Bookie=%s, Quote=%.2f, Median=%.2f",
                        key, b.get("name", "?"), q, med)
            continue
        gefiltert.append(b)
    return gefiltert


# ─── Spiel-Parser ─────────────────────────────────────────────────────────────

def parse_odds_api_game(fixture: dict) -> dict | None:
    start_time = fixture.get("commence_time", "")
    if not ist_in_naechsten_stunden(start_time, STUNDEN_VORAUS):
        return None

    heim = fixture.get("home_team", "")
    gast = fixture.get("away_team", "")
    liga = fixture.get("sport_key", "").replace("_", " ").title()

    if not heim or not gast:
        return None

    try:
        dt = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
        spiel_zeit = dt.strftime("%d.%m.%Y %H:%M")
    except Exception:
        spiel_zeit = start_time

    # 1. Bookie-Details sammeln (alle mit validen h2h-Quoten)
    bookie_details = []
    for bookmaker in fixture.get("bookmakers", []):
        bookie_name = bookmaker.get("key", "")
        for market in bookmaker.get("markets", []):
            if market.get("key") != "h2h":
                continue
            q_heim = q_unent = q_gast = 0
            for outcome in market.get("outcomes", []):
                name  = outcome.get("name", "")
                price = outcome.get("price", 0)
                if name == heim:
                    q_heim = price
                elif name == gast:
                    q_gast = price
                elif name == "Draw":
                    q_unent = price
            if q_heim > 1.01 and q_unent > 1.01 and q_gast > 1.01:
                bookie_details.append({
                    "name":                 bookie_name,
                    "quote_heim":           q_heim,
                    "quote_unentschieden":  q_unent,
                    "quote_gast":           q_gast,
                })

    if len(bookie_details) < MIN_BOOKIE:
        return None

    # 2. Sharp-Filter (optional): nur vertrauenswürdige Bookies für Konsens
    if SHARP_BOOKIES:
        sharp_only = [b for b in bookie_details if b["name"].lower() in SHARP_BOOKIES]
        if len(sharp_only) >= 3:
            konsens_basis = sharp_only
        else:
            konsens_basis = bookie_details  # Fallback wenn zu wenige Sharps
    else:
        konsens_basis = bookie_details

    # 3. Outlier je Markt rausfiltern
    clean_heim  = _filter_outliers(konsens_basis, "quote_heim")
    clean_unent = _filter_outliers(konsens_basis, "quote_unentschieden")
    clean_gast  = _filter_outliers(konsens_basis, "quote_gast")

    if min(len(clean_heim), len(clean_unent), len(clean_gast)) < 3:
        log.info("Zu wenige Bookies nach Outlier-Filter: %s vs %s", heim, gast)
        return None

    # 4. Konsens = MEDIAN (robust)
    konsens_heim  = round(median(b["quote_heim"]          for b in clean_heim),  3)
    konsens_unent = round(median(b["quote_unentschieden"] for b in clean_unent), 3)
    konsens_gast  = round(median(b["quote_gast"]          for b in clean_gast),  3)

    # 5. Beste Quote aus BEREINIGTEN Bookies (nicht mehr aus Ausreißern!)
    def beste_mit_bookie(bookies: list, key: str) -> tuple[float, str]:
        if not bookies:
            return 0.0, ""
        best = max(bookies, key=lambda b: b[key])
        return best[key], best["name"]

    beste_heim,  bookie_heim  = beste_mit_bookie(clean_heim,  "quote_heim")
    beste_unent, bookie_unent = beste_mit_bookie(clean_unent, "quote_unentschieden")
    beste_gast,  bookie_gast  = beste_mit_bookie(clean_gast,  "quote_gast")

    return {
        "id":                        fixture.get("id"),
        "liga":                      liga,
        "heim":                      heim,
        "gast":                      gast,
        "zeit":                      spiel_zeit,
        "quote_heim":                konsens_heim,
        "quote_unentschieden":       konsens_unent,
        "quote_gast":                konsens_gast,
        "beste_quote_heim":          beste_heim,
        "beste_quote_heim_bookie":   bookie_heim,
        "beste_quote_unentschieden": beste_unent,
        "beste_quote_unent_bookie":  bookie_unent,
        "beste_quote_gast":          beste_gast,
        "beste_quote_gast_bookie":   bookie_gast,
        "anzahl_buchmacher":         len(bookie_details),
        "anzahl_konsens_bookies":    len(clean_heim),
        "alle_buchmacher":           bookie_details,
    }


# ─── Orchestrierung ───────────────────────────────────────────────────────────

async def get_parsed_odds() -> list:
    raw = await fetch_fixtures_with_odds()
    parsed = []
    for fixture in raw:
        p = parse_odds_api_game(fixture)
        if p:
            parsed.append(p)
    print(f"  → {len(parsed)} Spiele in den nächsten {STUNDEN_VORAUS}h ({len(raw)} gesamt)")
    return parsed


async def fetch_results(sport: str | None = None) -> list:
    """
    Holt Spielergebnisse. Wenn 'sport' angegeben, nur für diese Liga.
    Sonst für alle konfigurierten SPORT_KEYS.
    """
    sport_keys = [sport] if sport else SPORT_KEYS
    alle_results = []
    async with httpx.AsyncClient() as client:
        for sport_key in sport_keys:
            resp = await _fetch_with_retry(
                client,
                f"{BASE_URL}/sports/{sport_key}/scores",
                {"apiKey": ODDS_API_KEY, "daysFrom": 1},
            )
            if resp is not None:
                alle_results.extend(resp.json())
            await asyncio.sleep(1)
    return alle_results
