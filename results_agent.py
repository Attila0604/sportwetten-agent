"""
Ergebnis-Agent — prüft täglich ob Wetten gewonnen oder verloren haben
Läuft täglich um 10:00 Uhr und aktualisiert die Excel-Datei automatisch
"""
import os
import httpx
from datetime import datetime, date, timedelta

ODDS_API_KEY = os.getenv("ODDS_API_KEY")
BASE_URL = "https://api.the-odds-api.com/v4"

SOCCER_SPORTS = [
    "soccer_germany_bundesliga",
    "soccer_england_league1",
    "soccer_epl",
    "soccer_spain_la_liga",
    "soccer_italy_serie_a",
    "soccer_france_ligue_one",
    "soccer_uefa_champs_league",
    "soccer_austria_bundesliga",
]


async def hole_ergebnisse(sport: str) -> list:
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"{BASE_URL}/sports/{sport}/scores/",
                params={
                    "apiKey": ODDS_API_KEY,
                    "daysFrom": 3  # FIX Bug 1: war 2, zu knapp für Spiele von vor 2+ Tagen
                }
            )
            if resp.status_code == 200:
                return resp.json()
            else:
                print(f"  API Fehler ({sport}): {resp.status_code}")
    except Exception as e:
        print(f"  Ergebnis-Fehler ({sport}): {e}")
    return []


async def hole_alle_ergebnisse() -> list:
    alle = []
    for sport in SOCCER_SPORTS:
        ergebnisse = await hole_ergebnisse(sport)
        for e in ergebnisse:
            e["liga_key"] = sport
        alle.extend(ergebnisse)
    print(f"  → Gesamt {len(alle)} Spiele von API geladen")
    return alle


def _aehnlich(a: str, b: str) -> bool:
    """Prüft ob zwei Teamnamen ähnlich sind"""
    a_words = a.split()
    b_words = b.split()
    for wa in a_words:
        for wb in b_words:
            if len(wa) > 3 and len(wb) > 3 and (wa in wb or wb in wa):
                return True
    return False


def finde_ergebnis(heim: str, gast: str, ergebnisse: list) -> dict:
    """Sucht das Ergebnis für ein bestimmtes Spiel"""
    heim_lower = heim.lower().strip()
    gast_lower = gast.lower().strip()

    for spiel in ergebnisse:
        spiel_heim = spiel.get("home_team", "").lower().strip()
        spiel_gast = spiel.get("away_team", "").lower().strip()

        heim_match = (heim_lower in spiel_heim or spiel_heim in heim_lower or
                      _aehnlich(heim_lower, spiel_heim))
        gast_match = (gast_lower in spiel_gast or spiel_gast in gast_lower or
                      _aehnlich(gast_lower, spiel_gast))

        if heim_match and gast_match and spiel.get("completed"):
            scores = spiel.get("scores") or []
            if len(scores) >= 2:
                heim_score = None
                gast_score = None

                # FIX Bug 2: Score-Parsing war fehlerhaft, jetzt beide Teams explizit prüfen
                for s in scores:
                    name = s.get("name", "").lower().strip()
                    name_match_heim = (name in spiel_heim or spiel_heim in name or
                                       _aehnlich(name, spiel_heim))
                    name_match_gast = (name in spiel_gast or spiel_gast in name or
                                       _aehnlich(name, spiel_gast))

                    if name_match_heim:
                        heim_score = s.get("score")
                    elif name_match_gast:
                        gast_score = s.get("score")

                # Fallback: Wenn Matching fehlschlägt, Reihenfolge nutzen
                if heim_score is None and len(scores) >= 1:
                    heim_score = scores[0].get("score")
                if gast_score is None and len(scores) >= 2:
                    gast_score = scores[1].get("score")

                if heim_score is not None and gast_score is not None:
                    return {
                        "heim": spiel.get("home_team"),
                        "gast": spiel.get("away_team"),
                        "heim_score": int(heim_score),
                        "gast_score": int(gast_score),
                        "endstand": f"{heim_score}:{gast_score}",
                        "abgeschlossen": True,
                    }
    return {}


def berechne_wett_ergebnis(empfehlung: str, heim_score: int, gast_score: int) -> str:
    if empfehlung == "Heimsieg":
        return "Gewonnen" if heim_score > gast_score else "Verloren"
    elif empfehlung == "Gastsieg":
        return "Gewonnen" if gast_score > heim_score else "Verloren"
    elif empfehlung == "Unentschieden":
        return "Gewonnen" if heim_score == gast_score else "Verloren"
    return "Offen"


def berechne_gewinn_verlust(status: str, einsatz: float, quote: float) -> float:
    if status == "Gewonnen":
        return round(einsatz * quote - einsatz, 2)
    elif status == "Verloren":
        return round(-einsatz, 2)
    return 0.0


def aktualisiere_kapital_sheet(ws_kapital, heute: date, tages_gv: float,
                                kapital_vorher: float, anzahl_wetten: int):
    """Schreibt täglichen Kapitalstand ins Kapital-Sheet"""
    # Nächste leere Zeile finden (ab Zeile 3, da Zeile 1+2 Header)
    naechste_zeile = 3
    for row in range(3, ws_kapital.max_row + 2):
        if ws_kapital.cell(row=row, column=1).value is None:
            naechste_zeile = row
            break

    kapital_neu = round(kapital_vorher + tages_gv, 2)
    roi = round((tages_gv / kapital_vorher * 100), 2) if kapital_vorher > 0 else 0.0

    ws_kapital.cell(row=naechste_zeile, column=1).value = heute.strftime("%d.%m.%Y")
    ws_kapital.cell(row=naechste_zeile, column=2).value = kapital_neu
    ws_kapital.cell(row=naechste_zeile, column=3).value = round(tages_gv, 2)
    ws_kapital.cell(row=naechste_zeile, column=4).value = anzahl_wetten
    ws_kapital.cell(row=naechste_zeile, column=5).value = roi
    ws_kapital.cell(row=naechste_zeile, column=6).value = "Auto-Update"

    print(f"  → Kapital-Sheet: {kapital_vorher:.2f}€ + {tages_gv:+.2f}€ = {kapital_neu:.2f}€")
    return kapital_neu


async def ergebnisse_aktualisieren() -> dict:
    from excel_agent import EXCEL_PATH
    import openpyxl
    from openpyxl.styles import Font, PatternFill

    GRUEN = "FF2ECC71"
    ROT = "FFE74C3C"
    WEISS = "FFFFFFFF"

    print(f"  → Hole Spielergebnisse...")
    alle_ergebnisse = await hole_alle_ergebnisse()
    print(f"  → {len(alle_ergebnisse)} Spiele gefunden")

    if not os.path.exists(EXCEL_PATH):
        print("  ⚠ Excel-Datei nicht gefunden")
        return {"aktualisiert": 0, "gewonnen": 0, "verloren": 0}

    wb = openpyxl.load_workbook(EXCEL_PATH)
    ws = wb["Meine Wetten"]
    ws_kapital = wb["Kapital"]

    aktualisiert = 0
    gewonnen = 0
    verloren = 0
    tages_gv = 0.0
    kapital_aktuell = 1000.0  # Startkapital

    # Aktuelles Kapital aus letztem Kapital-Eintrag lesen
    for row in range(ws_kapital.max_row, 2, -1):
        val = ws_kapital.cell(row=row, column=2).value
        if val is not None:
            try:
                kapital_aktuell = float(val)
            except:
                pass
            break

    for row_idx in range(3, ws.max_row + 1):
        status_raw = ws.cell(row=row_idx, column=15).value

        # FIX Bug 4: Whitespace-sicherer Vergleich
        status = str(status_raw or "").strip()
        if status != "Offen":
            continue

        heim = ws.cell(row=row_idx, column=3).value
        gast = ws.cell(row=row_idx, column=4).value
        empfehlung = ws.cell(row=row_idx, column=5).value
        quote = ws.cell(row=row_idx, column=6).value or 0
        einsatz = ws.cell(row=row_idx, column=10).value or 0

        if not heim or not gast:
            continue

        ergebnis = finde_ergebnis(str(heim), str(gast), alle_ergebnisse)

        if ergebnis.get("abgeschlossen"):
            heim_score = ergebnis["heim_score"]
            gast_score = ergebnis["gast_score"]
            endstand = ergebnis["endstand"]

            wett_status = berechne_wett_ergebnis(str(empfehlung), heim_score, gast_score)
            gv = berechne_gewinn_verlust(wett_status, float(einsatz), float(quote))
            tages_gv += gv

            # Spalte 12: Endstand (z.B. "2:1")
            ws.cell(row=row_idx, column=12).value = endstand

            # Spalte 13: Vollständiger Spielstand
            ws.cell(row=row_idx, column=13).value = f"{heim} {heim_score}:{gast_score} {gast}"

            # Spalte 14: G/V EUR
            gv_z = ws.cell(row=row_idx, column=14)
            gv_z.value = gv
            gv_z.number_format = '#,##0.00'
            gv_z.font = Font(name="Arial", bold=True, size=10,
                             color=GRUEN if gv > 0 else ROT)

            # Spalte 15: Status
            sz = ws.cell(row=row_idx, column=15)
            sz.value = wett_status
            if wett_status == "Gewonnen":
                sz.fill = PatternFill("solid", start_color=GRUEN)
                sz.font = Font(name="Arial", bold=True, color=WEISS, size=10)
                gewonnen += 1
            else:
                sz.fill = PatternFill("solid", start_color=ROT)
                sz.font = Font(name="Arial", bold=True, color=WEISS, size=10)
                verloren += 1

            aktualisiert += 1
            print(f"  ✓ {heim} vs {gast}: {endstand} → {wett_status} ({gv:+.2f}€)")

    # FIX Bug 3: Kapital-Sheet befüllen wenn Wetten aktualisiert wurden
    if aktualisiert > 0:
        aktualisiere_kapital_sheet(
            ws_kapital=ws_kapital,
            heute=date.today(),
            tages_gv=tages_gv,
            kapital_vorher=kapital_aktuell,
            anzahl_wetten=aktualisiert
        )

    wb.save(EXCEL_PATH)
    print(f"  → Excel gespeichert: {aktualisiert} Wetten aktualisiert")

    return {
        "aktualisiert": aktualisiert,
        "gewonnen": gewonnen,
        "verloren": verloren,
        "tages_gv": round(tages_gv, 2),
        "gesamt_ergebnisse": len(alle_ergebnisse),
    }
