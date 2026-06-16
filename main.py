import os
from datetime import datetime, date, timedelta
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI, BackgroundTasks
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from dotenv import load_dotenv

load_dotenv()

from odds_agent import get_parsed_odds
from analysis_agent import analysiere_spiele, generiere_wochen_analyse, generiere_monats_analyse
from excel_agent import (
    erstelle_excel, empfehlungen_hinzufuegen, top3_als_wetten_eintragen,
    analyse_eintragen, get_statistik, get_kapital, EXCEL_PATH
)
from gdrive_agent import excel_zu_drive_hochladen
from whatsapp_agent import sende_tipps, sende_wochen_stats
from results_agent import ergebnisse_aktualisieren
from data_import import importiere   # Weg B: Historien-Import
from predict import prognose          # Weg B: Poisson-Prognose

_cache = {
    "datum": None, "alle_empfehlungen": [], "top3": [],
    "zusammenfassung": "", "letzter_lauf": None, "analyse_laeuft": False,
    "letzte_ergebnisse": None,
}

scheduler = AsyncIOScheduler(timezone="Europe/Vienna")


# ── Hauptanalyse täglich 21:00 ────────────────────────────────────────────────
async def abend_analyse():
    print(f"\n[{datetime.now().strftime('%d.%m.%Y %H:%M')}] 🌙 Abend-Analyse 21:00 Uhr...")
    _cache["analyse_laeuft"] = True
    try:
        spiele = await get_parsed_odds()
        print(f"  → {len(spiele)} Spiele")
        kapital = get_kapital()
        result = await analysiere_spiele(spiele, kapital)

        # ── Konfidenz Filter ≥ 7 ─────────────────────────────────────────────
        top3_roh = result.get("top3", [])
        top3 = [
            emp for emp in top3_roh
            if isinstance(emp, dict) and emp.get("konfidenz", 0) >= 7
        ]
        # Fallback: Falls alle rausgefiltert → besten nehmen
        if not top3 and top3_roh:
            top3 = [top3_roh[0]] if isinstance(top3_roh[0], dict) else []
        # ─────────────────────────────────────────────────────────────────────

        alle = result.get("alle_empfehlungen", [])
        morgen = (datetime.now() + timedelta(days=1)).strftime("%d.%m.%Y")

        empfehlungen_hinzufuegen(result, morgen)
        if top3:
            top3_als_wetten_eintragen(top3, kapital, morgen)

        _cache.update({
            "datum": date.today().isoformat(),
            "alle_empfehlungen": alle,
            "top3": top3,
            "zusammenfassung": result.get("zusammenfassung", ""),
            "letzter_lauf": datetime.now().isoformat(),
        })

        print("  → WhatsApp senden...")
        await sende_tipps(top3, kapital)

        print("  → Google Drive Upload...")
        await excel_zu_drive_hochladen()

        print(f"  ✅ Abend-Analyse fertig! {len(top3)} Top-Tipps\n")
    except Exception as e:
        print(f"  ✗ Fehler: {e}\n")
    finally:
        _cache["analyse_laeuft"] = False


# ── Ergebnis-Check täglich 10:00 ──────────────────────────────────────────────
async def ergebnis_check():
    print(f"\n[{datetime.now().strftime('%d.%m.%Y %H:%M')}] 🏆 Ergebnis-Check 10:00 Uhr...")
    try:
        ergebnisse = await ergebnisse_aktualisieren()
        _cache["letzte_ergebnisse"] = {
            **ergebnisse,
            "zeitpunkt": datetime.now().isoformat()
        }

        if ergebnisse["aktualisiert"] > 0:
            from whatsapp_agent import sende_whatsapp
            tages_gv = ergebnisse.get("tages_gv", 0)
            msg = (
                f"📊 *ERGEBNIS-UPDATE*\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"✅ Gewonnen: *{ergebnisse['gewonnen']}*\n"
                f"❌ Verloren: *{ergebnisse['verloren']}*\n"
                f"🔄 Aktualisiert: *{ergebnisse['aktualisiert']}* Wetten\n"
                f"💰 Tages G/V: *{tages_gv:+.2f}€*\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"📊 Excel wurde aktualisiert!\n"
                f"🤖 _Sportwetten KI Multi Agent_"
            )
            await sende_whatsapp(msg)
            await excel_zu_drive_hochladen()
            print(f"  ✅ {ergebnisse['aktualisiert']} Ergebnisse aktualisiert")
        else:
            print(f"  → Keine neuen Ergebnisse")

        return ergebnisse

    except Exception as e:
        print(f"  ✗ Ergebnis-Fehler: {e}")
        return {"aktualisiert": 0, "gewonnen": 0, "verloren": 0, "fehler": str(e)}


# ── Wochenanalyse Montag 07:00 ────────────────────────────────────────────────
async def wochen_analyse():
    print(f"[{datetime.now().strftime('%d.%m.%Y %H:%M')}] 📅 Wochenanalyse...")
    try:
        stats = get_statistik()
        wetten = [w for w in stats.get("alle_wetten", []) if w.get("status") != "Offen"][-20:]
        analyse = await generiere_wochen_analyse(wetten)
        gv = sum(w.get("gewinn_verlust", 0) for w in wetten)
        einsatz = sum(w.get("einsatz", 0) for w in wetten)
        roi = round(gv / einsatz * 100, 2) if einsatz > 0 else 0
        lw = date.today() - timedelta(days=7)
        zeitraum = f"KW {date.today().isocalendar()[1]-1} ({lw.strftime('%d.%m')}–{(date.today()-timedelta(days=1)).strftime('%d.%m.%Y')})"
        analyse_eintragen(zeitraum, analyse, len(wetten), roi, monatlich=False)
        await sende_wochen_stats(stats)
        await excel_zu_drive_hochladen()
        print(f"  ✅ Wochenanalyse OK (ROI: {roi}%)")
    except Exception as e:
        print(f"  ✗ Fehler: {e}")


# ── Monatsanalyse 1. d. Monats 08:00 ─────────────────────────────────────────
async def monats_analyse():
    print(f"[{datetime.now().strftime('%d.%m.%Y %H:%M')}] 🗓️ Monatsanalyse...")
    try:
        stats = get_statistik()
        ks = stats.get("startkapital", float(os.getenv("STARTKAPITAL", "1000")))
        ke = stats.get("aktuelles_kapital", ks)
        wetten = [w for w in stats.get("alle_wetten", []) if w.get("status") != "Offen"]
        analyse = await generiere_monats_analyse(wetten, ks, ke)
        roi = round((ke - ks) / ks * 100, 2) if ks > 0 else 0
        lm = (date.today().replace(day=1) - timedelta(days=1)).strftime("%m.%Y")
        analyse_eintragen(f"Monat {lm}", analyse, len(wetten), roi, monatlich=True)
        await excel_zu_drive_hochladen()
        print(f"  ✅ Monatsanalyse OK")
    except Exception as e:
        print(f"  ✗ Fehler: {e}")


# ── App ───────────────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    if not os.path.exists(EXCEL_PATH):
        erstelle_excel()
        print("✓ Excel erstellt")

    scheduler.add_job(abend_analyse,  "cron", hour=21, minute=0,         id="abend")
    scheduler.add_job(ergebnis_check, "cron", hour=10, minute=0,         id="ergebnisse")
    scheduler.add_job(wochen_analyse, "cron", day_of_week="mon", hour=7, id="woche")
    scheduler.add_job(monats_analyse, "cron", day=1, hour=8,             id="monat")
    scheduler.start()
    print("✓ Scheduler:")
    print("  🌙 21:00  — Analyse + WhatsApp + Drive")
    print("  🏆 10:00  — Ergebnis-Check + WhatsApp")
    print("  📅 Mo 07:00 — Wochenanalyse")
    print("  🗓️  1. 08:00 — Monatsanalyse")
    yield
    scheduler.shutdown()


app = FastAPI(title="Sportwetten KI Multi-Agent v2.4", lifespan=lifespan)
static_dir = Path(__file__).parent
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


@app.get("/")
async def root():
    return FileResponse(str(static_dir / "index.html"))

@app.get("/api/empfehlungen")
async def get_empfehlungen():
    return JSONResponse({
        "alle_empfehlungen": _cache["alle_empfehlungen"],
        "top3":              _cache["top3"],
        "zusammenfassung":   _cache["zusammenfassung"],
        "letzter_lauf":      _cache["letzter_lauf"],
        "analyse_laeuft":    _cache["analyse_laeuft"],
        "datum":             date.today().isoformat(),
    })

@app.post("/api/analyse-starten")
async def analyse_starten(bg: BackgroundTasks):
    if _cache["analyse_laeuft"]:
        return {"message": "Läuft bereits..."}
    bg.add_task(abend_analyse)
    return {"message": "Analyse gestartet! Ca. 45 Sekunden..."}

@app.post("/api/ergebnisse-pruefen")
async def ergebnisse_pruefen():
    ergebnisse = await ergebnis_check()
    return {
        "message":           "Ergebnis-Check abgeschlossen!",
        "aktualisiert":      ergebnisse.get("aktualisiert", 0),
        "gewonnen":          ergebnisse.get("gewonnen", 0),
        "verloren":          ergebnisse.get("verloren", 0),
        "tages_gv":          ergebnisse.get("tages_gv", 0.0),
        "gesamt_ergebnisse": ergebnisse.get("gesamt_ergebnisse", 0),
        "fehler":            ergebnisse.get("fehler", None),
    }

@app.get("/api/statistik")
async def get_stats():
    return get_statistik()

@app.get("/api/excel-download")
async def excel_download():
    if not os.path.exists(EXCEL_PATH):
        erstelle_excel()
    return FileResponse(
        EXCEL_PATH,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=f"Sportwetten_{date.today().strftime('%Y%m%d')}.xlsx"
    )

@app.post("/api/drive-upload")
async def drive_upload(bg: BackgroundTasks):
    bg.add_task(excel_zu_drive_hochladen)
    return {"message": "Upload gestartet..."}

@app.post("/api/whatsapp-test")
async def whatsapp_test():
    from whatsapp_agent import sende_whatsapp
    ok = await sende_whatsapp("✅ *Test erfolgreich!*\nDein Sportwetten KI Agent ist aktiv! ⚽🤖")
    return {"success": ok, "message": "✅ Gesendet!" if ok else "❌ Fehler"}

@app.get("/api/status")
async def status():
    from whatsapp_agent import WHATSAPP_PHONE, WHATSAPP_API_KEY
    return {
        "status":               "online",
        "version":              "2.3.0",
        "uhrzeit":              datetime.now().strftime("%d.%m.%Y %H:%M"),
        "analyse_laeuft":       _cache["analyse_laeuft"],
        "letzter_lauf":         _cache["letzter_lauf"],
        "letzte_ergebnisse":    _cache["letzte_ergebnisse"],
        "excel_vorhanden":      os.path.exists(EXCEL_PATH),
        "drive_eingerichtet":   os.path.exists(os.getenv("GDRIVE_TOKEN_FILE", "data/gdrive_token.json")),
        "whatsapp_eingerichtet": bool(WHATSAPP_PHONE and WHATSAPP_API_KEY),
        "startkapital":         float(os.getenv("STARTKAPITAL", "1000")),
        "max_risiko":           float(os.getenv("MAX_RISIKO_PROZENT", "3")),
        "naechste_analyse":     "21:00 Uhr",
        "naechster_ergebnis_check": "10:00 Uhr",
    }

@app.get("/import-historie")
async def import_historie(secret: str = "", seasons: str = "2023,2024,2025"):
    """Weg B: Historien-Import in Supabase. seasons per URL wählbar, z.B. ?seasons=2025"""
    if secret != os.getenv("IMPORT_SECRET", ""):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    saison_liste = [s.strip() for s in seasons.split(",") if s.strip()]
    return await importiere(seasons=saison_liste)

@app.get("/prognose")
async def prognose_endpoint(home: str, away: str, league: str = "PL",
                            quote_heim: float = None,
                            quote_remis: float = None,
                            quote_gast: float = None):
    """Weg B: Poisson-Prognose für ein Spiel. Quoten optional -> zeigt Edge."""
    return await prognose(home, away, league,
                          quote_heim, quote_remis, quote_gast)

@app.post("/run-analysis")
async def run_analysis(bg: BackgroundTasks):
    if _cache["analyse_laeuft"]:
        return {"message": "Läuft bereits..."}
    bg.add_task(abend_analyse)
    return {"message": "Analyse gestartet!"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=int(os.getenv("PORT", 8000)), reload=False)
