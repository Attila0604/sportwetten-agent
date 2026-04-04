import httpx
import os
from datetime import datetime, timezone, timedelta

# Wie viele Stunden in die Zukunft schauen (Standard: 24h)
STUNDEN_VORAUS = int(os.getenv("STUNDEN_VORAUS", "24"))

ODDS_API_KEY = os.getenv("ODDS_API_KEY")
BASE_URL = "https://api.the-odds-api.com/v4"

SOCCER_SPORTS = [
    "soccer_germany_bundesliga",
    "soccer_england_league1",
    "soccer_epl",
    "soccer_spain_la_liga",
    "soccer_italy_serie_a",
    "soccer_france_ligue_one",
    "soccer_uefa_champs_league",
    "soccer_austria_bundesliga",
    "soccer_fifa_world_cup_qualifiers",
    "soccer_friendly_international",
    "soccer_germany_bundesliga2",
]


async def fetch_odds_for_sport(client: httpx.AsyncClient, sport: str) -> list:
    """Holt Quoten für eine bestimmte Liga – alle verfügbaren Buchmacher"""
    try:
        resp = await client.get(
            f"{BASE_URL}/sports/{sport}/odds/",
            params={
                "apiKey": ODDS_API_KEY,
                "regions": "eu",
                "markets": "h2h",
                "oddsFormat": "decimal",
            },
            timeout=15,
        )
        if resp.status_code == 200:
            return resp.json()
        return []
    except Exception:
        return []


async def fetch_all_football_odds() -> list:
    """Holt alle Fußball-Quoten von allen verfügbaren Buchmachern"""
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
                params={"apiKey": ODDS_API_KEY, "daysFrom": 1},
                timeout=15,
            )
            if resp.status_code == 200:
                return resp.json()
    except Exception:
        pass
    return []


def ist_in_naechsten_stunden(commence_time: str, stunden: int = 24) -> bool:
    """Prüft ob das Spiel innerhalb der nächsten X Stunden stattfindet."""
    try:
        dt = datetime.fromisoformat(commence_time.replace("Z", "+00:00"))
        jetzt = datetime.now(timezone.utc)
        grenze = jetzt + timedelta(hours=stunden)
        return jetzt <= dt <= grenze
    except Exception:
        return False


def berechne_konsens(bookmakers: list, home_team: str, away_team: str) -> dict | None:
    """
    Berechnet Konsens-Quoten aus ALLEN verfügbaren Buchmachers.
    Gibt None zurück wenn weniger als 3 Buchmacher verfügbar sind.
    """
    heim_quoten = []
    unent_quoten = []
    gast_quoten = []
    bookie_details = []

    for bookie in bookmakers:
        for market in bookie.get("markets", []):
            if market["key"] != "h2h":
                continue
            outcomes = {o["name"]: o["price"] for o in market["outcomes"]}
            q_heim = outcomes.get(home_team, 0)
            q_unent = outcomes.get("Draw", 0)
            q_gast = outcomes.get(away_team, 0)

            # Nur verwenden wenn alle 3 Quoten vorhanden
            if q_heim > 1 and q_unent > 1 and q_gast > 1:
                heim_quoten.append(q_heim)
                unent_quoten.append(q_unent)
                gast_quoten.append(q_gast)
                bookie_details.append({
                    "name": bookie["key"],
                    "quote_heim": q_heim,
                    "quote_unentschieden": q_unent,
                    "quote_gast": q_gast,
                })

    # Mindestens 3 Buchmacher für zuverlässigen Konsens
    if len(heim_quoten) < 3:
        return None

    konsens_heim  = round(sum(heim_quoten) / len(heim_quoten), 3)
    konsens_unent = round(sum(unent_quoten) / len(unent_quoten), 3)
    konsens_gast  = round(sum(gast_quoten) / len(gast_quoten), 3)

    return {
        "konsens_quote_heim": konsens_heim,
        "konsens_quote_unentschieden": konsens_unent,
        "konsens_quote_gast": konsens_gast,
        "anzahl_buchmacher": len(heim_quoten),
        "alle_buchmacher": bookie_details,
    }


def finde_beste_quote(bookmakers: list, home_team: str, away_team: str) -> dict:
    """
    Findet die beste verfügbare Quote für jedes Ergebnis
    (für den Fall dass der User manuell wettet).
    """
    beste = {"heim": 0, "unentschieden": 0, "gast": 0,
             "bookie_heim": "", "bookie_unent": "", "bookie_gast": ""}

    for bookie in bookmakers:
        for market in bookie.get("markets", []):
            if market["key"] != "h2h":
                continue
            outcomes = {o["name"]: o["price"] for o in market["outcomes"]}
            q_heim  = outcomes.get(home_team, 0)
            q_unent = outcomes.get("Draw", 0)
            q_gast  = outcomes.get(away_team, 0)

            if q_heim > beste["heim"]:
                beste["heim"] = q_heim
                beste["bookie_heim"] = bookie["key"]
            if q_unent > beste["unentschieden"]:
                beste["unentschieden"] = q_unent
                beste["bookie_unent"] = bookie["key"]
            if q_gast > beste["gast"]:
                beste["gast"] = q_gast
                beste["bookie_gast"] = bookie["key"]

    return beste


def parse_game(game: dict) -> dict | None:
    """
    Extrahiert relevante Daten + Konsens-Quoten aller Buchmacher.
    Gibt None zurück wenn zu wenig Daten vorhanden.
    """
    # ── 24h Filter ────────────────────────────────────────────────────────────
    if not ist_in_naechsten_stunden(game.get("commence_time", ""), STUNDEN_VORAUS):
        return None

    bookmakers = game.get("bookmakers", [])
    if not bookmakers:
        return None

    home_team = game.get("home_team", "")
    away_team = game.get("away_team", "")

    # Konsens aus ALLEN Buchmachers berechnen
    konsens = berechne_konsens(bookmakers, home_team, away_team)
    if not konsens:
        return None  # Zu wenige Buchmacher → überspringen

    # Beste verfügbare Quote finden
    beste = finde_beste_quote(bookmakers, home_team, away_team)

    # Bet365 Quote falls vorhanden (für Referenz)
    bet365 = next((b for b in bookmakers if b["key"] == "bet365"), None)
    bet365_quoten = {}
    if bet365:
        for market in bet365.get("markets", []):
            if market["key"] == "h2h":
                outcomes = {o["name"]: o["price"] for o in market["outcomes"]}
                bet365_quoten = {
                    "bet365_heim": outcomes.get(home_team, 0),
                    "bet365_unentschieden": outcomes.get("Draw", 0),
                    "bet365_gast": outcomes.get(away_team, 0),
                }

    # Zeitformat
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

        # Konsens-Quoten (Durchschnitt aller Buchmacher)
        "quote_heim": konsens["konsens_quote_heim"],
        "quote_unentschieden": konsens["konsens_quote_unentschieden"],
        "quote_gast": konsens["konsens_quote_gast"],

        # Beste verfügbare Quoten (wo soll man wetten?)
        "beste_quote_heim": beste["heim"],
        "beste_quote_heim_bookie": beste["bookie_heim"],
        "beste_quote_unentschieden": beste["unentschieden"],
        "beste_quote_unent_bookie": beste["bookie_unent"],
        "beste_quote_gast": beste["gast"],
        "beste_quote_gast_bookie": beste["bookie_gast"],

        # Bet365 Referenz
        **bet365_quoten,

        # Metadaten
        "anzahl_buchmacher": konsens["anzahl_buchmacher"],
        "alle_buchmacher": konsens["alle_buchmacher"],
    }


async def get_parsed_odds() -> list:
    """Gibt alle geparsten Spiele mit Konsens-Quoten zurück"""
    raw = await fetch_all_football_odds()
    parsed = []
    for game in raw:
        p = parse_game(game)
        if p:
            parsed.append(p)
    print(f"  → {len(parsed)} Spiele in den nächsten {STUNDEN_VORAUS}h (min. 3 Buchmacher)")
    return parsed
