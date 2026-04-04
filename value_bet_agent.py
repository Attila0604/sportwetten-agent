"""
value_bet_agent.py
──────────────────
Erkennt Value Bets durch Konsens-Vergleich aller Buchmacher.

Logik:
  1. Konsens-Quote = Durchschnitt aller Buchmacher (bereits in odds_agent berechnet)
  2. Implizite Konsens-Wahrscheinlichkeit = 1 / Konsens-Quote
  3. Beste verfügbare Quote vergleichen
  4. Wenn beste Quote > Konsens × (1 + MIN_EV) → Value Bet!
"""

import os

MIN_EV_PROZENT = float(os.getenv("MIN_EV_PROZENT", "0.05"))   # Mindest-EV in %
MIN_BUCHMACHER = int(os.getenv("MIN_BUCHMACHER", "3"))       # Mindest-Buchmacher für Konsens


def berechne_ev(konsens_quote: float, beste_quote: float) -> float:
    """
    Berechnet den Expected Value in Prozent.

    EV = (beste_quote / konsens_quote - 1) × 100

    Beispiel:
        Konsens: 2.00 → impliziert 50% Wahrscheinlichkeit
        Beste:   2.20 → impliziert 45% Wahrscheinlichkeit
        EV = (2.20 / 2.00 - 1) × 100 = +10% ✅ Value Bet!
    """
    if konsens_quote <= 1 or beste_quote <= 1:
        return 0.0
    return round(beste_quote / konsens_quote - 1, 4)


def analysiere_value_bets(spiele: list) -> list:
    """
    Analysiert alle Spiele und gibt nur echte Value Bets zurück.

    Returns:
        Liste von Value Bets mit EV, empfohlener Quote und Buchmacher
    """
    value_bets = []

    for spiel in spiele:
        anzahl = spiel.get("anzahl_buchmacher", 0)
        if anzahl < MIN_BUCHMACHER:
            continue

        konsens_heim  = spiel.get("quote_heim", 0)
        konsens_unent = spiel.get("quote_unentschieden", 0)
        konsens_gast  = spiel.get("quote_gast", 0)

        beste_heim  = spiel.get("beste_quote_heim", 0)
        beste_unent = spiel.get("beste_quote_unentschieden", 0)
        beste_gast  = spiel.get("beste_quote_gast", 0)

        # EV für jede Wett-Option berechnen
        kandidaten = [
            {
                "ergebnis": "Heimsieg",
                "konsens_quote": konsens_heim,
                "beste_quote": beste_heim,
                "bookie": spiel.get("beste_quote_heim_bookie", ""),
                "ev": berechne_ev(konsens_heim, beste_heim),
            },
            {
                "ergebnis": "Unentschieden",
                "konsens_quote": konsens_unent,
                "beste_quote": beste_unent,
                "bookie": spiel.get("beste_quote_unent_bookie", ""),
                "ev": berechne_ev(konsens_unent, beste_unent),
            },
            {
                "ergebnis": "Gastsieg",
                "konsens_quote": konsens_gast,
                "beste_quote": beste_gast,
                "bookie": spiel.get("beste_quote_gast_bookie", ""),
                "ev": berechne_ev(konsens_gast, beste_gast),
            },
        ]

        # Nur Kandidaten mit EV über Mindestgrenze
        for k in kandidaten:
            if k["ev"] >= MIN_EV_PROZENT and k["beste_quote"] > 1:
                # Implizite Wahrscheinlichkeit aus Konsens
                impl_wahrsch = round(1 / k["konsens_quote"], 4) if k["konsens_quote"] > 1 else 0

                value_bets.append({
                    # Spiel-Info
                    "spiel_id": spiel.get("id"),
                    "heim": spiel.get("heim"),
                    "gast": spiel.get("gast"),
                    "liga": spiel.get("liga"),
                    "zeit": spiel.get("zeit"),

                    # Value Bet Details
                    "empfehlung": k["ergebnis"],
                    "quote": k["beste_quote"],           # Beste verfügbare Quote
                    "bookie": k["bookie"],               # Wo wetten
                    "konsens_quote": k["konsens_quote"], # Markt-Durchschnitt
                    "ev": k["ev"],                       # Expected Value in %
                    "implizite_wahrscheinlichkeit": impl_wahrsch,

                    # Buchmacher-Info
                    "anzahl_buchmacher": anzahl,
                    "alle_quoten": spiel.get("alle_buchmacher", []),
                })

    # Sortiert nach EV (beste zuerst)
    value_bets.sort(key=lambda x: x["ev"], reverse=True)

    print(f"  → {len(value_bets)} Value Bets gefunden (EV ≥ {MIN_EV_PROZENT}%)")
    return value_bets


def top_value_bets(value_bets: list, anzahl: int = 3) -> list:
    """Gibt die besten N Value Bets zurück"""
    return value_bets[:anzahl]


def format_value_bet_summary(value_bets: list) -> str:
    """Formatiert Value Bets als übersichtlichen Text"""
    if not value_bets:
        return "Heute keine Value Bets gefunden (EV < 5%)."

    lines = [f"⚡ {len(value_bets)} VALUE BETS GEFUNDEN\n"]
    for i, vb in enumerate(value_bets, 1):
        lines.append(
            f"{i}. {vb['heim']} vs {vb['gast']}\n"
            f"   → {vb['empfehlung']} | Quote: {vb['quote']} ({vb['bookie']})\n"
            f"   → Konsens: {vb['konsens_quote']} | EV: +{vb['ev']}%\n"
            f"   → {vb['anzahl_buchmacher']} Buchmacher | {vb['liga']}\n"
        )
    return "\n".join(lines)
