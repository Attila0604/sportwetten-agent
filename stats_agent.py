"""
stats_agent.py
──────────────
Holt Statistiken von API-Football für bessere Value Bet Analyse.
- Letzte 5 Spiele (Form)
- Heim/Auswärts Statistiken  
- Head-to-Head Historie
"""

import httpx
import asyncio
import os

API_FOOTBALL_KEY = os.getenv("API_FOOTBALL_KEY", "")
BASE_URL = "https://v3.football.api-sports.io"

HEADERS = {
    "x-apisports-key": API_FOOTBALL_KEY,
}

# Liga IDs in API-Football
LIGA_IDS = {
    "Soccer Epl":                  39,   # Premier League
    "Soccer Germany Bundesliga":   78,   # Bundesliga
    "Soccer Spain La Liga":         140,  # La Liga
    "Soccer Italy Serie A":        135,  # Serie A
    "Soccer France Ligue One":     61,   # Ligue 1
    "Soccer Uefa Champs League":   2,    # Champions League
    "Soccer Austria Bundesliga":   144,  # Austria Bundesliga
}

SAISON = "2025"


async def hole_team_id(team_name: str, liga_id: int) -> int | None:
    """Sucht die Team ID anhand des Namens"""
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{BASE_URL}/teams",
                headers=HEADERS,
                params={"name": team_name, "league": liga_id, "season": SAISON},
                timeout=10,
            )
            if resp.status_code == 200:
                data = resp.json()
                teams = data.get("response", [])
                if teams:
                    return teams[0]["team"]["id"]
    except Exception as e:
        print(f"  Team ID Fehler [{team_name}]: {e}")
    return None


async def hole_letzte_spiele(team_id: int, anzahl: int = 5) -> list:
    """Holt die letzten N Spiele eines Teams"""
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{BASE_URL}/fixtures",
                headers=HEADERS,
                params={
                    "team":   team_id,
                    "last":   anzahl,
                    "season": SAISON,
                },
                timeout=10,
            )
            if resp.status_code == 200:
                return resp.json().get("response", [])
    except Exception as e:
        print(f"  Letzte Spiele Fehler [{team_id}]: {e}")
    return []


async def hole_head_to_head(team1_id: int, team2_id: int) -> list:
    """Holt die letzten Head-to-Head Spiele"""
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{BASE_URL}/fixtures/headtohead",
                headers=HEADERS,
                params={
                    "h2h":  f"{team1_id}-{team2_id}",
                    "last": 5,
                },
                timeout=10,
            )
            if resp.status_code == 200:
                return resp.json().get("response", [])
    except Exception as e:
        print(f"  H2H Fehler: {e}")
    return []


def berechne_form(spiele: list, team_id: int) -> str:
    """Berechnet die Form aus den letzten Spielen (W/D/L)"""
    form = []
    for spiel in spiele[-5:]:
        fixture = spiel.get("fixture", {})
        teams   = spiel.get("teams", {})
        goals   = spiel.get("goals", {})

        heim_id   = teams.get("home", {}).get("id")
        gast_id   = teams.get("away", {}).get("id")
        heim_tore = goals.get("home", 0) or 0
        gast_tore = goals.get("away", 0) or 0

        if team_id == heim_id:
            if heim_tore > gast_tore:
                form.append("W")
            elif heim_tore == gast_tore:
                form.append("D")
            else:
                form.append("L")
        elif team_id == gast_id:
            if gast_tore > heim_tore:
                form.append("W")
            elif gast_tore == heim_tore:
                form.append("D")
            else:
                form.append("L")

    return "".join(form) if form else "N/A"


def berechne_tore_schnitt(spiele: list, team_id: int) -> dict:
    """Berechnet Tore pro Spiel Durchschnitt"""
    geschossen = []
    kassiert   = []

    for spiel in spiele:
        teams     = spiel.get("teams", {})
        goals     = spiel.get("goals", {})
        heim_id   = teams.get("home", {}).get("id")
        heim_tore = goals.get("home", 0) or 0
        gast_tore = goals.get("away", 0) or 0

        if team_id == heim_id:
            geschossen.append(heim_tore)
            kassiert.append(gast_tore)
        else:
            geschossen.append(gast_tore)
            kassiert.append(heim_tore)

    return {
        "geschossen": round(sum(geschossen) / len(geschossen), 2) if geschossen else 0,
        "kassiert":   round(sum(kassiert) / len(kassiert), 2) if kassiert else 0,
    }


async def hole_statistiken_fuer_spiel(
    heim: str, gast: str, liga: str
) -> dict:
    """
    Holt alle relevanten Statistiken für ein Spiel.
    Gibt ein dict zurück das direkt in den KI-Prompt eingefügt wird.
    """
    liga_id = LIGA_IDS.get(liga)
    if not liga_id:
        return {}

    try:
        # Team IDs holen (parallel)
        heim_id, gast_id = await asyncio.gather(
            hole_team_id(heim, liga_id),
            hole_team_id(gast, liga_id),
        )

        if not heim_id or not gast_id:
            return {}

        # Daten parallel holen
        heim_spiele, gast_spiele, h2h = await asyncio.gather(
            hole_letzte_spiele(heim_id),
            hole_letzte_spiele(gast_id),
            hole_head_to_head(heim_id, gast_id),
        )

        await asyncio.sleep(0.5)  # Rate limit

        # Form berechnen
        heim_form = berechne_form(heim_spiele, heim_id)
        gast_form = berechne_form(gast_spiele, gast_id)

        # Tore Durchschnitt
        heim_tore = berechne_tore_schnitt(heim_spiele, heim_id)
        gast_tore = berechne_tore_schnitt(gast_spiele, gast_id)

        # H2H Auswertung
        h2h_heim_siege  = 0
        h2h_unent       = 0
        h2h_gast_siege  = 0
        for spiel in h2h:
            teams     = spiel.get("teams", {})
            goals     = spiel.get("goals", {})
            h_id      = teams.get("home", {}).get("id")
            heim_tore_h2h = goals.get("home", 0) or 0
            gast_tore_h2h = goals.get("away", 0) or 0
            if h_id == heim_id:
                if heim_tore_h2h > gast_tore_h2h:
                    h2h_heim_siege += 1
                elif heim_tore_h2h == gast_tore_h2h:
                    h2h_unent += 1
                else:
                    h2h_gast_siege += 1
            else:
                if gast_tore_h2h > heim_tore_h2h:
                    h2h_heim_siege += 1
                elif gast_tore_h2h == heim_tore_h2h:
                    h2h_unent += 1
                else:
                    h2h_gast_siege += 1

        return {
            "heim_form":        heim_form,
            "gast_form":        gast_form,
            "heim_tore_schnitt": heim_tore,
            "gast_tore_schnitt": gast_tore,
            "h2h": {
                "heim_siege":  h2h_heim_siege,
                "unentschieden": h2h_unent,
                "gast_siege":  h2h_gast_siege,
                "spiele":      len(h2h),
            },
        }

    except Exception as e:
        print(f"  Stats Fehler [{heim} vs {gast}]: {e}")
        return {}
