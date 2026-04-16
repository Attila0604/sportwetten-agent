"""
analysis_agent.py  (v2 – robust staking + constrained LLM)
────────────────────────────────────────────────────────────
Analysiert Value Bets und wählt Top 3 Wetten mit Kelly-Staking.

Änderungen vs. v1:
  1. Kelly basiert auf MARKT-Wahrscheinlichkeit, nicht auf LLM-Schätzung
     → verhindert Phantom-Einsätze durch LLM-Halluzinationen
  2. Quarter-Kelly (0.25) statt Half-Kelly (0.5) – konfigurierbar
     → robuster bei unsicheren Wahrscheinlichkeiten
  3. Prompt enthält harte Regeln (keine Draws, Quoten-Range, EV-Cap)
  4. Sonnet statt Haiku als Default – bessere Urteile bei Geldentscheidungen
  5. Stats-Ausfall wird explizit im Prompt markiert
  6. LLM-Output wird gegen Business-Regeln validiert (Draws werden raus-gefiltert)
  7. konfidenz >= MIN_KONFIDENZ als zusätzlicher Filter
"""

import os
import json
import logging
from datetime import datetime
import anthropic

from value_bet_agent import analysiere_value_bets, top_value_bets
from stats_agent import hole_statistiken_fuer_spiel

log = logging.getLogger(__name__)

client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

# ─── Konfiguration ────────────────────────────────────────────────────────────
STARTKAPITAL        = float(os.getenv("STARTKAPITAL",        "1000"))
MAX_RISIKO_PROZENT  = float(os.getenv("MAX_RISIKO_PROZENT",  "3"))
KELLY_FRAKTION      = float(os.getenv("KELLY_FRAKTION",      "0.25"))  # Quarter-Kelly
MIN_KONFIDENZ       = int(  os.getenv("MIN_KONFIDENZ",       "6"))     # 1-10 Skala
ALLOW_DRAW          = os.getenv("ALLOW_DRAW", "false").lower() == "true"
ANALYSIS_MODEL      = os.getenv("ANALYSIS_MODEL", "claude-sonnet-4-6")

SYSTEM_PROMPT = """Du bist ein Sportwetten-Analyst. Antworte NUR mit validem JSON.
Kein Markdown, keine Codeblöcke, keine Erklärungen – nur reines JSON.
Halte dich STRIKT an die Regeln im User-Prompt."""


# ─── Kelly-Staking (marktbasiert, nicht LLM-basiert) ─────────────────────────

def berechne_kelly(kapital: float, markt_prob: float, quote: float,
                   ev: float = 0.0) -> float:
    """
    Kelly-Einsatz basierend auf MARKT-Wahrscheinlichkeit und gemessenem Edge.

    markt_prob:  implizite Wahrscheinlichkeit aus dem Konsens (1/konsens_quote)
    quote:       beste verfügbare Quote beim Buchmacher
    ev:          gemessener Edge (best/konsens - 1)

    Logik:
      - Unsere "wahre" Wahrscheinlichkeit = markt_prob * (1 + ev)
        → wir gehen davon aus, dass der Markt-Median im Schnitt richtig liegt,
          und unser Edge der Differenz zur besten verfügbaren Quote entspricht
      - Kelly-Fraktion wird stark reduziert (Quarter-Kelly)
      - Hard cap bei MAX_RISIKO_PROZENT
    """
    if quote <= 1 or markt_prob <= 0 or ev < 0:
        return 0.0

    # "Wahre" Wahrscheinlichkeit = Markt-Konsens (mit unserem gemessenen Edge korrigiert)
    wahre_prob = min(markt_prob * (1 + ev), 0.98)

    b = quote - 1
    kelly = (wahre_prob * b - (1 - wahre_prob)) / b

    if kelly <= 0:
        return 0.0

    # Fraktionales Kelly (robuster bei unsicheren Wahrscheinlichkeiten)
    einsatz = kapital * kelly * KELLY_FRAKTION

    # Hard Cap und Mindest-Einsatz
    max_e = kapital * (MAX_RISIKO_PROZENT / 100)
    einsatz = max(0.50, min(einsatz, max_e))

    # Runden auf 0.50
    return round(round(einsatz / 0.5) * 0.5, 2)


# ─── JSON-Bereinigung ─────────────────────────────────────────────────────────

def bereinige_json(text: str) -> str:
    text = text.strip()
    if "```" in text:
        for part in text.split("```"):
            part = part.strip()
            if part.startswith("json"):
                part = part[4:].strip()
            if part.startswith("{"):
                text = part
                break
    start = text.find("{")
    end   = text.rfind("}")
    if start != -1 and end != -1:
        text = text[start:end+1]
    return text.strip()


# ─── Validierung der LLM-Empfehlungen ─────────────────────────────────────────

def _validiere_empfehlung(emp: dict, original_vb: dict) -> dict | None:
    """
    Prüft, ob eine LLM-Empfehlung den Business-Regeln entspricht.
    Überschreibt kritische Felder mit den Original-Werten (gegen Halluzination).
    Gibt None zurück, wenn die Empfehlung verworfen werden soll.
    """
    if not isinstance(emp, dict):
        return None

    # Keine Draws (falls konfiguriert)
    tipp = emp.get("empfehlung", original_vb.get("empfehlung", ""))
    if not ALLOW_DRAW and tipp == "Unentschieden":
        log.warning("LLM hat Draw empfohlen – verworfen: %s vs %s",
                    original_vb.get("heim"), original_vb.get("gast"))
        return None

    # Konfidenz-Filter
    konfidenz = emp.get("konfidenz", 0)
    try:
        konfidenz = int(konfidenz)
    except (ValueError, TypeError):
        konfidenz = 0
    if konfidenz < MIN_KONFIDENZ:
        log.info("Konfidenz zu niedrig (%d < %d) – verworfen: %s vs %s",
                 konfidenz, MIN_KONFIDENZ, original_vb.get("heim"), original_vb.get("gast"))
        return None

    # Überschreibe kritische Felder mit Original-Werten (LLM darf diese nicht ändern)
    emp["empfehlung"] = original_vb["empfehlung"]
    emp["quote"]      = original_vb["quote"]
    emp["bookie"]     = original_vb["bookie"]
    emp["ev"]         = original_vb["ev"]
    emp["heim"]       = original_vb["heim"]
    emp["gast"]       = original_vb["gast"]
    emp["liga"]       = original_vb["liga"]
    emp["zeit"]       = original_vb["zeit"]

    return emp


# ─── Haupt-Analyse ────────────────────────────────────────────────────────────

async def analysiere_spiele(spiele: list, aktuelles_kapital: float = None) -> dict:
    kapital = aktuelles_kapital or STARTKAPITAL
    max_e   = round(kapital * MAX_RISIKO_PROZENT / 100, 2)
    morgen  = datetime.now().strftime("%d.%m.%Y")

    if not spiele:
        return {"alle_empfehlungen": [], "top3": [], "zusammenfassung": "Keine Spiele verfügbar."}

    value_bets = analysiere_value_bets(spiele)
    top_value  = top_value_bets(value_bets, anzahl=5)
    anzahl_vb  = len(value_bets)

    if not top_value:
        return {
            "alle_empfehlungen": [],
            "top3": [],
            "zusammenfassung": f"Keine Value Bets gefunden (EV-Filter, {anzahl_vb} Kandidaten).",
            "value_bets_gesamt": 0,
            "value_bets_roh": [],
        }

    # Mapping vb_id → original für spätere Validierung
    vb_map = {}

    # ── Statistiken für Top 5 holen ──────────────────────────────────────────
    print("  → Statistiken von API-Football holen...")
    vb_liste = []
    stats_verfuegbar_count = 0

    for vb in top_value:
        vb_id = f"{vb['heim']}_{vb['gast']}"
        vb_map[vb_id] = vb

        stats = {}
        stats_ok = False
        try:
            stats = await hole_statistiken_fuer_spiel(vb["heim"], vb["gast"], vb["liga"])
            if stats:
                stats_ok = True
                stats_verfuegbar_count += 1
        except Exception as e:
            log.warning("Stats Fehler [%s vs %s]: %s", vb["heim"], vb["gast"], e)

        eintrag = {
            "vb_id":       vb_id,
            "heim":        vb["heim"],
            "gast":        vb["gast"],
            "liga":        vb["liga"],
            "zeit":        vb["zeit"],
            "tipp":        vb["empfehlung"],
            "quote":       vb["quote"],
            "bookie":      vb["bookie"],
            "ev_prozent":  round(vb["ev"] * 100, 2),
            "markt_prob":  round(vb.get("implizite_wahrscheinlichkeit", 0), 4),
            "stats_ok":    stats_ok,
        }
        if stats_ok:
            eintrag["statistiken"] = {
                "heim_form":         stats.get("heim_form", "N/A"),
                "gast_form":         stats.get("gast_form", "N/A"),
                "heim_tore_schnitt": stats.get("heim_tore_schnitt", {}),
                "gast_tore_schnitt": stats.get("gast_tore_schnitt", {}),
                "h2h":               stats.get("h2h", {}),
            }
        vb_liste.append(eintrag)

    # ── Prompt mit klaren Regeln ─────────────────────────────────────────────
    draw_regel = "ERLAUBT" if ALLOW_DRAW else "NIEMALS Unentschieden empfehlen"

    prompt = f"""Datum: {morgen}
Kapital: {kapital:.2f}EUR | Max-Einsatz: {max_e:.2f}EUR
Gesamt Value Bets: {anzahl_vb}
Statistiken verfuegbar: {stats_verfuegbar_count}/{len(top_value)}

HARTE REGELN (nicht verhandelbar):
1. {draw_regel}
2. Die Felder 'empfehlung', 'quote', 'bookie', 'ev' darfst du NICHT aendern
3. Konfidenz-Skala 1-10: nur Wetten mit Konfidenz >= {MIN_KONFIDENZ} empfehlen
4. Bei fehlenden Statistiken: Konfidenz max. 6 geben
5. Maximal 3 Empfehlungen (die besten aus den Top 5)

Top 5 Kandidaten:
{json.dumps(vb_liste, ensure_ascii=False, indent=2)}

Analysiere Form der letzten 5 Spiele, H2H Historie, Tore-Schnitt (falls Stats vorhanden).
Waehle die besten 3 (oder weniger, wenn nicht genug Ueberzeugendes dabei).

Antworte NUR mit JSON in diesem Format:
{{
  "top3": [
    {{
      "vb_id": "<exakt aus Eingabe>",
      "empfehlung": "<exakt aus Eingabe>",
      "konfidenz": <1-10>,
      "risiko": "<Niedrig|Mittel|Hoch>",
      "begruendung": "<max 200 Zeichen>"
    }}
  ],
  "zusammenfassung": "<max 150 Zeichen>"
}}"""

    # ── LLM-Call ─────────────────────────────────────────────────────────────
    try:
        msg = client.messages.create(
            model=ANALYSIS_MODEL,
            max_tokens=2000,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )
        text = bereinige_json(msg.content[0].text)
        result = json.loads(text)

        top3_raw = result.get("top3", [])
        top3 = []

        for emp in top3_raw:
            if not isinstance(emp, dict):
                continue
            vb_id = emp.get("vb_id")
            original_vb = vb_map.get(vb_id)
            if not original_vb:
                log.warning("LLM hat unbekannte vb_id zurueckgegeben: %s", vb_id)
                continue

            validated = _validiere_empfehlung(emp, original_vb)
            if validated is None:
                continue

            # Kelly-Einsatz basierend auf MARKT-Daten (nicht LLM-Schätzung!)
            einsatz = berechne_kelly(
                kapital=kapital,
                markt_prob=original_vb.get("implizite_wahrscheinlichkeit", 0),
                quote=original_vb["quote"],
                ev=original_vb["ev"],
            )
            validated["empfohlener_einsatz"]        = einsatz
            validated["kelly_einsatz"]              = einsatz
            validated["max_einsatz"]                = max_e
            validated["implizite_wahrscheinlichkeit"] = original_vb.get("implizite_wahrscheinlichkeit", 0)
            validated["potenz_gewinn"]              = round(einsatz * original_vb["quote"] - einsatz, 2)

            top3.append(validated)

        return {
            "alle_empfehlungen":  top3,
            "top3":               top3,
            "zusammenfassung":    result.get("zusammenfassung", ""),
            "value_bets_gesamt":  anzahl_vb,
            "value_bets_roh":     top_value,
        }

    except Exception as e:
        log.error("Analyse-Fehler: %s", e)
        # Fallback: einfach die Top-EV-Bets mit Markt-basiertem Kelly
        fallback_top3 = []
        for vb in top_value[:3]:
            if not ALLOW_DRAW and vb["empfehlung"] == "Unentschieden":
                continue
            einsatz = berechne_kelly(
                kapital=kapital,
                markt_prob=vb.get("implizite_wahrscheinlichkeit", 0),
                quote=vb["quote"],
                ev=vb["ev"],
            )
            fallback_top3.append({
                **vb,
                "konfidenz":   MIN_KONFIDENZ,
                "risiko":      "Mittel",
                "begruendung": f"Value Bet (Fallback): EV +{vb['ev']*100:.1f}%",
                "empfohlener_einsatz":         einsatz,
                "kelly_einsatz":               einsatz,
                "max_einsatz":                 max_e,
                "echte_wahrscheinlichkeit":    vb.get("implizite_wahrscheinlichkeit", 0),
                "potenz_gewinn":               round(einsatz * vb["quote"] - einsatz, 2),
            })
        return {
            "alle_empfehlungen": fallback_top3,
            "top3":              fallback_top3,
            "zusammenfassung":   f"{anzahl_vb} Value Bets (KI-Fallback, Fehler: {str(e)[:100]})",
            "value_bets_gesamt": anzahl_vb,
            "value_bets_roh":    top_value,
        }


# ─── Wochen- / Monats-Analyse (unverändert, nur Logging statt print) ─────────

async def generiere_wochen_analyse(wetten: list) -> str:
    if not wetten:
        return "Keine Wetten diese Woche."
    try:
        gew  = sum(1 for w in wetten if w.get("status") == "Gewonnen")
        verl = sum(1 for w in wetten if w.get("status") == "Verloren")
        gv   = sum(w.get("gewinn_verlust", 0) for w in wetten)
        prompt = (
            f"Wöchentliche Analyse (Deutsch, max 300 Wörter):\n"
            f"Wetten: {len(wetten)} | Gewonnen: {gew} | Verloren: {verl} | G/V: {gv:.2f}EUR\n"
            f"Details: {json.dumps(wetten, ensure_ascii=False)}"
        )
        msg = client.messages.create(
            model=ANALYSIS_MODEL, max_tokens=600,
            messages=[{"role": "user", "content": prompt}]
        )
        return msg.content[0].text.strip()
    except Exception as e:
        return f"Fehler: {e}"


async def generiere_monats_analyse(wetten: list, kapital_start: float, kapital_ende: float) -> str:
    if not wetten:
        return "Keine Wetten diesen Monat."
    try:
        gew = sum(1 for w in wetten if w.get("status") == "Gewonnen")
        gv  = sum(w.get("gewinn_verlust", 0) for w in wetten)
        roi = gv / kapital_start * 100 if kapital_start > 0 else 0
        prompt = (
            f"Monatliche Analyse (Deutsch, max 500 Wörter):\n"
            f"Wetten: {len(wetten)} | Gewonnen: {gew} | G/V: {gv:.2f}EUR | ROI: {roi:.2f}%\n"
            f"Kapital: {kapital_start:.2f} → {kapital_ende:.2f}EUR\n"
            f"Details: {json.dumps(wetten, ensure_ascii=False)}"
        )
        msg = client.messages.create(
            model=ANALYSIS_MODEL, max_tokens=1000,
            messages=[{"role": "user", "content": prompt}]
        )
        return msg.content[0].text.strip()
    except Exception as e:
        return f"Fehler: {e}"
