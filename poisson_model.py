"""
poisson_model.py
────────────────
Unabhängiges Wahrscheinlichkeits-Modell für Fußball (Weg B).

Idee:
  - Aus vergangenen Spielen schätzen wir pro Team eine ANGRIFFS- und
    eine ABWEHR-Stärke (relativ zum Liga-Schnitt).
  - Daraus berechnen wir die erwarteten Tore beider Teams.
  - Mit der Poisson-Verteilung kriegen wir die Wahrscheinlichkeit für
    jedes mögliche Ergebnis -> aufsummiert zu Heimsieg / Remis / Auswärtssieg.

Reines Python (nur stdlib `math`) -> keine schweren Dependencies,
laeuft problemlos auf Railway.
"""

from math import exp, factorial
from collections import defaultdict


def _poisson_pmf(k: int, lam: float) -> float:
    """Wahrscheinlichkeit, dass ein Team genau k Tore schiesst (Erwartung lam)."""
    return (lam ** k) * exp(-lam) / factorial(k)


def fit_team_ratings(matches: list) -> dict:
    """
    Schaetzt Angriffs-/Abwehrstaerken aus der Spielhistorie.

    matches: Liste von dicts mit:
        {"home": str, "away": str, "home_goals": int, "away_goals": int}

    Rueckgabe: dict mit Liga-Schnitten + pro Team {"attack","defense"}.
    """
    if not matches:
        raise ValueError("Keine Spiele zum Trainieren.")

    tore_heim = sum(m["home_goals"] for m in matches)
    tore_gast = sum(m["away_goals"] for m in matches)
    n = len(matches)

    schnitt_heim = tore_heim / n          # Liga-Schnitt Heimtore
    schnitt_gast = tore_gast / n          # Liga-Schnitt Auswaertstore

    # Tore pro Team sammeln
    erzielt = defaultdict(list)           # als Heim ODER Gast erzielt
    kassiert = defaultdict(list)
    heim_spiele = defaultdict(int)
    gast_spiele = defaultdict(int)

    for m in matches:
        h, a = m["home"], m["away"]
        erzielt[h].append(m["home_goals"]); kassiert[h].append(m["away_goals"])
        erzielt[a].append(m["away_goals"]); kassiert[a].append(m["home_goals"])
        heim_spiele[h] += 1; gast_spiele[a] += 1

    teams = {}
    liga_schnitt_tore = (tore_heim + tore_gast) / (2 * n)
    for team in erzielt:
        avg_erzielt  = sum(erzielt[team])  / len(erzielt[team])
        avg_kassiert = sum(kassiert[team]) / len(kassiert[team])
        # Staerke relativ zum Liga-Schnitt (1.0 = exakt Durchschnitt)
        attack  = avg_erzielt  / liga_schnitt_tore if liga_schnitt_tore else 1.0
        defense = avg_kassiert / liga_schnitt_tore if liga_schnitt_tore else 1.0
        teams[team] = {"attack": round(attack, 3), "defense": round(defense, 3)}

    return {
        "schnitt_heim": round(schnitt_heim, 3),
        "schnitt_gast": round(schnitt_gast, 3),
        "teams": teams,
    }


def predict_match(ratings: dict, home: str, away: str, max_tore: int = 8) -> dict:
    """
    Wahrscheinlichkeiten fuer Heimsieg / Remis / Auswaertssieg.
    Faellt auf Liga-Schnitt zurueck, wenn ein Team unbekannt ist.
    """
    t = ratings["teams"]
    neutral = {"attack": 1.0, "defense": 1.0}
    h = t.get(home, neutral)
    a = t.get(away, neutral)

    # Erwartete Tore = Liga-Schnitt * eigener Angriff * gegnerische Abwehr
    lam_heim = ratings["schnitt_heim"] * h["attack"] * a["defense"]
    lam_gast = ratings["schnitt_gast"] * a["attack"] * h["defense"]

    p_heim = p_remis = p_gast = 0.0
    for i in range(max_tore + 1):          # Heimtore
        for j in range(max_tore + 1):      # Gasttore
            p = _poisson_pmf(i, lam_heim) * _poisson_pmf(j, lam_gast)
            if i > j:   p_heim  += p
            elif i == j: p_remis += p
            else:       p_gast  += p

    return {
        "erwartete_tore_heim": round(lam_heim, 2),
        "erwartete_tore_gast": round(lam_gast, 2),
        "p_heim":  round(p_heim, 4),
        "p_remis": round(p_remis, 4),
        "p_gast":  round(p_gast, 4),
    }


def finde_edge(modell_prob: float, quote: float) -> float:
    """
    Edge = (meine Wahrscheinlichkeit * Quote) - 1.
    > 0  -> Modell haelt die Wette fuer wertvoller als der Buchmacher.
    """
    return round(modell_prob * quote - 1, 4)
