"""
poisson_model.py  (v1 – zurückgerollt, bestes Modell im Backtest)
─────────────────────────────────────────────────────────────────
Einfaches, gut kalibriertes Poisson-Modell:
  - Pro Team eine Angriffs- und Abwehrstärke relativ zum Liga-Schnitt.
  - Erwartete Tore -> Poisson -> Heimsieg / Remis / Auswärtssieg.

Hinweis: half_life_days / shrink / rho werden akzeptiert, aber IGNORIERT
(v2-Experiment war im Backtest schlechter). So bleiben predict.py,
backtest.py und main.py unverändert lauffähig.
"""

from math import exp, factorial
from collections import defaultdict


def _poisson_pmf(k: int, lam: float) -> float:
    return (lam ** k) * exp(-lam) / factorial(k)


def fit_team_ratings(matches: list, half_life_days=None, shrink=None,
                     rho=None, **_ignored) -> dict:
    if not matches:
        raise ValueError("Keine Spiele zum Trainieren.")

    tore_heim = sum(m["home_goals"] for m in matches)
    tore_gast = sum(m["away_goals"] for m in matches)
    n = len(matches)
    schnitt_heim = tore_heim / n
    schnitt_gast = tore_gast / n

    erzielt = defaultdict(list)
    kassiert = defaultdict(list)
    for m in matches:
        h, a = m["home"], m["away"]
        erzielt[h].append(m["home_goals"]); kassiert[h].append(m["away_goals"])
        erzielt[a].append(m["away_goals"]); kassiert[a].append(m["home_goals"])

    liga_schnitt_tore = (tore_heim + tore_gast) / (2 * n)
    teams = {}
    for team in erzielt:
        avg_erzielt  = sum(erzielt[team])  / len(erzielt[team])
        avg_kassiert = sum(kassiert[team]) / len(kassiert[team])
        attack  = avg_erzielt  / liga_schnitt_tore if liga_schnitt_tore else 1.0
        defense = avg_kassiert / liga_schnitt_tore if liga_schnitt_tore else 1.0
        teams[team] = {"attack": round(attack, 3), "defense": round(defense, 3)}

    return {"schnitt_heim": round(schnitt_heim, 3),
            "schnitt_gast": round(schnitt_gast, 3),
            "teams": teams}


def predict_match(ratings: dict, home: str, away: str, max_tore: int = 8) -> dict:
    t = ratings["teams"]
    neutral = {"attack": 1.0, "defense": 1.0}
    h = t.get(home, neutral)
    a = t.get(away, neutral)

    lam_heim = ratings["schnitt_heim"] * h["attack"] * a["defense"]
    lam_gast = ratings["schnitt_gast"] * a["attack"] * h["defense"]

    p_heim = p_remis = p_gast = 0.0
    for i in range(max_tore + 1):
        for j in range(max_tore + 1):
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
    return round(modell_prob * quote - 1, 4)
