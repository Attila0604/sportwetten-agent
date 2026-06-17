"""
predict.py
──────────
Liest die Spielhistorie aus Supabase, trainiert das Poisson-Modell
und gibt eine Wahrscheinlichkeits-Prognose für ein Spiel zurück.

Optional: Buchmacher-Quoten mitgeben -> zeigt den Edge (Weg-B-Kern).
"""

import os
import httpx
from poisson_model import fit_team_ratings, predict_match, finde_edge

SUPABASE_URL = os.getenv("SUPABASE_URL", "").rstrip("/")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")


async def _lade_liga_matches(client: httpx.AsyncClient, league: str) -> list:
    """Holt alle Spiele einer Liga aus Supabase (eine Liga < 1000 Zeilen)."""
    url = f"{SUPABASE_URL}/rest/v1/matches"
    params = {
        "select": "match_date,home,away,home_goals,away_goals",
        "league": f"eq.{league}",
        "limit": "5000",
    }
    headers = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"}
    r = await client.get(url, params=params, headers=headers, timeout=30)
    r.raise_for_status()
    return r.json()


async def prognose(home: str, away: str, league: str = "PL",
                   quote_heim: float = None,
                   quote_remis: float = None,
                   quote_gast: float = None) -> dict:
    """
    Prognose für home vs away in einer Liga.
    Quoten sind optional -> wenn gesetzt, wird der Edge berechnet.
    """
    if not (SUPABASE_URL and SUPABASE_KEY):
        return {"ok": False, "error": "SUPABASE_URL / SUPABASE_KEY fehlen"}

    async with httpx.AsyncClient() as client:
        matches = await _lade_liga_matches(client, league)

    if not matches:
        return {"ok": False, "error": f"Keine Spiele für Liga '{league}' gefunden"}

    ratings = fit_team_ratings(matches)
    p = predict_match(ratings, home, away)

    # Warnung, falls ein Team nicht in den Trainingsdaten ist
    unbekannt = [t for t in (home, away) if t not in ratings["teams"]]

    ergebnis = {
        "ok": True,
        "liga": league,
        "spiele_trainiert": len(matches),
        "heim": home,
        "gast": away,
        "wahrscheinlichkeit": {
            "heimsieg":      f"{p['p_heim']*100:.1f}%",
            "unentschieden": f"{p['p_remis']*100:.1f}%",
            "auswaertssieg": f"{p['p_gast']*100:.1f}%",
        },
        "erwartete_tore": f"{p['erwartete_tore_heim']} : {p['erwartete_tore_gast']}",
    }
    if unbekannt:
        ergebnis["warnung"] = f"Unbekannte Teams (Liga-Schnitt genutzt): {unbekannt}"

    # Edge-Check, falls Quoten mitgegeben
    edges = {}
    if quote_heim: edges["heimsieg"]      = f"{finde_edge(p['p_heim'],  quote_heim)*100:+.1f}%"
    if quote_remis: edges["unentschieden"] = f"{finde_edge(p['p_remis'], quote_remis)*100:+.1f}%"
    if quote_gast: edges["auswaertssieg"] = f"{finde_edge(p['p_gast'],  quote_gast)*100:+.1f}%"
    if edges:
        ergebnis["edge"] = edges
        ergebnis["hinweis_edge"] = "Positiver Edge = Modell hält die Wette für wertvoller als der Buchmacher."

    return ergebnis
