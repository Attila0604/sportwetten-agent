"""
backtest.py
───────────
Ehrlicher Out-of-Sample-Test des Poisson-Modells:
  - Trainiert NUR auf den älteren Saisons.
  - Sagt die Test-Saison vorher (die das Modell nie gesehen hat).
  - Vergleicht mit den echten Ergebnissen.
  - Misst gegen eine naive Vergleichsbasis (Basisraten der Trainingsdaten).

Metriken:
  - Trefferquote: wie oft war der wahrscheinlichste Tipp richtig.
  - Brier-Score: Qualität der Wahrscheinlichkeiten (0 = perfekt, niedriger = besser).
  - Log-Loss: bestraft selbstsichere Fehlprognosen (niedriger = besser).
"""

import os
from math import log
import httpx
from poisson_model import fit_team_ratings, predict_match

SUPABASE_URL = os.getenv("SUPABASE_URL", "").rstrip("/")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")


def _outcome(hg: int, ag: int) -> str:
    return "heim" if hg > ag else ("remis" if hg == ag else "gast")


async def _lade_matches(client, league):
    url = f"{SUPABASE_URL}/rest/v1/matches"
    params = {"select": "season,home,away,home_goals,away_goals",
              "league": f"eq.{league}", "limit": "10000"}
    headers = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"}
    r = await client.get(url, params=params, headers=headers, timeout=60)
    r.raise_for_status()
    return r.json()


def _metriken(vorhersagen: list) -> dict:
    """vorhersagen: Liste von (p_dict, actual_outcome)."""
    n = len(vorhersagen)
    treffer = 0
    brier_sum = 0.0
    logloss_sum = 0.0
    for p, actual in vorhersagen:
        # Trefferquote
        tipp = max(("heim", "remis", "gast"), key=lambda k: p[k])
        if tipp == actual:
            treffer += 1
        # Brier (3 Klassen)
        for k in ("heim", "remis", "gast"):
            ist = 1.0 if k == actual else 0.0
            brier_sum += (p[k] - ist) ** 2
        # Log-Loss (mit Clamp gegen log(0))
        p_actual = max(p[actual], 1e-9)
        logloss_sum += -log(p_actual)
    return {
        "trefferquote": round(treffer / n * 100, 1),
        "brier":        round(brier_sum / n, 4),
        "logloss":      round(logloss_sum / n, 4),
    }


async def backtest(league: str = "PL", test_season: str = "2025") -> dict:
    if not (SUPABASE_URL and SUPABASE_KEY):
        return {"ok": False, "error": "SUPABASE_URL / SUPABASE_KEY fehlen"}

    async with httpx.AsyncClient() as client:
        alle = await _lade_matches(client, league)

    train = [m for m in alle if m["season"] != test_season]
    test  = [m for m in alle if m["season"] == test_season]
    if not train or not test:
        return {"ok": False, "error": f"Zu wenig Daten (train={len(train)}, test={len(test)})"}

    # Modell trainieren
    ratings = fit_team_ratings(train)

    # Basisraten aus Training (naive Vergleichsbasis)
    bh = sum(1 for m in train if _outcome(m["home_goals"], m["away_goals"]) == "heim") / len(train)
    br = sum(1 for m in train if _outcome(m["home_goals"], m["away_goals"]) == "remis") / len(train)
    bg = sum(1 for m in train if _outcome(m["home_goals"], m["away_goals"]) == "gast") / len(train)
    basis_p = {"heim": bh, "remis": br, "gast": bg}

    modell_vorhersagen = []
    basis_vorhersagen  = []
    for m in test:
        actual = _outcome(m["home_goals"], m["away_goals"])
        p = predict_match(ratings, m["home"], m["away"])
        modell_vorhersagen.append(
            ({"heim": p["p_heim"], "remis": p["p_remis"], "gast": p["p_gast"]}, actual)
        )
        basis_vorhersagen.append((basis_p, actual))

    modell = _metriken(modell_vorhersagen)
    basis  = _metriken(basis_vorhersagen)

    return {
        "ok": True,
        "liga": league,
        "trainiert_auf": f"{len(train)} Spiele (ohne Saison {test_season})",
        "getestet_auf":  f"{len(test)} Spiele (Saison {test_season})",
        "modell":   modell,
        "basis":    basis,
        "urteil": {
            "trefferquote": "Modell besser" if modell["trefferquote"] > basis["trefferquote"] else "Basis besser/gleich",
            "brier":        "Modell besser" if modell["brier"]  < basis["brier"]  else "Basis besser/gleich",
            "logloss":      "Modell besser" if modell["logloss"] < basis["logloss"] else "Basis besser/gleich",
        },
        "hinweis": "Niedriger Brier/Log-Loss = besser. Schlägt das Modell die Basis in allen drei, ist das ein gutes Zeichen.",
    }
