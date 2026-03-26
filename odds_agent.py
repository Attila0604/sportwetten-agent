import httpx
import os
from datetime import datetime

ODDS_API_KEY = os.getenv("ODDS_API_KEY")
BASE_URL = "https://api.the-odds-api.com/v4"

# Alle Fußball-Ligen die überwacht werden
SOCCER_SPORTS = [
    "soccer_germany_bundesliga",
    "soccer_england_league1",
    "soccer_epl",
    "soccer_spain_la_liga",
    "soccer_italy_serie_a",
    "soccer_france_ligue_one",
    "soccer_uefa_champs_league",
    "soccer_austria_bundesliga",
    # NEU: Diese Ligen spielen auch während der Länderspielpause!
    "soccer_fifa_world_cup_qualifiers",
    "soccer_friendly_international",
    "soccer_germany_bundesliga2"
]

async def fetch_odds_for_sport(client: httpx.AsyncClient, sport: str) -> list:
    """Holt Quoten für eine bestimmte Liga"""
    try:
        resp = await client.get(
            f"{BASE_URL}/sports/{sport}/odds/",
            params={
                "apiKey": ODDS_API_KEY,
                "regions": "eu", # Wir suchen im ganzen EU-Raum
                "markets": "h2h",
                "oddsFormat": "decimal",
                # Den strikten Bet365-Filter haben wir entfernt, um mehr Daten zu bekommen
            },
            timeout=15,
        )
        if resp.status_code == 200:
            return resp.json()
        return []
    except Exception:
        return []

async def fetch_all_football_odds() -> list:
    """Holt alle Fußball-Quoten"""
    all_games = []
    async with httpx.AsyncClient() as client:
        for sport in SOCCER_SPORTS:
            games = await fetch_odds_for_sport(client, sport)
            for game in games:
                game["liga"] = sport.replace("soccer_", "").replace("_", " ").title()
            all_games.extend(games)
    return all_games

async def fetch_results(sport: str) -> list:
    """Holt abgeschlossene Spielergebnisse"""
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{BASE_URL}/sports/{sport}/scores/",
                params={
                    "apiKey": ODDS_API_KEY,
                    "daysFrom": 1,
                },
                timeout=15,
            )
            if resp.status_code == 200:
                return resp.json()
    except Exception:
        pass
    return []

def parse_game(game: dict) -> dict:
    """Extrahiert die relevanten Daten eines Spiels, flexibel bei Buchmachern"""
    bookmakers = game.get("bookmakers", [])
    
    # Wenn gar kein Buchmacher Quoten hat, überspringen
    if not bookmakers:
        return None

    # Versuch 1: Wir suchen Bet365. 
    # Versuch 2: Wenn Bet365 nicht da ist, nehmen wir einfach den allerersten Buchmacher in der Liste!
    target_bookie = next((b for b in bookmakers if b["key"] == "bet365"), bookmakers[0])
    
    odds_data = None
    for market in target_bookie.get("markets", []):
        if market["key"] == "h2h":
            outcomes = {o["name"]: o["price"] for o in market["outcomes"]}
            odds_data = outcomes
            break

    if not odds_data:
        return None

    home_team = game.get("home_team", "")
    away_team = game.get("away_team", "")
    commence_time = game.get("commence_time", "")

    try:
        dt = datetime.fromisoformat(commence_time.replace("Z", "+00:00"))
        spiel_zeit = dt.strftime("%d.%m.%Y %H:%M")
    except Exception:
        spiel_zeit = commence_time

    return {
        "id": game.get("id"),
        "liga": game.get("liga", ""),
        "heim": home_team,
        "gast": away_team,
        "zeit": spiel_zeit,
        "quote_heim": odds_data.get(home_team, 0),
        "quote_unentschieden": odds_data.get("Draw", 0),
        "quote_gast": odds_data.get(away_team, 0),
    }

async def get_parsed_odds() -> list:
    """Gibt alle geparsten Spiele mit Quoten zurück"""
    raw = await fetch_all_football_odds()
    parsed = []
    for game in raw:
        p = parse_game(game)
        if p:
            parsed.append(p)
    return parsed
