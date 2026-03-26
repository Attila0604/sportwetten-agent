"""
Google Drive Einrichtung — Einmal ausführen!
Führe aus: python setup_google_drive.py

Danach funktioniert der automatische Upload in:
"Sportwetten durch KI Multi Agent" Ordner in Google Drive
"""
import json
import os
import webbrowser
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
import urllib.request
import urllib.parse

TOKEN_FILE = "data/gdrive_token.json"

print("=" * 60)
print("🔑 Google Drive Einrichtung")
print("=" * 60)
print()
print("SCHRITT 1: Google Cloud Console")
print("-" * 40)
print("1. Gehe zu: https://console.cloud.google.com")
print("2. Erstelle ein neues Projekt: 'Sportwetten Agent'")
print("3. Aktiviere die 'Google Drive API'")
print("4. Gehe zu 'APIs & Dienste' → 'Anmeldedaten'")
print("5. Erstelle 'OAuth 2.0-Client-ID' → Typ: 'Desktop-App'")
print("6. Lade die JSON-Datei herunter")
print()

client_id = input("Client ID (aus der JSON): ").strip()
client_secret = input("Client Secret (aus der JSON): ").strip()

if not client_id or not client_secret:
    print("❌ Client ID und Secret sind erforderlich!")
    exit(1)

# OAuth2 Flow
REDIRECT_URI = "http://localhost:8080"
SCOPE = "https://www.googleapis.com/auth/drive.file"

auth_url = (
    f"https://accounts.google.com/o/oauth2/v2/auth"
    f"?client_id={client_id}"
    f"&redirect_uri={REDIRECT_URI}"
    f"&response_type=code"
    f"&scope={urllib.parse.quote(SCOPE)}"
    f"&access_type=offline"
    f"&prompt=consent"
)

print()
print("SCHRITT 2: Google-Konto autorisieren")
print("-" * 40)
print("Öffne diesen Link in deinem Browser:")
print()
print(auth_url)
print()

# Versuche Browser zu öffnen
try:
    webbrowser.open(auth_url)
    print("(Browser wurde automatisch geöffnet)")
except Exception:
    pass

# Lokaler Server für Callback
auth_code = None

class CallbackHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        global auth_code
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        if "code" in params:
            auth_code = params["code"][0]
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"""
<html><body style="font-family:Arial;text-align:center;padding:50px;background:#0d1117;color:white">
<h2 style="color:#2ecc71">&#x2705; Autorisierung erfolgreich!</h2>
<p>Du kannst dieses Fenster jetzt schlie&#xDF;en.</p>
</body></html>""")
    def log_message(self, *args): pass

print("Warte auf Autorisierung...")
server = HTTPServer(("localhost", 8080), CallbackHandler)
server.handle_request()

if not auth_code:
    print("❌ Kein Autorisierungscode erhalten!")
    exit(1)

print("✅ Autorisierungscode erhalten!")

# Token Exchange
data = urllib.parse.urlencode({
    "code": auth_code,
    "client_id": client_id,
    "client_secret": client_secret,
    "redirect_uri": REDIRECT_URI,
    "grant_type": "authorization_code",
}).encode()

req = urllib.request.Request(
    "https://oauth2.googleapis.com/token",
    data=data,
    headers={"Content-Type": "application/x-www-form-urlencoded"},
)

try:
    with urllib.request.urlopen(req) as resp:
        token_data = json.loads(resp.read())
    token_data["client_id"] = client_id
    token_data["client_secret"] = client_secret

    os.makedirs("data", exist_ok=True)
    with open(TOKEN_FILE, "w") as f:
        json.dump(token_data, f, indent=2)

    print()
    print("=" * 60)
    print("✅ GOOGLE DRIVE ERFOLGREICH EINGERICHTET!")
    print("=" * 60)
    print()
    print(f"Token gespeichert in: {TOKEN_FILE}")
    print()
    print("📁 Excel wird täglich hochgeladen in:")
    print("   'Sportwetten durch KI Multi Agent'")
    print()
    print("Du kannst jetzt das System starten:")
    print("   sudo systemctl start betting-agent")
    print("=" * 60)

except Exception as e:
    print(f"❌ Fehler beim Token-Exchange: {e}")
    exit(1)
