import os
import json
from datetime import datetime
import anthropic

from value_bet_agent import analysiere_value_bets, top_value_bets

client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

STARTKAPITAL      = float(os.getenv("STARTKAPITAL", "1000"))
MAX_RISIKO_PROZENT = float(os.getenv("MAX_RISIKO_PROZENT", "3"))

SYSTEM_PROMPT = """Du bist ein professioneller Fußballwett-Analyst und Bankroll-Manager.
Analysiere Value Bets und berechne optimale Einsätze nach Kelly-Kriterium.

BANKROLL REGELN:
- Maximales Risiko pro Wette: MAX_RISIKO% des Kapitals
- Halber Kelly: Einsatz = Kapital × 0.5 × ((p×(q-1)-(1-p)) / (q-1))
  p = echte Wahrscheinlichkeit, q = Dezimalquote
- Minimum: 0.50€, Maximum: MAX_RISIKO% des Kapitals
- Runde auf 0.50€ genau
- Nur EV > 5% und Konfidenz >= 6 empfehlen
- Wähle exakt die TOP 3 besten Wetten für morgen

WICHTIG: Dir werden bereits vorberechnete Value Bets geliefert (Konsens-Methode).
Nutze diese als Grundlage – du kannst sie bestätigen, ablehnen oder priorisieren.

Antworte NUR in validem JSON."""


def berechne_kelly(kapital: float, prob: float, quote: float) -> float:
    if quote <= 1 or prob <= 0:
        return 0
    b = quote - 1
    kelly = (prob * b - (1 - prob)) / b
    if kelly <= 0:
        return 0
    einsatz = kapital * kelly * 0.5
    max_e   = kapital * (MAX_RISIKO_PROZENT / 100)
    einsatz = max(0.50, min(einsatz, max_e))
    return round(round(einsatz / 0.5) * 0.5, 2)


async def analysiere_spiele(spiele: list, aktuelles_kapital: float = None) -> dict:
    kapital = aktuelles_kapital or STARTKAPITAL
    max_e   = round(kapital * MAX_RISIKO_PROZENT / 100, 2)
    morgen  = datetime.now().strftime("%d.%m.%Y")

    if not spiele:
        return {"alle_empfehlungen": [], "top3": [], "zusammenfassung": "Keine Spiele verfügbar."}

    # ── Value Bets vorberechnen (Konsens-Methode) ─────────────────────────────
    value_bets     = analysiere_value_bets(spiele)
    top_value      = top_value_bets(value_bets, anzahl=10)
    anzahl_vb      = len(value_bets)

    # Für den Prompt: nur die wichtigsten Felder der Value Bets
    vb_simplified = [
        {
            "heim":            vb["heim"],
            "gast":            vb["gast"],
            "liga":            vb["liga"],
            "zeit":            vb["zeit"],
            "empfehlung":      vb["empfehlung"],
            "quote":           vb["quote"],
            "bookie":          vb["bookie"],
            "konsens_quote":   vb["konsens_quote"],
            "ev":              vb["ev"],
            "impl_wahrsch":    vb["implizite_wahrscheinlichkeit"],
            "buchmacher_anz":  vb["anzahl_buchmacher"],
        }
        for vb in top_value
    ]

    prompt = f"""Analysiere Value Bets für morgen ({morgen}).

KAPITAL: {kapital:.2f}€ | MAX EINSATZ: {max_e:.2f}€ ({MAX_RISIKO_PROZENT}%)

── VORBERECHNETE VALUE BETS (Konsens-Methode, EV≥5%) ──
Gesamt gefunden: {anzahl_vb} Value Bets
Top {len(vb_simplified)} für deine Analyse:
{json.dumps(vb_simplified, ensure_ascii=False, indent=2)}

── ALLE SPIELE (für Kontext) ──
{json.dumps(spiele[:40], ensure_ascii=False)}

AUFGABE:
1. Bewerte die vorberechneten Value Bets
2. Wähle alle guten Value Bets (EV>5%, Konfidenz≥6) als Empfehlungen
3. Wähle die TOP 3 besten für heute

JSON Antwort:
{{
  "alle_empfehlungen": [{{
    "spiel_id":"...","heim":"...","gast":"...","liga":"...","zeit":"...",
    "empfehlung":"Heimsieg|Unentschieden|Gastsieg",
    "quote":2.10,
    "bookie":"bet365",
    "echte_wahrscheinlichkeit":0.55,
    "implizite_wahrscheinlichkeit":0.476,
    "ev":0.155,
    "konfidenz":7,
    "risiko":"Niedrig|Mittel|Hoch",
    "begruendung":"Begründung auf Deutsch"
  }}],
  "top3": [{{
    "spiel_id":"...","heim":"...","gast":"...","liga":"...","zeit":"...",
    "empfehlung":"Heimsieg",
    "quote":2.10,
    "bookie":"bet365",
    "echte_wahrscheinlichkeit":0.55,
    "implizite_wahrscheinlichkeit":0.476,
    "ev":0.155,
    "konfidenz":7,
    "risiko":"Niedrig",
    "begruendung":"...",
    "empfohlener_einsatz":18.50,
    "einsatz_begruendung":"Warum dieser Einsatz"
  }}],
  "zusammenfassung":"2-3 Sätze auf Deutsch",
  "value_bets_gesamt": {anzahl_vb}
}}"""

    try:
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=3000,
            system=SYSTEM_PROMPT.replace("MAX_RISIKO%", f"{MAX_RISIKO_PROZENT}%"),
            messages=[{"role": "user", "content": prompt}],
        )
        text = msg.content[0].text.strip()
        if "```" in text:
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]

        result = json.loads(text.strip())

        for emp in result.get("top3", []):
            kelly  = berechne_kelly(kapital, emp.get("echte_wahrscheinlichkeit", 0), emp.get("quote", 0))
            ki_e   = emp.get("empfohlener_einsatz", kelly)
            emp["empfohlener_einsatz"] = round(min(float(ki_e), max_e), 2)
            emp["kelly_einsatz"]       = kelly
            emp["max_einsatz"]         = max_e
            emp["potenz_gewinn"]       = round(
                emp["empfohlener_einsatz"] * emp.get("quote", 1) - emp["empfohlener_einsatz"], 2
            )

        # Value Bet Rohdaten für Transparenz mitspeichern
        result["value_bets_roh"] = top_value

        return result

    except Exception as e:
        print(f"Analyse-Fehler: {e}")
        return {
            "alle_empfehlungen": [],
            "top3": [],
            "zusammenfassung": f"Fehler: {e}",
            "value_bets_roh": value_bets,
        }


async def generiere_wochen_analyse(wetten: list) -> str:
    if not wetten:
        return "Keine Wetten diese Woche."
    try:
        gew  = sum(1 for w in wetten if w.get("status") == "Gewonnen")
        verl = sum(1 for w in wetten if w.get("status") == "Verloren")
        gv   = sum(w.get("gewinn_verlust", 0) for w in wetten)
        prompt = f"""Wöchentliche Wettanalyse auf Deutsch (max 300 Wörter):

Wetten: {len(wetten)} | Gewonnen: {gew} | Verloren: {verl} | G/V: {gv:.2f}€

Details: {json.dumps(wetten, ensure_ascii=False)}

Analysiere: Performance, was lief gut/schlecht, Liga-Analyse, Empfehlungen nächste Woche."""
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001", max_tokens=600,
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
        prompt = f"""Monatliche Wettanalyse auf Deutsch (max 500 Wörter):

Monat: {len(wetten)} Wetten | {gew} Gewonnen | G/V: {gv:.2f}€
Kapital: {kapital_start:.2f}€ → {kapital_ende:.2f}€ | ROI: {gv/kapital_start*100:.2f}%

Details: {json.dumps(wetten, ensure_ascii=False)}

Analysiere: Gesamtperformance, Liga-Analyse, Bankroll-Entwicklung, Strategie-Empfehlungen."""
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001", max_tokens=1000,
            messages=[{"role": "user", "content": prompt}]
        )
        return msg.content[0].text.strip()
    except Exception as e:
        return f"Fehler: {e}"
