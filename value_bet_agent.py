"""
value_bet_agent.py  (v2 – bugfix + tighter filters)
──────────────────────────────────────────────────────
Erkennt Value Bets durch Konsens-Vergleich aller Buchmacher.

Änderungen vs. alter Version:
  1. MEDIAN statt Mittelwert als Konsens (robust gegen Ausreißer-Bookies)
  2. Outlier-Filter: beste_quote darf max. MAX_EDGE über Konsens liegen
     → verhindert EV-Werte wie 2084% durch fehlerhafte Bookie-Daten
  3. Strikteres MIN_QUOTE und MAX_QUOTE (datengetrieben)
  4. Unentschieden-Wetten optional ausschließbar
  5. Sanity-Check auf Konsens-Quote (muss >= 1.01 sein)
  6. Debug-Logging für verworfene Kandidaten
  7. MAX_EV Cap als Bug-Guard

Logik:
  1. Konsens-Quote = Median aller Buchmacher (nicht Durchschnitt!)
  2. Outlier-Check: best_quote / konsens_quote <= 1 + MAX_EDGE
  3. EV = beste_quote / konsens_quote - 1
  4. Wenn MIN_EV <= EV <= MAX_EV UND MIN_QUOTE <= Quote <= MAX_QUOTE → Value Bet
"""

import os
import logging
from statistics import median

log = logging.getLogger(__name__)

# ─── Konfiguration ────────────────────────────────────────────────────────────
# Datengetrieben aus 32 abgeschlossenen Wetten (ROI-Analyse)

MIN_EV       = float(os.getenv("MIN_EV_PROZENT", "0.03"))   # 3% (niedriger EV performt besser als hoher!)
MAX_EV       = float(os.getenv("MAX_EV_PROZENT", "0.25"))   # 25% Cap – alles drüber = Bug-Indikator
MIN_QUOTE    = float(os.getenv("MIN_QUOTE",      "1.70"))   # Quoten <1.7 haben 20% Hit-Rate bei 62% nötig
MAX_QUOTE    = float(os.getenv("MAX_QUOTE",      "2.20"))   # Quoten >2.5 haben -60% ROI
MAX_EDGE     = float(os.getenv("MAX_EDGE",       "0.15"))   # beste_quote max. 15% über Konsens (sonst Bug)
MIN_BOOKIE   = int(  os.getenv("MIN_BUCHMACHER", "5"))      # vorher 3 – 5 macht Konsens stabiler
ALLOW_DRAW   = os.getenv("ALLOW_DRAW", "false").lower() == "true"  # Draws sind Gift in den Daten

ERLAUBTE_LIGEN = [
    "Soccer Fifa World Cup",
    "Soccer Epl",
    "Soccer Germany Bundesliga",
    "Soccer Spain La Liga",
    "Soccer Italy Serie A",
    "Soccer France Ligue One",
    "Soccer Uefa Champs League",
    "Soccer Austria Bundesliga",
]


# ─── Hilfsfunktionen ──────────────────────────────────────────────────────────

def _median_quote(quoten: list) -> float:
    """
    Median aller gültigen Quoten (> 1.01) aus den Buchmachern.
    Robust gegen Ausreißer: 1 verrückter Bookie kippt das Ergebnis nicht.
    """
    gueltig = [q for q in quoten if isinstance(q, (int, float)) and q > 1.01]
    if len(gueltig) < MIN_BOOKIE:
        return 0.0
    return round(median(gueltig), 4)


def _extract_quoten(spiel: dict, markt: str) -> list:
    """
    Holt alle einzelnen Bookie-Quoten für einen Markt (h/d/a) aus alle_buchmacher.
    Fallback: wenn nicht verfügbar, leere Liste.
    """
    key_map = {"heim": "heim", "unentschieden": "draw", "gast": "gast"}
    json_key = key_map.get(markt, markt)
    alle = spiel.get("alle_buchmacher", [])
    if not isinstance(alle, list):
        return []
    return [b.get(json_key) for b in alle if isinstance(b, dict)]


def berechne_ev(konsens_quote: float, beste_quote: float) -> float:
    """EV = beste/konsens - 1. Gibt 0.0 zurück, wenn einer der Werte ungültig."""
    if konsens_quote < 1.01 or beste_quote < 1.01:
        return 0.0
    return round(beste_quote / konsens_quote - 1, 4)


def _ist_outlier(beste_quote: float, konsens_quote: float) -> bool:
    """
    True, wenn beste_quote verdächtig weit über dem Konsens liegt.
    Schützt vor Buchmacher-Datenfehlern (z.B. Quote 150 statt 1.50).
    """
    if konsens_quote < 1.01:
        return True
    edge = beste_quote / konsens_quote - 1
    return edge > MAX_EDGE


# ─── Haupt-Logik ──────────────────────────────────────────────────────────────

def analysiere_value_bets(spiele: list) -> list:
    value_bets = []
    verworfen = {"bookies": 0, "liga": 0, "konsens": 0, "outlier": 0,
                 "ev_low": 0, "ev_high": 0, "quote_low": 0, "quote_high": 0, "draw": 0}

    for spiel in spiele:
        if not isinstance(spiel, dict):
            continue
        if spiel.get("anzahl_buchmacher", 0) < MIN_BOOKIE:
            verworfen["bookies"] += 1
            continue

        liga = spiel.get("liga", "")
        if liga not in ERLAUBTE_LIGEN:
            verworfen["liga"] += 1
            continue

        kandidaten = [
            {
                "ergebnis":    "Heimsieg",
                "markt":       "heim",
                "beste_quote": spiel.get("beste_quote_heim", 0),
                "bookie":      spiel.get("beste_quote_heim_bookie", ""),
            },
            {
                "ergebnis":    "Unentschieden",
                "markt":       "unentschieden",
                "beste_quote": spiel.get("beste_quote_unentschieden", 0),
                "bookie":      spiel.get("beste_quote_unent_bookie", ""),
            },
            {
                "ergebnis":    "Gastsieg",
                "markt":       "gast",
                "beste_quote": spiel.get("beste_quote_gast", 0),
                "bookie":      spiel.get("beste_quote_gast_bookie", ""),
            },
        ]

        for k in kandidaten:
            # Draw-Filter
            if not ALLOW_DRAW and k["ergebnis"] == "Unentschieden":
                verworfen["draw"] += 1
                continue

            # Konsens robust bilden (Median statt Mittelwert)
            einzelquoten = _extract_quoten(spiel, k["markt"])
            konsens = _median_quote(einzelquoten)

            # Fallback: altes Feld, falls alle_buchmacher nicht verfügbar
            if konsens == 0.0:
                legacy_map = {"heim": "quote_heim",
                              "unentschieden": "quote_unentschieden",
                              "gast": "quote_gast"}
                konsens = spiel.get(legacy_map[k["markt"]], 0) or 0.0

            # Sanity-Check: Konsens muss plausible Quote sein
            if konsens < 1.01:
                verworfen["konsens"] += 1
                log.debug("Verworfen – ungültige Konsens-Quote %.3f bei %s vs %s (%s)",
                          konsens, spiel.get("heim"), spiel.get("gast"), k["ergebnis"])
                continue

            beste = k["beste_quote"]
            if beste < 1.01:
                verworfen["konsens"] += 1
                continue

            # Outlier-Check: beste_quote darf nicht absurd weit über Konsens liegen
            if _ist_outlier(beste, konsens):
                verworfen["outlier"] += 1
                log.warning("Outlier verworfen: %s vs %s (%s) – beste=%.2f, konsens=%.2f, edge=%.1f%%",
                            spiel.get("heim"), spiel.get("gast"), k["ergebnis"],
                            beste, konsens, (beste/konsens - 1)*100)
                continue

            # Quoten-Filter (datengetrieben)
            if beste < MIN_QUOTE:
                verworfen["quote_low"] += 1
                continue
            if beste > MAX_QUOTE:
                verworfen["quote_high"] += 1
                continue

            # EV berechnen und filtern
            ev = berechne_ev(konsens, beste)
            if ev < MIN_EV:
                verworfen["ev_low"] += 1
                continue
            if ev > MAX_EV:
                # Bug-Guard: EV über 25% ist fast immer Daten-Noise
                verworfen["ev_high"] += 1
                log.warning("EV-Cap überschritten: %s vs %s (%s) – ev=%.1f%%, beste=%.2f, konsens=%.2f",
                            spiel.get("heim"), spiel.get("gast"), k["ergebnis"],
                            ev*100, beste, konsens)
                continue

            impl_wahrsch = round(1 / konsens, 4)

            value_bets.append({
                "spiel_id":                    spiel.get("id"),
                "heim":                        spiel.get("heim"),
                "gast":                        spiel.get("gast"),
                "liga":                        liga,
                "zeit":                        spiel.get("zeit"),
                "empfehlung":                  k["ergebnis"],
                "quote":                       beste,
                "bookie":                      k["bookie"],
                "konsens_quote":               konsens,
                "ev":                          ev,
                "implizite_wahrscheinlichkeit": impl_wahrsch,
                "anzahl_buchmacher":           spiel.get("anzahl_buchmacher"),
                "alle_quoten":                 spiel.get("alle_buchmacher", []),
            })

    # Sortierung: nicht nur nach EV, sondern nach ERWARTUNGSWERT × EV
    # (ein EV von 5% bei Quote 1.9 ist wertvoller als 5% bei Quote 2.2)
    value_bets.sort(key=lambda x: x["ev"] * x["implizite_wahrscheinlichkeit"], reverse=True)

    # Pro Spiel nur den besten Tipp
    gesehen = set()
    unique_bets = []
    for vb in value_bets:
        spiel_id = vb.get("spiel_id") or f"{vb['heim']}_{vb['gast']}"
        if spiel_id not in gesehen:
            gesehen.add(spiel_id)
            unique_bets.append(vb)

    print(f"  → {len(unique_bets)} Value Bets (EV {MIN_EV*100:.0f}–{MAX_EV*100:.0f}%, Quote {MIN_QUOTE}–{MAX_QUOTE})")
    print(f"     Verworfen: {verworfen}")
    return unique_bets


def top_value_bets(value_bets: list, anzahl: int = 3) -> list:
    return value_bets[:anzahl]


def format_value_bet_summary(value_bets: list) -> str:
    if not value_bets:
        return (f"Heute keine Value Bets "
                f"(EV {MIN_EV*100:.0f}–{MAX_EV*100:.0f}%, Quote {MIN_QUOTE}–{MAX_QUOTE}).")
    lines = [f"⚡ {len(value_bets)} VALUE BETS GEFUNDEN\n"]
    for i, vb in enumerate(value_bets, 1):
        lines.append(
            f"{i}. {vb['heim']} vs {vb['gast']}\n"
            f"   → {vb['empfehlung']} | Quote: {vb['quote']} ({vb['bookie']})\n"
            f"   → EV: +{vb['ev']*100:.1f}% | Konsens: {vb['konsens_quote']} | {vb['liga']}\n"
        )
    return "\n".join(lines)
