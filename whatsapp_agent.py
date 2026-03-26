"""
WhatsApp Agent — sendet täglich um 21:00 Uhr die Top 3 Tipps via CallMeBot (100% kostenlos!)

EINRICHTUNG (einmalig, 2 Minuten):
1. Speichere diese Nummer in deinen WhatsApp-Kontakten:
      +34 644 59 91 23   (Name z.B. "CallMeBot")
2. Sende eine WhatsApp an diese Nummer mit genau diesem Text:
      I allow callmebot to send me messages
3. Du bekommst sofort deinen API Key zurück (z.B. 1234567)
4. Trage in .env ein:
      WHATSAPP_PHONE=4369912345678   (deine Nummer OHNE + z.B. AT: 43...)
      WHATSAPP_API_KEY=1234567
"""
import os
import httpx
from urllib.parse import quote
from datetime import datetime, timedelta

WHATSAPP_PHONE = os.getenv("WHATSAPP_PHONE", "")
WHATSAPP_API_KEY = os.getenv("WHATSAPP_API_KEY", "")
DASHBOARD_URL = os.getenv("DASHBOARD_URL", "http://dein-server:8000")


async def sende_whatsapp(nachricht: str) -> bool:
    """Sendet WhatsApp via CallMeBot API"""
    if not WHATSAPP_PHONE or not WHATSAPP_API_KEY:
        print("  ⚠ WhatsApp: WHATSAPP_PHONE / WHATSAPP_API_KEY fehlt in .env")
        return False
    try:
        url = (
            f"https://api.callmebot.com/whatsapp.php"
            f"?phone={WHATSAPP_PHONE}"
            f"&text={quote(nachricht)}"
            f"&apikey={WHATSAPP_API_KEY}"
        )
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.get(url)
        if resp.status_code == 200 and "queued" in resp.text.lower():
            print("  ✅ WhatsApp gesendet!")
            return True
        print(f"  ⚠ WhatsApp-Fehler ({resp.status_code}): {resp.text[:120]}")
        return False
    except Exception as e:
        print(f"  ✗ WhatsApp-Fehler: {e}")
        return False


def erstelle_tipp_nachricht(top3: list, kapital: float) -> str:
    """Erstellt die formatierte WhatsApp-Nachricht für Top 3 Tipps"""
    morgen = (datetime.now() + timedelta(days=1)).strftime("%d.%m.%Y")
    zeilen = [
        f"⚽ *SPORTWETTEN KI — {morgen}*",
        f"💰 Aktuelles Kapital: *{kapital:.2f}€*",
        "━━━━━━━━━━━━━━━━━━━━",
    ]

    if not top3:
        zeilen += [
            "",
            "❌ *Keine Value Bets heute.*",
            "Morgen wieder versuchen! 💪",
        ]
    else:
        risiko_emoji = {"Niedrig": "🟢", "Mittel": "🟡", "Hoch": "🔴"}
        for i, emp in enumerate(top3, 1):
            ev = round(emp.get("ev", 0) * 100, 1)
            einsatz = emp.get("empfohlener_einsatz", 0)
            pot = emp.get("potenz_gewinn", 0)
            re = risiko_emoji.get(emp.get("risiko", ""), "⚪")
            begr = emp.get("begruendung", "")
            if len(begr) > 75:
                begr = begr[:75] + "..."

            zeilen += [
                "",
                f"*#{i} — {emp.get('heim')} vs {emp.get('gast')}*",
                f"🏆 {emp.get('liga', '')}  |  🕐 {emp.get('zeit', '')}",
                f"▶️ Tipp: *{emp.get('empfehlung', '')}*  @  Quote *{emp.get('quote', '')}*",
                f"💵 Einsatz: *{einsatz:.2f}€*  |  Pot. Gewinn: *+{pot:.2f}€*",
                f"📊 EV: +{ev}%  |  {re} Risiko: {emp.get('risiko', '')}",
                f"💡 _{begr}_" if begr else "",
            ]

    zeilen += [
        "",
        "━━━━━━━━━━━━━━━━━━━━",
        f"📱 {DASHBOARD_URL}",
        "🤖 _Sportwetten KI Multi Agent_",
    ]
    # Leere Zeilen bereinigen
    return "\n".join(z for z in zeilen if z is not None)


def erstelle_wochen_nachricht(stats: dict) -> str:
    gv = stats.get("gesamt_gv", 0)
    roi = stats.get("roi", 0)
    return (
        f"📅 *WOCHENRÜCKBLICK*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🎯 Wetten gesamt: *{stats.get('gesamt_wetten', 0)}*\n"
        f"✅ Gewonnen: *{stats.get('gewonnen', 0)}*\n"
        f"❌ Verloren: *{stats.get('verloren', 0)}*\n"
        f"🎯 Trefferquote: *{stats.get('trefferquote', 0):.1f}%*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"💰 Kapital: *{stats.get('aktuelles_kapital', 0):.2f}€*\n"
        f"{'📈' if gv >= 0 else '📉'} Woche G/V: *{'+' if gv>=0 else ''}{gv:.2f}€*\n"
        f"ROI: *{'+' if roi>=0 else ''}{roi:.2f}%*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🤖 _Sportwetten KI Multi Agent_"
    )


async def sende_tipps(top3: list, kapital: float) -> bool:
    msg = erstelle_tipp_nachricht(top3, kapital)
    return await sende_whatsapp(msg)


async def sende_wochen_stats(stats: dict) -> bool:
    msg = erstelle_wochen_nachricht(stats)
    return await sende_whatsapp(msg)
