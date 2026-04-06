import os
import json
from datetime import datetime
import anthropic

from value_bet_agent import analysiere_value_bets, top_value_bets
from stats_agent import hole_statistiken_fuer_spiel

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
    text = text.strip()
    if "```" in text:
        parts = text.split("```")
        for part in parts:
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
            "zusammenfassung": "Keine Value Bets gefunden (EV-Filter).",
            "value_bets_gesamt": 0,
            "value_bets_roh": [],
        }

    # ── Statistiken für Top 5 holen ──────────────────────────────────────────
    print("  → Statistiken von API-Football holen...")
    vb_liste = []
    for vb in top_value:
        stats = {}
        try:
            stats = await hole_statistiken_fuer_spiel(
                vb["heim"], vb["gast"], vb["liga"]
            )
        except Exception as e:
            print(f"  Stats Fehler [{vb['heim']} vs {vb['gast']}]: {e}")

        eintrag = {
            "heim":   vb["heim"],
            "gast":   vb["gast"],
            "liga":   vb["liga"],
            "zeit":   vb["zeit"],
            "tipp":   vb["empfehlung"],
            "quote":  vb["quote"],
            "bookie": vb["bookie"],
            "ev":     vb["ev"],
        }

        # Statistiken hinzufügen falls vorhanden
        if stats:
            eintrag["statistiken"] = {
                "heim_form":         stats.get("heim_form", "N/A"),
                "gast_form":         stats.get("gast_form", "N/A"),
                "heim_tore_schnitt": stats.get("heim_tore_schnitt", {}),
                "gast_tore_schnitt": stats.get("gast_tore_schnitt", {}),
                "h2h":               stats.get("h2h", {}),
            }

        vb_liste.append(eintrag)

    prompt = (
        f"Datum: {morgen} | Kapital: {kapital:.2f}EUR | Max-Einsatz: {max_e:.2f}EUR\n"
        f"Gesamt Value Bets: {anzahl_vb}\n"
        f"Top 5 mit Statistiken:\n{json.dumps(vb_liste, ensure_ascii=False)}\n\n"
        f"Analysiere die Statistiken (Form, H2H, Tore) und waehle TOP 3.\n"
        f"Beruecksichtige: Form der letzten 5 Spiele, H2H Historie, Tore-Schnitt.\n"
        f"Antworte NUR mit diesem JSON:\n"
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

        # Nur Dictionaries durchlassen
        top3 = [emp for emp in result.get("top3", []) if isinstance(emp, dict)]
        alle = [emp for emp in result.get("alle_empfehlungen", []) if isinstance(emp, dict)]

        if not alle:
            alle = top3

        for emp in [e for e in top3 if isinstance(e, dict)]:
            kelly = berechne_kelly(kapital, emp.get("echte_wahrscheinlichkeit", 0), emp.get("quote", 0))
            ki_e  = emp.get("empfohlener_einsatz", kelly)
            emp["empfohlener_einsatz"] = round(min(float(ki_e or kelly), max_e), 2)
            emp["kelly_einsatz"]       = kelly
            emp["max_einsatz"]         = max_e
            emp["potenz_gewinn"]       = round(
                emp["empfohlener_einsatz"] * emp.get("quote", 1) - emp["empfohlener_einsatz"], 2
            )

        return {
            "alle_empfehlungen":  alle,
            "top3":               top3,
            "zusammenfassung":    result.get("zusammenfassung", ""),
            "value_bets_gesamt":  anzahl_vb,
            "value_bets_roh":     top_value,
        }

    except Exception as e:
        print(f"Analyse-Fehler: {e}")
        fallback_top3 = []
        for vb in top_value[:3]:
            if not isinstance(vb, dict):
                continue
            einsatz = berechne_kelly(kapital, vb.get("implizite_wahrscheinlichkeit", 0.5), vb["quote"])
            fallback_top3.append({
                **vb,
                "konfidenz":                7,
                "risiko":                   "Mittel",
                "begruendung":              f"Value Bet: EV +{vb['ev']*100:.1f}% (Konsens-Methode)",
                "empfohlener_einsatz":      einsatz,
                "echte_wahrscheinlichkeit": vb.get("implizite_wahrscheinlichkeit", 0),
                "potenz_gewinn":            round(einsatz * vb["quote"] - einsatz, 2),
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
