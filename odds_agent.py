"""
odds_agent.py  (v3 – credit-optimiert)
────────────────────────────────────────────────────────────
Änderungen vs. v2:
  - API-seitiger Zeitfilter (commenceTimeFrom/To) → weniger Daten übertragen
  - Nur aktive Ligen werden abgefragt (Saison-Check via /sports endpoint)
  - fetch_results() nur für übergebene Sport-Keys (keine 7-Ligen-Vollabfrage)
  - In-Memory Cache (15 Min TTL) verhindert Doppel-Requests im selben Lauf
  - Credit-Verbrauch: ~70-80% weniger als v2
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
STUNDEN_VORAUS   = int(  os.getenv("STUNDEN_VORAUS",   "48"))   # 48h statt 24h = 1x täglich reicht
MIN_BOOKIE       = int(  os.getenv("MIN_BUCHMACHER",   "5"))
BOOKIE_OUTLIER   = float(os.getenv("BOOKIE_OUTLIER",   "0.20"))

SPORT_KEYS = [
    "soccer_fifa_world_cup",
    "soccer_epl",
    "soccer_germany_bundesliga",
    "soccer_spain_la_liga",
    "soccer_italy_serie_a",
    "soccer_france_ligue_one",
    "soccer_uefa_champs_league",
    "soccer_austria_bundesliga",
]

SHARP_BOOKIES = set(filter(None, os.getenv("SHARP_BOOKIES", "").split(",")))

# ─── In-Memory Cache ──────────────────────────────────────────────────────────
_cache: dict = {}
CACHE_TTL_MINUTEN = 15

def _cache_get(key: str):
    entry = _cache.get(key)
    if entry and (datetime.now() - entry["ts"]).seconds < CACHE_TTL_MINUTEN * 60:
        log.info("Cache-Hit: %s", key)
        return entry["data"]
    return None

def _cache_set(key: str, data):
    _cache[key] = {"ts": datetime.now(), "data": data}


# ─── Aktive Ligen ermitteln (1 API-Call für alle!) ───────────────────────────

async def get_aktive_sport_keys(client: httpx.AsyncClient) -> list[str]:
    """
    Holt die Liste aktiver Sportarten von The Odds API.
    Kostet nur 1 Credit und erspart unnötige Ligen-Abfragen.
    """
    cached = _cache_get("aktive_sports")
    if cached:
        return cached

    resp = await _fetch_with_retry(
        client,
        f"{BASE_URL}/sports",
        {"apiKey": ODDS_API_KEY, "all": "false"},  # only active sports
    )
    if resp is None:
        log.warning("Konnte aktive Sports nicht laden, nutze alle SPORT_KEYS")
        return SPORT_KEYS

    aktive = {s["key"] for s in resp.json() if s.get("active", False)}
    result = [k for k in SPORT_KEYS if k in aktive]
    log.info("Aktive Ligen (%d/%d): %s", len(result), len(SPORT_KEYS), result)
    _cache_set("aktive_sports", result)
    return result


# ─── API-Fetch mit Retry ──────────────────────────────────────────────────────

async def _fetch_with_retry(client: httpx.AsyncClient, url: str, params: dict,
                            max_retries: int = 3) -> httpx.Response | None:
    """Exponential Backoff bei Rate-Limits (5s, 15s, 45s)."""
    for attempt in range(max_retries):
        try:
            resp = await client.get(url, params=params, timeout=20)
            if resp.status_code == 200:
                # Verbleibende Credits loggen
                remaining = resp.headers.get("x-requests-remaining", "?")
                used = resp.headers.get("x-requests-used", "?")
                log.debug("Credits: %s genutzt, %s verbleibend", used, remaining)
                return resp
            if resp.status_code == 401:
                log.error("HTTP 401 – OUT_OF_CREDITS oder ungültiger API Key!")
                return None  # Sofort abbrechen, kein Retry
            if resp.status_code == 429:
                wait = 5 * (3 ** attempt)
                log.warning("429 Rate-Limit, warte %ds (Versuch %d/%d)", wait, attempt+1, max_retries)
                await asyncio.sleep(wait)
                continue
            log.error("HTTP %d: %s", resp.status_code, resp.text[:200])
            return None
        except Exception as e:
            log.error("Fetch-Fehler: %s", e)
            await asyncio.sleep(2)
    return None


# ─── Hauptfunktion: Quoten holen (credit-optimiert) ──────────────────────────

async def fetch_fixtures_with_odds() -> list:
    """
    NEU v3: 
    1. Erst aktive Ligen prüfen (1 Credit)
    2. Zeitfenster direkt in der API-Anfrage (weniger Daten = weniger Credits)
    3. Cache verhindert Doppelabfragen
    """
    alle_spiele = []
    jetzt = datetime.now(timezone.utc)
    bis   = jetzt + timedelta(hours=STUNDEN_VORAUS)

    # ISO-Format für API-Parameter
    von_str = jetzt.strftime("%Y-%m-%dT%H:%M:%SZ")
    bis_str = bis.strftime("%Y-%m-%dT%H:%M:%SZ")

    async with httpx.AsyncClient() as client:
        # Schritt 1: Nur aktive Ligen abfragen (spart Credits bei inaktiven Ligen)
        aktive_keys = await get_aktive_sport_keys(client)
        await asyncio.sleep(0.5)

        for sport_key in aktive_keys:
            cache_key = f"odds_{sport_key}"
            cached = _cache_get(cache_key)
            if cached is not None:
                alle_spiele.extend(cached)
                print(f"  📦 {sport_key}: {len(cached)} Spiele (aus Cache)")
                continue

            resp = await _fetch_with_retry(
                client,
                f"{BASE_URL}/sports/{sport_key}/odds",
                {
                    "apiKey":             ODDS_API_KEY,
                    "regions":            "eu",
                    "markets":            "h2h",
                    "oddsFormat":         "decimal",
                    "commenceTimeFrom":   von_str,   # NEU: API-seitiger Zeitfilter
                    "commenceTimeTo":     bis_str,   # → weniger Daten = weniger Credits
                },
            )
            if resp is None:
                print(f"  ❌ {sport_key}: übersprungen nach Retries")
                await asyncio.sleep(1)
                continue

            spiele = resp.json()
            _cache_set(cache_key, spiele)
            alle_spiele.extend(spiele)
            print(f"  ✅ {sport_key}: {len(spiele)} Spiele")
            await asyncio.sleep(0.5)  # etwas kürzer da weniger Daten

    return alle_spiele


# ─── Zeit-Filter (Fallback, da API jetzt filtert) ─────────────────────────────

def ist_in_naechsten_stunden(start_time: str, stunden: int = 48) -> bool:
    try:
        dt = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
        jetzt  = datetime.now(timezone.utc)
        grenze = jetzt + timedelta(hours=stunden)
        return jetzt <= dt <= grenze
    except Exception:
        return False


# ─── Outlier-Schutz ───────────────────────────────────────────────────────────

def _filter_outliers(bookies: list, key: str) -> list:
    quoten = [b[key] for b in bookies if b.get(key, 0) > 1.01]
    if len(quoten) < 3:
        return bookies

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
    # Zeitfilter als Fallback (API filtert bereits, aber sicher ist sicher)
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
                    "name":                bookie_name,
                    "quote_heim":          q_heim,
                    "quote_unentschieden": q_unent,
                    "quote_gast":          q_gast,
                })

    if len(bookie_details) < MIN_BOOKIE:
        return None

    if SHARP_BOOKIES:
        sharp_only = [b for b in bookie_details if b["name"].lower() in SHARP_BOOKIES]
        konsens_basis = sharp_only if len(sharp_only) >= 3 else bookie_details
    else:
        konsens_basis = bookie_details

    clean_heim  = _filter_outliers(konsens_basis, "quote_heim")
    clean_unent = _filter_outliers(konsens_basis, "quote_unentschieden")
    clean_gast  = _filter_outliers(konsens_basis, "quote_gast")

    if min(len(clean_heim), len(clean_unent), len(clean_gast)) < 3:
        return None

    konsens_heim  = round(median(b["quote_heim"]          for b in clean_heim),  3)
    konsens_unent = round(median(b["quote_unentschieden"] for b in clean_unent), 3)
    konsens_gast  = round(median(b["quote_gast"]          for b in clean_gast),  3)

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


async def fetch_results(sport_keys: list[str] | None = None) -> list:
    """
    NEU v3: Nur für übergebene sport_keys (z.B. nur Ligen mit aktiven Bets).
    Statt alle 7 Ligen = massive Credit-Ersparnis!
    
    Aufruf-Beispiel im results_agent:
        sport_keys = list({bet["liga_key"] for bet in offene_bets})
        results = await fetch_results(sport_keys)
    """
    keys_to_fetch = sport_keys if sport_keys else SPORT_KEYS
    
    if not sport_keys:
        log.warning("fetch_results() ohne sport_keys → alle %d Ligen werden abgefragt!", len(SPORT_KEYS))

    alle_results = []
    async with httpx.AsyncClient() as client:
        for sport_key in keys_to_fetch:
            cache_key = f"results_{sport_key}"
            cached = _cache_get(cache_key)
            if cached is not None:
                alle_results.extend(cached)
                continue

            resp = await _fetch_with_retry(
                client,
                f"{BASE_URL}/sports/{sport_key}/scores",
                {"apiKey": ODDS_API_KEY, "daysFrom": 1},
            )
            if resp is not None:
                data = resp.json()
                _cache_set(cache_key, data)
                alle_results.extend(data)
            await asyncio.sleep(0.5)
    return alle_results
