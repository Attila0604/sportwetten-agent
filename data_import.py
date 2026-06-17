"""
data_import.py
──────────────
Holt historische Spielergebnisse von football-data.org (Gratis-Tier)
und schreibt sie in die Supabase-Tabelle `matches`.

- Reine httpx-Calls -> keine neue Dependency (httpx hast du schon).
- Upsert per Supabase REST-API: doppelte Spiele werden ignoriert.
- Drosselung auf <10 Calls/Min (Gratis-Limit von football-data.org).

Vorbereitung (einmalig):
  1. Auf football-data.org/client/register kostenlos registrieren -> API-Token.
  2. Railway Env-Vars: FOOTBALL_DATA_KEY, SUPABASE_URL, SUPABASE_KEY.
"""

import os
import asyncio
import httpx

FD_KEY       = os.getenv("FOOTBALL_DATA_KEY", "")
SUPABASE_URL = os.getenv("SUPABASE_URL", "").rstrip("/")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")

FD_BASE = "https://api.football-data.org/v4"

# Gratis-Ligen bei football-data.org (Code -> Klartext)
LIGEN = {
    # Top-5 (sehr scharf bepreist):
    "PL":  "Premier League",
    "BL1": "Bundesliga",
    "PD":  "La Liga",
    "SA":  "Serie A",
    "FL1": "Ligue 1",
    # Weichere Ligen (weniger scharf bepreist -> mögliche Edge-Quellen):
    "ELC": "Championship (England 2. Liga)",
    "DED": "Eredivisie (Niederlande)",
    "PPL": "Primeira Liga (Portugal)",
    "BSA": "Brasileirao (Brasilien)",
}


def _parse_matches(json_data: dict, liga_code: str, season: str) -> list:
    """Wandelt die football-data.org-Antwort in unsere Tabellen-Zeilen um."""
    zeilen = []
    for m in json_data.get("matches", []):
        if m.get("status") != "FINISHED":
            continue
        ft = (m.get("score", {}) or {}).get("fullTime", {}) or {}
        if ft.get("home") is None or ft.get("away") is None:
            continue
        zeilen.append({
            "league":     liga_code,
            "season":     season,
            "match_date": m["utcDate"][:10],
            "home":       m["homeTeam"]["name"],
            "away":       m["awayTeam"]["name"],
            "home_goals": ft["home"],
            "away_goals": ft["away"],
        })
    return zeilen


async def _hole_liga(client: httpx.AsyncClient, code: str, season: str) -> list:
    """Eine Liga + Saison von football-data.org laden."""
    url = f"{FD_BASE}/competitions/{code}/matches"
    resp = await client.get(url, params={"season": season},
                            headers={"X-Auth-Token": FD_KEY}, timeout=30)
    if resp.status_code != 200:
        print(f"  ⚠ {code} {season}: HTTP {resp.status_code} – übersprungen")
        return []
    zeilen = _parse_matches(resp.json(), code, season)
    print(f"  ✅ {LIGEN.get(code, code)} {season}: {len(zeilen)} Spiele")
    return zeilen


async def _schreibe_supabase(client: httpx.AsyncClient, zeilen: list) -> int:
    """Upsert nach Supabase. Doppelte (gleiche Liga/Datum/Teams) werden gemerged."""
    if not zeilen:
        return 0
    url = f"{SUPABASE_URL}/rest/v1/matches"
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates,return=minimal",
    }
    resp = await client.post(url, json=zeilen, headers=headers, timeout=30)
    if resp.status_code not in (200, 201, 204):
        print(f"  ⚠ Supabase-Schreiben fehlgeschlagen: HTTP {resp.status_code} {resp.text[:200]}")
        return 0
    return len(zeilen)


async def importiere(seasons: list = None, ligen: list = None) -> dict:
    """
    Hauptfunktion. Importiert alle angegebenen Ligen/Saisons.
    seasons: z.B. ["2023", "2024"]  (Startjahr der Saison)
    ligen:   z.B. ["PL", "BL1"]      (None = alle aus LIGEN)
    """
    if not (FD_KEY and SUPABASE_URL and SUPABASE_KEY):
        return {"ok": False, "error": "Env-Vars fehlen (FOOTBALL_DATA_KEY / SUPABASE_URL / SUPABASE_KEY)"}

    seasons = seasons or ["2023", "2024"]
    codes   = ligen or list(LIGEN.keys())
    gesamt  = 0

    async with httpx.AsyncClient() as client:
        for code in codes:
            for season in seasons:
                zeilen = await _hole_liga(client, code, season)
                gesamt += await _schreibe_supabase(client, zeilen)
                await asyncio.sleep(6.5)   # Gratis-Limit: <10 Calls/Min

    print(f"\n✅ Import fertig: {gesamt} Spiele in Supabase.")
    return {"ok": True, "importiert": gesamt}


if __name__ == "__main__":
    asyncio.run(importiere())
