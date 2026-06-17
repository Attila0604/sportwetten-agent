"""
poisson_model.py  (v2 – verbessert)
───────────────────────────────────
Unabhängiges Wahrscheinlichkeits-Modell für Fußball.

Verbesserungen gegenüber v1:
  - Zeit-Gewichtung: neuere Spiele zählen mehr (half_life_days).
  - Heim-/Auswärts-Split: getrennte Angriffs-/Abwehrstärke pro Venue.
  - Shrinkage: Teams mit wenig Daten -> Richtung Liga-Schnitt (shrink).
  - Dixon-Coles-Korrektur (rho) für knappe Ergebnisse (0:0,1:0,0:1,1:1).

Reines Python (stdlib) -> keine schweren Dependencies, läuft auf Railway.
Schnittstelle wie v1: fit_team_ratings(matches) + predict_match(ratings, h, a).
matches benötigen jetzt zusätzlich "match_date" (ISO "YYYY-MM-DD") für die
Zeit-Gewichtung; fehlt das Datum, wird Gewicht 1 genutzt.
"""

from math import exp, factorial
from datetime import date
from collections import defaultdict

NEUTRAL = {"home_attack": 1.0, "home_defense": 1.0,
           "away_attack": 1.0, "away_defense": 1.0}


def _poisson_pmf(k: int, lam: float) -> float:
    return (lam ** k) * exp(-lam) / factorial(k)


def _tau(i: int, j: int, lam: float, mu: float, rho: float) -> float:
    """Dixon-Coles-Korrektur für niedrige Ergebnisse."""
    if i == 0 and j == 0: return 1 - lam * mu * rho
    if i == 0 and j == 1: return 1 + lam * rho
    if i == 1 and j == 0: return 1 + mu * rho
    if i == 1 and j == 1: return 1 - rho
    return 1.0


def _parse(d):
    try:
        return date.fromisoformat(d[:10])
    except Exception:
        return None


def fit_team_ratings(matches: list, half_life_days: float = 240.0,
                     shrink: float = 6.0, rho: float = -0.05) -> dict:
    if not matches:
        raise ValueError("Keine Spiele zum Trainieren.")

    # Referenzdatum = jüngstes Spiel; Gewicht = 0.5 ^ (Alter / half_life)
    daten = [_parse(m.get("match_date", "")) for m in matches]
    ref = max([d for d in daten if d], default=None)

    def gewicht(d):
        if ref is None or d is None or half_life_days <= 0:
            return 1.0
        alter = (ref - d).days
        return 0.5 ** (alter / half_life_days)

    # Liga-Schnitte (gewichtet)
    w_sum = gf_h = gf_a = 0.0
    for m, d in zip(matches, daten):
        w = gewicht(d)
        w_sum += w
        gf_h += w * m["home_goals"]
        gf_a += w * m["away_goals"]
    league_home = gf_h / w_sum
    league_away = gf_a / w_sum

    # Pro Team: gewichtete Tore je Venue
    H = defaultdict(lambda: {"gf": 0.0, "ga": 0.0, "w": 0.0})  # Heimspiele
    A = defaultdict(lambda: {"gf": 0.0, "ga": 0.0, "w": 0.0})  # Auswärtsspiele
    for m, d in zip(matches, daten):
        w = gewicht(d)
        h, a = m["home"], m["away"]
        H[h]["gf"] += w * m["home_goals"]; H[h]["ga"] += w * m["away_goals"]; H[h]["w"] += w
        A[a]["gf"] += w * m["away_goals"]; A[a]["ga"] += w * m["home_goals"]; A[a]["w"] += w

    def shrunk(raw, w):
        # zieht Rohwert Richtung 1.0, je weniger Daten desto stärker
        return (w * raw + shrink * 1.0) / (w + shrink)

    teams = {}
    for t in set(list(H.keys()) + list(A.keys())):
        h, a = H[t], A[t]
        ha = shrunk((h["gf"] / h["w"]) / league_home, h["w"]) if h["w"] else 1.0
        hd = shrunk((h["ga"] / h["w"]) / league_away, h["w"]) if h["w"] else 1.0
        aa = shrunk((a["gf"] / a["w"]) / league_away, a["w"]) if a["w"] else 1.0
        ad = shrunk((a["ga"] / a["w"]) / league_home, a["w"]) if a["w"] else 1.0
        teams[t] = {"home_attack": round(ha, 3), "home_defense": round(hd, 3),
                    "away_attack": round(aa, 3), "away_defense": round(ad, 3)}

    return {"league_home": round(league_home, 3), "league_away": round(league_away, 3),
            "rho": rho, "teams": teams}


def predict_match(ratings: dict, home: str, away: str, max_tore: int = 10) -> dict:
    t = ratings["teams"]
    h = t.get(home, NEUTRAL)
    a = t.get(away, NEUTRAL)
    rho = ratings.get("rho", -0.05)

    lam = ratings["league_home"] * h["home_attack"] * a["away_defense"]  # Heimtore
    mu  = ratings["league_away"] * a["away_attack"] * h["home_defense"]  # Gasttore

    p_heim = p_remis = p_gast = 0.0
    for i in range(max_tore + 1):
        for j in range(max_tore + 1):
            p = _poisson_pmf(i, lam) * _poisson_pmf(j, mu) * _tau(i, j, lam, mu, rho)
            if i > j:   p_heim  += p
            elif i == j: p_remis += p
            else:       p_gast  += p

    total = p_heim + p_remis + p_gast  # tau -> Renormierung nötig
    return {
        "erwartete_tore_heim": round(lam, 2),
        "erwartete_tore_gast": round(mu, 2),
        "p_heim":  round(p_heim / total, 4),
        "p_remis": round(p_remis / total, 4),
        "p_gast":  round(p_gast / total, 4),
    }


def finde_edge(modell_prob: float, quote: float) -> float:
    return round(modell_prob * quote - 1, 4)
