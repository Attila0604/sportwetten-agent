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
    """Holt Spielergebnisse der letzten 2 Tage"""
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"{BASE_URL}/sports/{sport}/scores/",
                params={
                    "apiKey": ODDS_API_KEY,
                    "daysFrom": 2,
                }
            )
            if resp.status_code == 200:
                return resp.json()
    except Exception as e:
        print(f"  Ergebnis-Fehler ({sport}): {e}")
    return []


async def hole_alle_ergebnisse() -> list:
    """Holt alle Fußball-Ergebnisse"""
    alle = []
    for sport in SOCCER_SPORTS:
        ergebnisse = await hole_ergebnisse(sport)
        for e in ergebnisse:
            e["liga_key"] = sport
        alle.extend(ergebnisse)
    return alle


def finde_ergebnis(heim: str, gast: str, ergebnisse: list) -> dict:
    """Sucht das Ergebnis für ein bestimmtes Spiel"""
    heim_lower = heim.lower().strip()
    gast_lower = gast.lower().strip()

    for spiel in ergebnisse:
        spiel_heim = spiel.get("home_team", "").lower().strip()
        spiel_gast = spiel.get("away_team", "").lower().strip()

        # Exakter Match oder Teil-Match
        heim_match = (heim_lower in spiel_heim or spiel_heim in heim_lower or
                      _aehnlich(heim_lower, spiel_heim))
        gast_match = (gast_lower in spiel_gast or spiel_gast in gast_lower or
                      _aehnlich(gast_lower, spiel_gast))

        if heim_match and gast_match and spiel.get("completed"):
            scores = spiel.get("scores", [])
            if scores and len(scores) >= 2:
                heim_score = None
                gast_score = None
                for s in scores:
                    if s.get("name", "").lower() in spiel_heim:
                        heim_score = s.get("score")
                    else:
                        gast_score = s.get("score")

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


def _aehnlich(a: str, b: str) -> bool:
    """Prüft ob zwei Teamnamen ähnlich sind"""
    # Erste Wörter vergleichen
    a_words = set(a.split())
    b_words = set(b.split())
    gemeinsam = a_words & b_words
    return len(gemeinsam) >= 1 and len(gemeinsam[list(gemeinsam)[0]]) > 3 if gemeinsam else False


def berechne_wett_ergebnis(empfehlung: str, heim_score: int, gast_score: int) -> str:
    """Berechnet ob Wette gewonnen oder verloren"""
    if empfehlung == "Heimsieg":
        return "Gewonnen" if heim_score > gast_score else "Verloren"
    elif empfehlung == "Gastsieg":
        return "Gewonnen" if gast_score > heim_score else "Verloren"
    elif empfehlung == "Unentschieden":
        return "Gewonnen" if heim_score == gast_score else "Verloren"
    return "Offen"


def berechne_gewinn_verlust(status: str, einsatz: float, quote: float) -> float:
    """Berechnet Gewinn oder Verlust"""
    if status == "Gewonnen":
        return round(einsatz * quote - einsatz, 2)
    elif status == "Verloren":
        return round(-einsatz, 2)
    return 0.0


async def ergebnisse_aktualisieren() -> dict:
    """
    Hauptfunktion: Prüft alle offenen Wetten und aktualisiert Ergebnisse
    Gibt Zusammenfassung zurück
    """
    from excel_agent import get_statistik, wette_aktualisieren, EXCEL_PATH
    import openpyxl

    print(f"  → Hole Spielergebnisse...")
    alle_ergebnisse = await hole_alle_ergebnisse()
    print(f"  → {len(alle_ergebnisse)} Spiele gefunden")

    if not os.path.exists(EXCEL_PATH):
        print("  ⚠ Excel-Datei nicht gefunden")
        return {"aktualisiert": 0, "gewonnen": 0, "verloren": 0}

    wb = openpyxl.load_workbook(EXCEL_PATH)
    ws = wb["Meine Wetten"]

    aktualisiert = 0
    gewonnen = 0
    verloren = 0

    # Alle Zeilen durchgehen (ab Zeile 3, Zeile 1+2 = Header)
    for row_idx, row in enumerate(ws.iter_rows(min_row=3, values_only=False), start=3):
        status_zelle = ws.cell(row=row_idx, column=15)
        status = status_zelle.value

        # Nur offene Wetten prüfen
        if status != "Offen":
            continue

        heim = ws.cell(row=row_idx, column=3).value
        gast = ws.cell(row=row_idx, column=4).value
        empfehlung = ws.cell(row=row_idx, column=5).value
        quote = ws.cell(row=row_idx, column=6).value or 0
        einsatz = ws.cell(row=row_idx, column=10).value or 0

        if not heim or not gast:
            continue

        # Ergebnis suchen
        ergebnis = finde_ergebnis(str(heim), str(gast), alle_ergebnisse)

        if ergebnis.get("abgeschlossen"):
            heim_score = ergebnis["heim_score"]
            gast_score = ergebnis["gast_score"]
            endstand = ergebnis["endstand"]

            wett_status = berechne_wett_ergebnis(str(empfehlung), heim_score, gast_score)
            gv = berechne_gewinn_verlust(wett_status, float(einsatz), float(quote))

            # Excel aktualisieren
            from openpyxl.styles import Font, PatternFill
            GRUEN = "FF2ECC71"
            ROT = "FFE74C3C"
            WEISS = "FFFFFFFF"

            ws.cell(row=row_idx, column=12).value = endstand
            ws.cell(row=row_idx, column=13).value = f"{heim} {heim_score}:{gast_score} {gast}"

            gv_z = ws.cell(row=row_idx, column=14)
            gv_z.value = gv
            gv_z.number_format = '#,##0.00'
            gv_z.font = Font(name="Arial", bold=True, size=10,
                            color=GRUEN if gv > 0 else ROT)

            status_z = ws.cell(row=row_idx, column=15)
            status_z.value = wett_status
            if wett_status == "Gewonnen":
                status_z.fill = PatternFill("solid", start_color=GRUEN)
                status_z.font = Font(name="Arial", bold=True, color=WEISS, size=10)
                gewonnen += 1
            else:
                status_z.fill = PatternFill("solid", start_color=ROT)
                status_z.font = Font(name="Arial", bold=True, color=WEISS, size=10)
                verloren += 1

            aktualisiert += 1
            print(f"  ✓ {heim} vs {gast}: {endstand} → {wett_status} ({gv:+.2f}€)")

    wb.save(EXCEL_PATH)

    return {
        "aktualisiert": aktualisiert,
        "gewonnen": gewonnen,
        "verloren": verloren,
        "gesamt_ergebnisse": len(alle_ergebnisse),
    }
