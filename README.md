# ⚽ Sportwetten KI Multi-Agent — v2.1

## Tagesablauf

| Uhrzeit | Was passiert |
|---|---|
| **21:00** | 🤖 KI analysiert alle Fußballspiele |
| **21:00** | ⭐ Top 3 Tipps werden ausgewählt |
| **21:00** | 📊 Excel wird automatisch befüllt |
| **21:00** | 📱 **WhatsApp mit Tipps wird gesendet** |
| **21:00** | ☁️ Excel in Google Drive hochgeladen |
| **Mo 07:00** | 📅 Wochenanalyse + WhatsApp |
| **1. d.M. 08:00** | 🗓️ Monatsanalyse |

---

## 📱 Beispiel WhatsApp-Nachricht

```
⚽ SPORTWETTEN KI — 26.03.2026
💰 Aktuelles Kapital: 1.032,50€
━━━━━━━━━━━━━━━━━━━━

#1 — Bayern München vs Dortmund
🏆 Bundesliga  |  🕐 18:30
▶️ Tipp: Heimsieg  @  Quote 1.85
💵 Einsatz: 22.00€  |  Pot. Gewinn: +18.70€
📊 EV: +8.3%  |  🟢 Risiko: Niedrig
💡 Bayern überlegen zuhause, Dortmund in Formkrise

#2 — Real Madrid vs Atletico
🏆 La Liga  |  🕐 21:00
▶️ Tipp: Heimsieg  @  Quote 1.95
💵 Einsatz: 19.50€  |  Pot. Gewinn: +18.52€
📊 EV: +6.1%  |  🟡 Risiko: Mittel

━━━━━━━━━━━━━━━━━━━━
📱 http://dein-server:8000
🤖 Sportwetten KI Multi Agent
```

---

## 🚀 Setup

### 1. Auf IONOS deployen
```bash
git clone https://github.com/DEIN-NAME/betting-agent.git
cd betting-agent
bash setup_ionos.sh
```

### 2. API Keys in .env eintragen
```bash
nano .env
```

### 3. WhatsApp einrichten (2 Minuten!)
```
1. Speichere +34 644 59 91 23 als Kontakt "CallMeBot"
2. Sende WhatsApp: I allow callmebot to send me messages
3. Du bekommst deinen API Key (z.B. 1234567)
4. In .env eintragen:
   WHATSAPP_PHONE=4369912345678
   WHATSAPP_API_KEY=1234567
```

### 4. Google Drive einrichten
```bash
python setup_google_drive.py
```

### 5. Starten
```bash
sudo systemctl start betting-agent
```

### 6. WhatsApp testen
```bash
curl -X POST http://localhost:8000/api/whatsapp-test
```

---

## 📊 Excel Sheets

| Sheet | Inhalt |
|---|---|
| 📊 Empfehlungen | Alle Value Bets täglich |
| 🎯 Meine Wetten | Top 3 auto-eingetragen |
| 💰 Kapital | Kapitalverlauf |
| 📅 Wochenanalyse | KI-Wochenbericht |
| 🗓️ Monatsanalyse | KI-Monatsbericht |
| 📈 Statistik | ROI, Trefferquote |

---

## 🔄 Updates
```bash
git pull && sudo systemctl restart betting-agent
```

---

## ⚠️ Hinweise
- .env NIEMALS auf GitHub pushen
- CallMeBot: kostenlos, max. 50 Nachrichten/Tag
- Verantwortungsvoll wetten!
