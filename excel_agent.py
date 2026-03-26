import os
import json
from datetime import datetime, date
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

EXCEL_PATH = os.getenv("EXCEL_PATH", "data/wett_tracker.xlsx")
STARTKAPITAL = float(os.getenv("STARTKAPITAL", "1000"))

# Farben
C = {
    "dunkel": "FF0D1117", "card": "FF161B22", "blau": "FF1A8FE3",
    "gruen": "FF2ECC71", "rot": "FFE74C3C", "gold": "FFF1C40F",
    "weiss": "FFFFFFFF", "grau": "FF8B949E", "hellgrau": "FFF0F2F5",
    "dunkelgrau": "FF2C3E50", "navy": "FF1A252F",
}

def rand(c="FFD0D7DE"):
    s = Side(style="thin", color=c)
    return Border(left=s, right=s, top=s, bottom=s)

def kh(z, txt, fg="FFFFFFFF", bg="FF0D1117", sz=11, fett=True):
    z.value = txt
    z.font = Font(name="Arial", bold=fett, color=fg, size=sz)
    z.fill = PatternFill("solid", start_color=bg[2:] if bg.startswith("FF") else bg)
    z.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    z.border = rand()

def dz(z, v, fmt=None, fett=False, fg=None, bg=None, mitte=True):
    z.value = v
    z.font = Font(name="Arial", bold=fett, color=fg or "FF000000", size=10)
    if bg: z.fill = PatternFill("solid", start_color=bg[2:] if bg.startswith("FF") else bg)
    if fmt: z.number_format = fmt
    z.alignment = Alignment(horizontal="center" if mitte else "left", vertical="center")
    z.border = rand("FFDDDDDD")

def erstelle_excel():
    wb = Workbook()

    # Sheet 1: Empfehlungen
    ws1 = wb.active
    ws1.title = "📊 Empfehlungen"
    _sheet_empfehlungen(ws1)

    # Sheet 2: Meine Wetten (Top 3 auto-eingetragen)
    ws2 = wb.create_sheet("🎯 Meine Wetten")
    _sheet_wetten(ws2)

    # Sheet 3: Kapital-Verlauf
    ws3 = wb.create_sheet("💰 Kapital")
    _sheet_kapital(ws3)

    # Sheet 4: Wochenanalyse
    ws4 = wb.create_sheet("📅 Wochenanalyse")
    _sheet_analyse(ws4, "WOCHENANALYSE")

    # Sheet 5: Monatsanalyse
    ws5 = wb.create_sheet("🗓️ Monatsanalyse")
    _sheet_analyse(ws5, "MONATSANALYSE")

    # Sheet 6: Statistik
    ws6 = wb.create_sheet("📈 Statistik")
    _sheet_statistik(ws6)

    os.makedirs(os.path.dirname(EXCEL_PATH) if os.path.dirname(EXCEL_PATH) else ".", exist_ok=True)
    wb.save(EXCEL_PATH)
    return wb

def _sheet_empfehlungen(ws):
    ws.freeze_panes = "A3"
    ws.row_dimensions[1].height = 38
    ws.row_dimensions[2].height = 24
    ws.merge_cells("A1:N1")
    t = ws["A1"]
    t.value = "🏆 BET365 FUSSBALL VALUE BETS — KI TAGESANALYSE (23:00 Uhr)"
    t.font = Font(name="Arial", bold=True, color="FFFFFFFF", size=14)
    t.fill = PatternFill("solid", start_color="0D1117")
    t.alignment = Alignment(horizontal="center", vertical="center")

    cols = [
        ("A","Datum",12),("B","Liga",20),("C","Heim",22),("D","Gast",22),
        ("E","Uhrzeit",10),("F","Empfehlung",15),("G","Quote",9),
        ("H","Impl.%",10),("I","Echt%",10),("J","EV%",10),
        ("K","Konfidenz",12),("L","Risiko",10),("M","Top 3?",10),("N","Begründung",35),
    ]
    for col, hdr, w in cols:
        kh(ws[f"{col}2"], hdr)
        ws.column_dimensions[col].width = w

def _sheet_wetten(ws):
    ws.freeze_panes = "A3"
    ws.row_dimensions[1].height = 38
    ws.row_dimensions[2].height = 24
    ws.merge_cells("A1:P1")
    t = ws["A1"]
    t.value = "🎯 MEINE WETTEN — TOP 3 AUTO-TRACKING | Startkapital: " + f"{STARTKAPITAL:.0f}€ | Max 3% pro Wette"
    t.font = Font(name="Arial", bold=True, color="FFFFFFFF", size=13)
    t.fill = PatternFill("solid", start_color="0D1117")
    t.alignment = Alignment(horizontal="center", vertical="center")

    cols = [
        ("A","Datum",12),("B","Liga",18),("C","Heim",20),("D","Gast",20),
        ("E","Empfehlung",14),("F","Quote",9),("G","Kapital €",12),
        ("H","Max 3% €",11),("I","Kelly €",11),("J","Einsatz €",12),
        ("K","Pot.Gewinn €",14),("L","Endstand",12),("M","Ergebnis",15),
        ("N","Gewinn/V. €",14),("O","Status",12),("P","EV%",9),
    ]
    for col, hdr, w in cols:
        kh(ws[f"{col}2"], hdr)
        ws.column_dimensions[col].width = w

def _sheet_kapital(ws):
    ws.freeze_panes = "A3"
    ws.row_dimensions[1].height = 38
    ws.row_dimensions[2].height = 24
    ws.merge_cells("A1:F1")
    t = ws["A1"]
    t.value = "💰 KAPITALVERLAUF — Startkapital: " + f"{STARTKAPITAL:.0f}€"
    t.font = Font(name="Arial", bold=True, color="FFFFFFFF", size=14)
    t.fill = PatternFill("solid", start_color="0D1117")
    t.alignment = Alignment(horizontal="center", vertical="center")
    cols = [
        ("A","Datum",14),("B","Kapital €",16),("C","Tagesgewinn €",16),
        ("D","Wetten heute",14),("E","ROI heute %",14),("F","Notiz",25),
    ]
    for col, hdr, w in cols:
        kh(ws[f"{col}2"], hdr)
        ws.column_dimensions[col].width = w

def _sheet_analyse(ws, titel):
    ws.row_dimensions[1].height = 40
    ws.row_dimensions[2].height = 22
    ws.merge_cells("A1:D1")
    t = ws["A1"]
    t.value = f"📝 {titel} — KI AUSWERTUNG"
    t.font = Font(name="Arial", bold=True, color="FFFFFFFF", size=14)
    t.fill = PatternFill("solid", start_color="0D1117")
    t.alignment = Alignment(horizontal="center", vertical="center")
    for col, hdr, w in [("A","Zeitraum",20),("B","KI-Analyse",80),("C","Wetten",10),("D","ROI%",12)]:
        kh(ws[f"{col}2"], hdr)
        ws.column_dimensions[col].width = w

def _sheet_statistik(ws):
    ws.row_dimensions[1].height = 40
    ws.merge_cells("A1:C1")
    t = ws["A1"]
    t.value = "📈 GESAMTSTATISTIK"
    t.font = Font(name="Arial", bold=True, color="FFFFFFFF", size=16)
    t.fill = PatternFill("solid", start_color="0D1117")
    t.alignment = Alignment(horizontal="center", vertical="center")

    labels = [
        (3,"Startkapital €"), (4,"Aktuelles Kapital €"),
        (5,"Gesamt Gewinn/Verlust €"), (6,"ROI %"),
        (7,"Gesamt Wetten"), (8,"Gewonnen"), (9,"Verloren"),
        (10,"Offen"), (11,"Trefferquote %"),
        (12,"Durchschnittl. Quote"), (13,"Durchschnittl. Einsatz €"),
        (14,"Beste Wette €"), (15,"Schlechteste Wette €"),
    ]
    formeln = {
        3: str(STARTKAPITAL),
        4: "=C3+SUM('🎯 Meine Wetten'!N3:N10000)",
        5: "=C4-C3",
        6: "=IF(C3>0,(C4-C3)/C3*100,0)",
        7: "=COUNTA('🎯 Meine Wetten'!A3:A10000)",
        8: "=COUNTIF('🎯 Meine Wetten'!O3:O10000,\"Gewonnen\")",
        9: "=COUNTIF('🎯 Meine Wetten'!O3:O10000,\"Verloren\")",
        10: "=COUNTIF('🎯 Meine Wetten'!O3:O10000,\"Offen\")",
        11: "=IF(C7>0,C8/C7*100,0)",
        12: "=IF(C7>0,AVERAGEIF('🎯 Meine Wetten'!F3:F10000,\">0\"),0)",
        13: "=IF(C7>0,AVERAGE('🎯 Meine Wetten'!J3:J10000),0)",
        14: "=IF(C7>0,MAX('🎯 Meine Wetten'!N3:N10000),0)",
        15: "=IF(C7>0,MIN('🎯 Meine Wetten'!N3:N10000),0)",
    }
    fmt_map = {4:'#,##0.00"€"',5:'#,##0.00"€"',6:'#,##0.0"%"',
               11:'#,##0.0"%"',12:'#,##0.00',13:'#,##0.00"€"',
               14:'#,##0.00"€"',15:'#,##0.00"€"'}

    for row, lbl in labels:
        ws.row_dimensions[row].height = 24
        l = ws.cell(row=row, column=1, value=lbl)
        l.font = Font(name="Arial", bold=True, color="FFFFFFFF", size=11)
        l.fill = PatternFill("solid", start_color="2C3E50")
        l.alignment = Alignment(horizontal="left", vertical="center", indent=1)
        l.border = rand("FF555555")
        ws.column_dimensions["A"].width = 28

        v = ws.cell(row=row, column=3)
        v.value = formeln.get(row, "")
        if row in fmt_map: v.number_format = fmt_map[row]
        v.font = Font(name="Arial", bold=True, size=13, color="FF1A8FE3")
        v.fill = PatternFill("solid", start_color="F0F2F5")
        v.alignment = Alignment(horizontal="center", vertical="center")
        v.border = rand()
        ws.column_dimensions["C"].width = 22

        # Farb-Indikatoren
        if row in [5,6]:
            # ROI grün/rot Indikator (manuell gesetzt - kein bedingtes Format via openpyxl einfach)
            pass


# ─── Daten schreiben ────────────────────────────────────────────────────────

def empfehlungen_hinzufuegen(result: dict, datum: str = None):
    """Schreibt alle Empfehlungen + markiert Top3"""
    if not os.path.exists(EXCEL_PATH): erstelle_excel()
    wb = load_workbook(EXCEL_PATH)
    ws = wb["📊 Empfehlungen"]
    heute = datum or date.today().strftime("%d.%m.%Y")

    alle = result.get("alle_empfehlungen", [])
    top3_ids = {e.get("spiel_id") for e in result.get("top3", [])}
    zeile = ws.max_row + 1
    if zeile <= 2: zeile = 3

    farben = ["FFFFFFFF", "FFF8F9FA"]
    for i, emp in enumerate(alle):
        bg = farben[i % 2]
        r = zeile + i
        ist_top3 = emp.get("spiel_id") in top3_ids
        ev_p = round(emp.get("ev", 0) * 100, 2)

        vals = [
            (1, heute, None, False, None),
            (2, emp.get("liga",""), None, False, None),
            (3, emp.get("heim",""), None, True, C["navy"]),
            (4, emp.get("gast",""), None, True, C["navy"]),
            (5, emp.get("zeit","")[-5:] if len(emp.get("zeit",""))>5 else "", None, False, None),
            (6, emp.get("empfehlung",""), None, True, None),
            (7, emp.get("quote",0), '#,##0.00', True, C["blau"]),
            (8, round(emp.get("implizite_wahrscheinlichkeit",0)*100,1), '#,##0.0', False, None),
            (9, round(emp.get("echte_wahrscheinlichkeit",0)*100,1), '#,##0.0', False, None),
            (10, ev_p, '#,##0.00', True, C["gruen"] if ev_p>0 else C["rot"]),
            (11, emp.get("konfidenz",0), None, True, None),
            (12, emp.get("risiko",""), None, False, None),
            (13, "⭐ TOP 3" if ist_top3 else "", None, True, C["gold"] if ist_top3 else None),
            (14, emp.get("begruendung",""), None, False, None),
        ]
        for col, val, fmt, fett, fg in vals:
            z = ws.cell(row=r, column=col)
            bg_use = "FFD4EDDA" if ist_top3 else (bg[2:] if bg.startswith("FF") else bg)
            dz(z, val, fmt, fett, fg, "FF" + bg_use if not bg_use.startswith("FF") else bg_use)
        ws.row_dimensions[r].height = 20
    wb.save(EXCEL_PATH)


def top3_als_wetten_eintragen(top3: list, aktuelles_kapital: float, datum: str = None):
    """Trägt die Top 3 automatisch in 'Meine Wetten' ein"""
    if not os.path.exists(EXCEL_PATH): erstelle_excel()
    wb = load_workbook(EXCEL_PATH)
    ws = wb["🎯 Meine Wetten"]
    heute = datum or date.today().strftime("%d.%m.%Y")
    zeile = ws.max_row + 1
    if zeile <= 2: zeile = 3

    farben = ["FFFFFFFF", "FFF8F9FA"]
    for i, emp in enumerate(top3):
        bg = farben[i % 2]
        r = zeile + i
        einsatz = emp.get("empfohlener_einsatz", 0)
        quote = emp.get("quote", 0)
        pot_gewinn = round(einsatz * quote - einsatz, 2)
        max_e = emp.get("max_einsatz", 0)
        kelly_e = emp.get("kelly_einsatz", 0)
        ev_p = round(emp.get("ev", 0) * 100, 2)

        vals = [
            (1, heute, None, False, None),
            (2, emp.get("liga",""), None, False, None),
            (3, emp.get("heim",""), None, True, C["navy"]),
            (4, emp.get("gast",""), None, True, C["navy"]),
            (5, emp.get("empfehlung",""), None, True, None),
            (6, quote, '#,##0.00', True, C["blau"]),
            (7, round(aktuelles_kapital, 2), '#,##0.00"€"', False, None),
            (8, round(max_e, 2), '#,##0.00"€"', False, C["grau"]),
            (9, round(kelly_e, 2), '#,##0.00"€"', False, C["blau"]),
            (10, einsatz, '#,##0.00"€"', True, C["navy"]),
            (11, pot_gewinn, '#,##0.00"€"', True, C["gruen"]),
            (12, "- : -", None, False, None),
            (13, "Ausstehend", None, False, None),
            (14, 0.0, '#,##0.00"€"', True, None),
            (15, "Offen", None, True, None),
            (16, ev_p, '#,##0.00', False, C["gruen"] if ev_p>0 else C["rot"]),
        ]
        for col, val, fmt, fett, fg in vals:
            z = ws.cell(row=r, column=col)
            dz(z, val, fmt, fett, fg, bg[2:] if bg.startswith("FF") else bg)
        ws.row_dimensions[r].height = 20

    wb.save(EXCEL_PATH)


def kapital_eintragen(kapital: float, tagesgewinn: float, anzahl_wetten: int, notiz: str = ""):
    if not os.path.exists(EXCEL_PATH): erstelle_excel()
    wb = load_workbook(EXCEL_PATH)
    ws = wb["💰 Kapital"]
    zeile = ws.max_row + 1
    if zeile <= 2: zeile = 3
    heute = date.today().strftime("%d.%m.%Y")
    roi_heute = round(tagesgewinn / (kapital - tagesgewinn) * 100, 2) if (kapital - tagesgewinn) > 0 else 0
    vals = [heute, round(kapital,2), round(tagesgewinn,2), anzahl_wetten, roi_heute, notiz]
    fmts = [None, '#,##0.00"€"', '#,##0.00"€"', None, '#,##0.00"%"', None]
    for col, (val, fmt) in enumerate(zip(vals, fmts), 1):
        z = ws.cell(row=zeile, column=col)
        fg = C["gruen"] if col == 3 and tagesgewinn > 0 else C["rot"] if col == 3 and tagesgewinn < 0 else None
        dz(z, val, fmt, col in [2,3], fg)
    ws.row_dimensions[zeile].height = 20
    wb.save(EXCEL_PATH)


def analyse_eintragen(zeitraum: str, analyse_text: str, anzahl_wetten: int, roi: float, monatlich: bool = False):
    if not os.path.exists(EXCEL_PATH): erstelle_excel()
    wb = load_workbook(EXCEL_PATH)
    sheet_name = "🗓️ Monatsanalyse" if monatlich else "📅 Wochenanalyse"
    ws = wb[sheet_name]
    zeile = ws.max_row + 1
    if zeile <= 2: zeile = 3
    ws.row_dimensions[zeile].height = 80

    dz(ws.cell(row=zeile, column=1), zeitraum, None, True)
    z = ws.cell(row=zeile, column=2)
    z.value = analyse_text
    z.font = Font(name="Arial", size=10)
    z.alignment = Alignment(vertical="top", wrap_text=True)
    z.border = rand("FFDDDDDD")
    ws.column_dimensions["B"].width = 80
    dz(ws.cell(row=zeile, column=3), anzahl_wetten, None, True)
    dz(ws.cell(row=zeile, column=4), roi, '#,##0.00"%"', True,
       C["gruen"] if roi > 0 else C["rot"])
    wb.save(EXCEL_PATH)


def wette_aktualisieren(zeile_idx: int, endstand: str, ergebnis: str, gewinn_verlust: float, status: str):
    """Aktualisiert eine bestehende Wette mit Ergebnis"""
    if not os.path.exists(EXCEL_PATH): return
    wb = load_workbook(EXCEL_PATH)
    ws = wb["🎯 Meine Wetten"]
    r = zeile_idx + 2  # +2 wegen Header

    ws.cell(row=r, column=12).value = endstand
    ws.cell(row=r, column=13).value = ergebnis
    gv_z = ws.cell(row=r, column=14)
    gv_z.value = round(gewinn_verlust, 2)
    gv_z.font = Font(name="Arial", bold=True, size=10,
                      color=C["gruen"][2:] if gewinn_verlust > 0 else C["rot"][2:])
    gv_z.number_format = '#,##0.00"€"'

    status_z = ws.cell(row=r, column=15)
    status_z.value = status
    if status == "Gewonnen":
        status_z.fill = PatternFill("solid", start_color=C["gruen"][2:])
        status_z.font = Font(name="Arial", bold=True, color="FFFFFFFF", size=10)
    elif status == "Verloren":
        status_z.fill = PatternFill("solid", start_color=C["rot"][2:])
        status_z.font = Font(name="Arial", bold=True, color="FFFFFFFF", size=10)
    wb.save(EXCEL_PATH)


def get_statistik() -> dict:
    if not os.path.exists(EXCEL_PATH):
        erstelle_excel()
        return _leer()
    try:
        wb = load_workbook(EXCEL_PATH, data_only=True)
        ws = wb["🎯 Meine Wetten"]
        wetten = []
        for row in ws.iter_rows(min_row=3, values_only=True):
            if row[0]:
                wetten.append({
                    "datum": str(row[0]), "liga": row[1], "heim": row[2], "gast": row[3],
                    "empfehlung": row[4], "quote": row[5] or 0, "kapital": row[6] or 0,
                    "einsatz": row[9] or 0, "pot_gewinn": row[10] or 0,
                    "endstand": row[11], "ergebnis": row[12],
                    "gewinn_verlust": row[13] or 0, "status": row[14] or "Offen",
                    "ev": row[15] or 0,
                })

        gesamt = len(wetten)
        gew = sum(1 for w in wetten if w["status"] == "Gewonnen")
        verl = sum(1 for w in wetten if w["status"] == "Verloren")
        offen = sum(1 for w in wetten if w["status"] == "Offen")
        ges_einsatz = sum(w["einsatz"] for w in wetten)
        ges_gv = sum(w["gewinn_verlust"] for w in wetten)
        aktuelles_kapital = STARTKAPITAL + ges_gv

        return {
            "gesamt_wetten": gesamt, "gewonnen": gew, "verloren": verl, "offen": offen,
            "trefferquote": round(gew / gesamt * 100, 1) if gesamt > 0 else 0,
            "gesamt_einsatz": round(ges_einsatz, 2),
            "gesamt_gv": round(ges_gv, 2),
            "roi": round(ges_gv / STARTKAPITAL * 100, 2) if STARTKAPITAL > 0 else 0,
            "startkapital": STARTKAPITAL,
            "aktuelles_kapital": round(aktuelles_kapital, 2),
            "letzte_wetten": wetten[-10:][::-1],
            "alle_wetten": wetten,
        }
    except Exception as e:
        print(f"Statistik-Fehler: {e}")
        return _leer()


def get_kapital() -> float:
    stats = get_statistik()
    return stats.get("aktuelles_kapital", STARTKAPITAL)


def _leer():
    return {
        "gesamt_wetten": 0, "gewonnen": 0, "verloren": 0, "offen": 0,
        "trefferquote": 0, "gesamt_einsatz": 0, "gesamt_gv": 0,
        "roi": 0, "startkapital": STARTKAPITAL,
        "aktuelles_kapital": STARTKAPITAL,
        "letzte_wetten": [], "alle_wetten": [],
    }
