"""
Google Drive Agent — lädt Excel täglich in den Ordner 'Sportwetten durch KI Multi Agent'
Nutzt Google Drive API v3 mit Service Account oder OAuth2
"""
import os
import json
import httpx
from datetime import date, datetime

# Google Drive API via Service Account Token
GDRIVE_TOKEN_FILE = os.getenv("GDRIVE_TOKEN_FILE", "data/gdrive_token.json")
GDRIVE_FOLDER_NAME = "Sportwetten durch KI Multi Agent"
EXCEL_PATH = os.getenv("EXCEL_PATH", "data/wett_tracker.xlsx")

async def _get_access_token() -> str:
    """Liest den gespeicherten Access Token"""
    if not os.path.exists(GDRIVE_TOKEN_FILE):
        raise FileNotFoundError("Google Drive Token nicht gefunden. Bitte setup_google_drive.py ausführen!")
    with open(GDRIVE_TOKEN_FILE) as f:
        token_data = json.load(f)
    return token_data.get("access_token", "")

async def _refresh_token() -> str:
    """Erneuert den Access Token via Refresh Token"""
    if not os.path.exists(GDRIVE_TOKEN_FILE):
        raise FileNotFoundError("Token-Datei nicht gefunden!")
    with open(GDRIVE_TOKEN_FILE) as f:
        token_data = json.load(f)

    client_id = token_data.get("client_id")
    client_secret = token_data.get("client_secret")
    refresh_token = token_data.get("refresh_token")

    if not all([client_id, client_secret, refresh_token]):
        raise ValueError("Unvollständige Token-Daten")

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "https://oauth2.googleapis.com/token",
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
            }
        )
        if resp.status_code == 200:
            new_token = resp.json().get("access_token")
            token_data["access_token"] = new_token
            with open(GDRIVE_TOKEN_FILE, "w") as f:
                json.dump(token_data, f)
            return new_token
    raise Exception("Token-Erneuerung fehlgeschlagen")

async def _get_valid_token() -> str:
    """Holt einen gültigen Token (erneuert falls nötig)"""
    try:
        return await _refresh_token()
    except Exception:
        return await _get_access_token()

async def ordner_erstellen_oder_finden(token: str) -> str:
    """Findet oder erstellt den Google Drive Ordner"""
    headers = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient() as client:
        # Suchen
        resp = await client.get(
            "https://www.googleapis.com/drive/v3/files",
            headers=headers,
            params={
                "q": f"name='{GDRIVE_FOLDER_NAME}' and mimeType='application/vnd.google-apps.folder' and trashed=false",
                "fields": "files(id,name)",
            }
        )
        if resp.status_code == 200:
            files = resp.json().get("files", [])
            if files:
                return files[0]["id"]

        # Erstellen
        resp = await client.post(
            "https://www.googleapis.com/drive/v3/files",
            headers={**headers, "Content-Type": "application/json"},
            json={
                "name": GDRIVE_FOLDER_NAME,
                "mimeType": "application/vnd.google-apps.folder",
            }
        )
        if resp.status_code == 200:
            return resp.json()["id"]
    raise Exception("Ordner konnte nicht erstellt werden")

async def datei_hochladen(token: str, folder_id: str, datei_pfad: str, datei_name: str) -> str:
    """Lädt eine Datei in den Google Drive Ordner hoch (oder überschreibt sie)"""
    headers = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient(timeout=60) as client:
        # Prüfen ob Datei schon existiert
        resp = await client.get(
            "https://www.googleapis.com/drive/v3/files",
            headers=headers,
            params={
                "q": f"name='{datei_name}' and '{folder_id}' in parents and trashed=false",
                "fields": "files(id,name)",
            }
        )
        existing_id = None
        if resp.status_code == 200:
            files = resp.json().get("files", [])
            if files: existing_id = files[0]["id"]

        with open(datei_pfad, "rb") as f:
            datei_inhalt = f.read()

        mime = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

        if existing_id:
            # Update
            resp = await client.patch(
                f"https://www.googleapis.com/upload/drive/v3/files/{existing_id}",
                headers={**headers, "Content-Type": mime},
                content=datei_inhalt,
                params={"uploadType": "media"},
            )
        else:
            # Neu hochladen (multipart)
            import io
            boundary = "boundary_sportwetten_agent"
            meta = json.dumps({"name": datei_name, "parents": [folder_id]})
            body = (
                f"--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n"
                f"{meta}\r\n"
                f"--{boundary}\r\nContent-Type: {mime}\r\n\r\n"
            ).encode() + datei_inhalt + f"\r\n--{boundary}--".encode()

            resp = await client.post(
                "https://www.googleapis.com/upload/drive/v3/files",
                headers={**headers, "Content-Type": f"multipart/related; boundary={boundary}"},
                content=body,
                params={"uploadType": "multipart"},
            )

        if resp.status_code in [200, 201]:
            file_id = resp.json().get("id", "")
            print(f"  ✓ Google Drive: '{datei_name}' hochgeladen (ID: {file_id})")
            return file_id
        else:
            raise Exception(f"Upload-Fehler: {resp.status_code} — {resp.text}")

async def excel_zu_drive_hochladen() -> bool:
    """Hauptfunktion: Lädt die Excel-Datei in Google Drive hoch"""
    if not os.path.exists(EXCEL_PATH):
        print("  ⚠ Excel-Datei nicht gefunden, überspringe Drive-Upload")
        return False
    try:
        token = await _get_valid_token()
        folder_id = await ordner_erstellen_oder_finden(token)
        heute = date.today().strftime("%Y-%m-%d")
        datei_name = f"Sportwetten_Tracker_{heute}.xlsx"
        await datei_hochladen(token, folder_id, EXCEL_PATH, "Sportwetten_Tracker_Aktuell.xlsx")
        await datei_hochladen(token, folder_id, EXCEL_PATH, datei_name)
        print(f"  ✓ Excel in Google Drive Ordner '{GDRIVE_FOLDER_NAME}' gespeichert")
        return True
    except FileNotFoundError as e:
        print(f"  ⚠ Google Drive nicht eingerichtet: {e}")
        return False
    except Exception as e:
        print(f"  ✗ Google Drive Fehler: {e}")
        return False
