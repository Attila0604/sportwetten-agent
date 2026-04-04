import os
import json
from datetime import datetime
import anthropic

from value_bet_agent import analysiere_value_bets, top_value_bets

client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

STARTKAPITAL       = float(os.getenv("STARTKAPITAL", "1000"))
MAX_RISIKO_PROZENT = float(os.getenv("MAX_RISIKO_PROZENT", "3"))

SYSTEM_PROMPT = """Du bist ein Sportwetten-Analyst. Antworte NUR mit validem JSON, ohne Erklärungen davor oder danach.
Kein Markdown, keine Codeblöcke, nur reines JSON."""


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


def bereinige_json(text: str) -> str:
    """Bereinigt die KI-Antwort und extrahiert valides JSON."""
    text = text.strip()
    # Codeblöcke entfernen
    if "```" in text:
        parts = text.split("```")
        for part in parts:
            part = part.strip()
            if part.startswith("json"):
                part = part[4:].strip()
            if part.startswith("{"):
                text = part
                break
    # Ersten { bis letzten } extrahieren
    start = text.find("{")
    end   = text.rfind("}")
    if start != -1 and end != -1:
        text = text[start:end+1]
    return text.strip()


async def analysiere_spiele(spiele: list, aktuelles_kapital: float = None) -> dict:
    kapital = aktuelles_kapital or STARTKAPITAL
    max_e   = round(kapital * MAX_RISIKO_PROZENT / 100, 2)
    morgen  = datetime.now().strftime("%d.%m.%Y")

    if not spiele:
        return {"alle_empfehlungen": [], "top3": [], "zusammenfassung": "Keine Spiele verfügbar."}

    # Value Bets vorberechnen – nur Top 5 an KI senden
    value_bets = analysiere_value_bets(spiele)
    top_value  = top_value_bets(value_bets, anzahl=5)
    anzahl_vb  = len(value_bets)

    # Kompakter Prompt – nur das Nötigste
    vb_liste = [
        {
            "heim":       vb["heim"],
            "gast":       vb["gast"],
            "liga":       vb["liga"],
            "zeit":       vb["zeit"],
            "tipp":       vb["empfehlung"],
            "quote":      vb["quote"],
            "bookie":     vb["bookie"],
            "ev_pct":     vb["ev"],
        }
        for vb in top_value
    ]

    prompt = (
        f"Datum: {morgen} | Kapital: {kapital:.2f}EUR | Max-Einsatz: {max_e:.2f}EUR\n"
        f"Gesamt Value Bets: {anzahl_vb}\n"
        f"Top 5:\n{json.dumps(vb_liste, ensure_ascii=False)}\n\n"
        f"Waehle TOP 3. Antworte NUR mit diesem JSON:\n"
        '{"top3":[{"heim":"","gast":"","liga":"","zeit":"","empfehlung":"",'
        '"quote":0,"bookie":"","ev":0,"konfidenz":0,"risiko":"",'
        '"begruendung":"","empfohlener_einsatz":0,"echte_wahrscheinlichkeit":0,'
        '"implizite_wahrscheinlichkeit":0}],'
        '"alle_empfehlungen":[],'
        '"zusammenfassung":""}'
    )

    try:
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=2000,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )
        text = bereinige_json(msg.content[0].text)
        result = json.loads(text)

        # Falls alle_empfehlungen leer, top5 reinkopieren
        if not result.get("alle_empfehlungen"):
            result["alle_empfehlungen"] = result.get("top3", [])

        for emp in result.get("top3", []):
            kelly = berechne_kelly(kapital, emp.get("echte_wahrscheinlichkeit", 0), emp.get("quote", 0))
            ki_e  = emp.get("empfohlener_einsatz", kelly)
            emp["empfohlener_einsatz"] = round(min(float(ki_e or kelly), max_e), 2)
            emp["kelly_einsatz"]       = kelly
            emp["max_einsatz"]         = max_e
            emp["potenz_gewinn"]       = round(
                emp["empfohlener_einsatz"] * emp.get("quote", 1) - emp["empfohlener_einsatz"], 2
            )

        result["value_bets_gesamt"] = anzahl_vb
        result["value_bets_roh"]    = top_value
        return result

    except Exception as e:
        print(f"Analyse-Fehler: {e}")
        # Fallback: direkt Top 3 aus Value Bets ohne KI
        fallback_top3 = []
        for vb in top_value[:3]:
            einsatz = berechne_kelly(kapital, vb.get("implizite_wahrscheinlichkeit", 0.5), vb["quote"])
            fallback_top3.append({
                **vb,
                "konfidenz":               7,
                "risiko":                  "Mittel",
                "begruendung":             f"Value Bet: EV +{vb['ev']}% (Konsens-Methode)",
                "empfohlener_einsatz":     einsatz,
                "echte_wahrscheinlichkeit": vb.get("implizite_wahrscheinlichkeit", 0),
                "potenz_gewinn":           round(einsatz * vb["quote"] - einsatz, 2),
            })
        return {
            "alle_empfehlungen": fallback_top3,
            "top3":              fallback_top3,
            "zusammenfassung":   f"{anzahl_vb} Value Bets gefunden (KI-Fehler: {e})",
            "value_bets_gesamt": anzahl_vb,
            "value_bets_roh":    top_value,
        }


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
        roi = gv / kapital_start * 100 if kapital_start > 0 else 0
        prompt = (
            f"Monatliche Analyse (Deutsch, max 500 Wörter):\n"
            f"Wetten: {len(wetten)} | Gewonnen: {gew} | G/V: {gv:.2f}EUR | ROI: {roi:.2f}%\n"
            f"Kapital: {kapital_start:.2f} → {kapital_ende:.2f}EUR\n"
            f"Details: {json.dumps(wetten, ensure_ascii=False)}"
        )
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001", max_tokens=1000,
            messages=[{"role": "user", "content": prompt}]
        )
        return msg.content[0].text.strip()
    except Exception as e:
        return f"Fehler: {e}"
