import httpx
import os
from datetime import datetime, timezone, timedelta

ODDS_API_KEY = os.getenv("ODDS_API_KEY", "")
BASE_URL = "https://api.the-odds-api.com/v4"

STUNDEN_VORAUS = int(os.getenv("STUNDEN_VORAUS", "24"))

SPORT_KEYS = [
    "soccer_epl",
    "soccer_germany_bundesliga",
    "soccer_spain_la_liga",
    "soccer_italy_serie_a",
    "soccer_france_ligue_one",
    "soccer_uefa_champs_league",
    "soccer_austria_bundesliga",
]


async def fetch_fixtures_with_odds() -> list:
    alle_spiele = []
    async with httpx.AsyncClient() as client:
        for sport_key in SPORT_KEYS:
            try:
                resp = await client.get(
                    f"{BASE_URL}/sports/{sport_key}/odds",
                    params={
                        "apiKey": ODDS_API_KEY,
                        "regions": "eu",
                        "markets": "h2h",
                        "oddsFormat": "decimal",
                    },
                    timeout=20,
                )
                if resp.status_code == 200:
                    spiele = resp.json()
                    alle_spiele.extend(spiele)
                    print(f"  ✅ {sport_key}: {len(spiele)} Spiele")
                else:
                    print(f"  ❌ {sport_key}: {resp.status_code} - {resp.text[:100]}")
            except Exception as e:
                print(f"  ❌ {sport_key} Fehler: {e}")
    return alle_spiele


def ist_in_naechsten_stunden(start_time: str, stunden: int = 24) -> bool:
    try:
        dt = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
        jetzt = datetime.now(timezone.utc)
        grenze = jetzt + timedelta(hours=stunden)
        return jetzt <= dt <= grenze
    except Exception:
        return False


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

    heim_quoten = []
    unent_quoten = []
    gast_quoten = []
    bookie_details = []

    for bookmaker in fixture.get("bookmakers", []):
        bookie_name = bookmaker.get("key", "")
        for market in bookmaker.get("markets", []):
            if market.get("key") != "h2h":
                continue
            outcomes = market.get("outcomes", [])
            q_heim = 0
            q_unent = 0
            q_gast = 0
            for outcome in outcomes:
                name = outcome.get("name", "")
                price = outcome.get("price", 0)
                if name == heim:
                    q_heim = price
                elif name == gast:
                    q_gast = price
                elif name == "Draw":
                    q_unent = price
            if q_heim > 1 and q_unent > 1 and q_gast > 1:
                heim_quoten.append(q_heim)
                unent_quoten.append(q_unent)
                gast_quoten.append(q_gast)
                bookie_details.append({
                    "name": bookie_name,
                    "quote_heim": q_heim,
                    "quote_unentschieden": q_unent,
                    "quote_gast": q_gast,
                })

    if len(heim_quoten) < 3:
        return None

    konsens_heim = round(sum(heim_quoten) / len(heim_quoten), 3)
    konsens_unent = round(sum(unent_quoten) / len(unent_quoten), 3)
    konsens_gast = round(sum(gast_quoten) / len(gast_quoten), 3)

    beste_heim = max(heim_quoten)
    beste_unent = max(unent_quoten)
    beste_gast = max(gast_quoten)
    bookie_heim = bookie_details[heim_quoten.index(beste_heim)]["name"]
    bookie_unent = bookie_details[unent_quoten.index(beste_unent)]["name"]
    bookie_gast = bookie_details[gast_quoten.index(beste_gast)]["name"]

    return {
        "id": fixture.get("id"),
        "liga": liga,
        "heim": heim,
        "gast": gast,
        "zeit": spiel_zeit,
        "quote_heim": konsens_heim,
        "quote_unentschieden": konsens_unent,
        "quote_gast": konsens_gast,
        "beste_quote_heim": beste_heim,
        "beste_quote_heim_bookie": bookie_heim,
        "beste_quote_unentschieden": beste_unent,
        "beste_quote_unent_bookie": bookie_unent,
        "beste_quote_gast": beste_gast,
        "beste_quote_gast_bookie": bookie_gast,
        "anzahl_buchmacher": len(heim_quoten),
        "alle_buchmacher": bookie_details,
    }


async def get_parsed_odds() -> list:
    raw = await fetch_fixtures_with_odds()
    parsed = []
    for fixture in raw:
        p = parse_odds_api_game(fixture)
        if p:
            parsed.append(p)
    print(f"  → {len(parsed)} Spiele in den nächsten {STUNDEN_VORAUS}h ({len(raw)} gesamt)")
    return parsed


async def fetch_results(sport: str = None) -> list:
    alle_results = []
    async with httpx.AsyncClient() as client:
        for sport_key in SPORT_KEYS:
            try:
                resp = await client.get(
                    f"{BASE_URL}/sports/{sport_key}/scores",
                    params={
                        "apiKey": ODDS_API_KEY,
                        "daysFrom": 1,
                    },
                    timeout=15,
                )
                if resp.status_code == 200:
                    alle_results.extend(resp.json())
            except Exception as e:
                print(f"  Results Fehler [{sport_key}]: {e}")
    return alle_results
