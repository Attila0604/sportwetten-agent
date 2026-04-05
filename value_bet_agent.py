"""
value_bet_agent.py
──────────────────
Erkennt Value Bets durch Konsens-Vergleich aller Buchmacher.

Logik:
  1. Konsens-Quote = Durchschnitt aller Buchmacher
  2. Beste verfügbare Quote vergleichen
  3. EV = beste_quote / konsens_quote - 1
  4. Wenn EV >= MIN_EV UND Quote <= MAX_QUOTE → Value Bet!
"""

import os

MIN_EV      = float(os.getenv("MIN_EV_PROZENT", "0.08"))   # Mindest-EV (0.08 = 8%)
MAX_QUOTE   = float(os.getenv("MAX_QUOTE", "3.50"))         # Maximale Quote
MIN_BOOKIE  = int(os.getenv("MIN_BUCHMACHER", "3"))         # Mindest-Buchmacher


def berechne_ev(konsens_quote: float, beste_quote: float) -> float:
    """
    EV = beste_quote / konsens_quote - 1
    Beispiel: Konsens 2.00, Beste 2.20 → EV = 0.10 (= 10%)
    """
    if konsens_quote <= 1 or beste_quote <= 1:
        return 0.0
    return round(beste_quote / konsens_quote - 1, 4)


def analysiere_value_bets(spiele: list) -> list:
    """
    Gibt nur Value Bets zurück die:
    - EV >= MIN_EV (Standard: 8%)
    - Quote <= MAX_QUOTE (Standard: 3.50)
    - Mindestens MIN_BOOKIE Buchmacher (Standard: 3)
    """
    value_bets = []

    for spiel in spiele:
        if spiel.get("anzahl_buchmacher", 0) < MIN_BOOKIE:
            continue

        kandidaten = [
            {
                "ergebnis":     "Heimsieg",
                "konsens_quote": spiel.get("quote_heim", 0),
                "beste_quote":   spiel.get("beste_quote_heim", 0),
                "bookie":        spiel.get("beste_quote_heim_bookie", ""),
            },
            {
                "ergebnis":     "Unentschieden",
                "konsens_quote": spiel.get("quote_unentschieden", 0),
                "beste_quote":   spiel.get("beste_quote_unentschieden", 0),
                "bookie":        spiel.get("beste_quote_unent_bookie", ""),
            },
            {
                "ergebnis":     "Gastsieg",
                "konsens_quote": spiel.get("quote_gast", 0),
                "beste_quote":   spiel.get("beste_quote_gast", 0),
                "bookie":        spiel.get("beste_quote_gast_bookie", ""),
            },
        ]

        for k in kandidaten:
            ev = berechne_ev(k["konsens_quote"], k["beste_quote"])

            # ── Filter ────────────────────────────────────────────────────────
            if ev < MIN_EV:
                continue  # EV zu niedrig
            if k["beste_quote"] > MAX_QUOTE:
                continue  # Quote zu hoch → zu riskant
            if k["beste_quote"] <= 1:
                continue  # Ungültige Quote
            # ──────────────────────────────────────────────────────────────────

            impl_wahrsch = round(1 / k["konsens_quote"], 4) if k["konsens_quote"] > 1 else 0

            value_bets.append({
                "spiel_id":                 spiel.get("id"),
                "heim":                     spiel.get("heim"),
                "gast":                     spiel.get("gast"),
                "liga":                     spiel.get("liga"),
                "zeit":                     spiel.get("zeit"),
                "empfehlung":               k["ergebnis"],
                "quote":                    k["beste_quote"],
                "bookie":                   k["bookie"],
                "konsens_quote":            k["konsens_quote"],
                "ev":                       ev,
                "implizite_wahrscheinlichkeit": impl_wahrsch,
                "anzahl_buchmacher":        spiel.get("anzahl_buchmacher"),
                "alle_quoten":              spiel.get("alle_buchmacher", []),
            })

    # Sortiert nach EV (beste zuerst)
    value_bets.sort(key=lambda x: x["ev"], reverse=True)

    print(f"  → {len(value_bets)} Value Bets (EV≥{MIN_EV*100:.0f}%, Quote≤{MAX_QUOTE})")
    return value_bets


def top_value_bets(value_bets: list, anzahl: int = 3) -> list:
    """Gibt die besten N Value Bets zurück"""
    return value_bets[:anzahl]


def format_value_bet_summary(value_bets: list) -> str:
    """Formatiert Value Bets als übersichtlichen Text"""
    if not value_bets:
        return f"Heute keine Value Bets (EV<{MIN_EV*100:.0f}% oder Quote>{MAX_QUOTE})."

    lines = [f"⚡ {len(value_bets)} VALUE BETS GEFUNDEN\n"]
    for i, vb in enumerate(value_bets, 1):
        lines.append(
            f"{i}. {vb['heim']} vs {vb['gast']}\n"
            f"   → {vb['empfehlung']} | Quote: {vb['quote']} ({vb['bookie']})\n"
            f"   → EV: +{vb['ev']*100:.1f}% | {vb['liga']}\n"
        )
    return "\n".join(lines)
