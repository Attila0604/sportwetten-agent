import httpx
import os
from datetime import datetime, timezone, timedelta

ODDSPAPI_KEY = os.getenv("ODDSPAPI_KEY")
BASE_URL     = "https://api.oddspapi.io/v4"

STUNDEN_VORAUS = int(os.getenv("STUNDEN_VORAUS", "24"))

TOURNAMENT_IDS = os.getenv("TOURNAMENT_IDS",
    "17,8,572,23,679,34,13,35,572,10,42"
)

# Bookmaker-Liste – je mehr, desto besser der Konsens
BOOKMAKERS = os.getenv("BOOKMAKERS",
    "pinnacle,bet365,unibet,bwin,williamhill"
).split(",")


async def fetch_odds_for_bookmaker(client: httpx.AsyncClient, bookmaker: str) -> list:
    """Holt Quoten für EINEN Buchmacher (API-Requirement)"""
    try:
        resp = await client.get(
            f"{BASE_URL}/odds-by-tournaments",
            params={
                "apiKey":        ODDSPAPI_KEY,
                "tournamentIds": TOURNAMENT_IDS,
                "oddsFormat":    "decimal",
                "bookmaker":     bookmaker.strip(),  # ← Pflichtfeld!
            },
            timeout=20,
        )
        if resp.status_code == 200:
            return resp.json()
        else:
            print(f"  OddsPapi Fehler [{bookmaker}]: {resp.status_code} - {resp.text[:200]}")
            return []
    except Exception as e:
        print(f"  OddsPapi Fetch Fehler [{bookmaker}]: {e}")
        return []


async def fetch_fixtures_with_odds() -> list:
    """
    Holt Quoten von mehreren Buchmachers (je 1 Request pro Bookie)
    und merged die bookmakerOdds in eine kombinierte Fixture-Liste.
    """
    # fixture_id → merged fixture dict
    merged: dict[str, dict] = {}

    async with httpx.AsyncClient() as client:
        for bookmaker in BOOKMAKERS:
            fixtures = await fetch_odds_for_bookmaker(client, bookmaker)
            for fixture in fixtures:
                fid = fixture.get("fixtureId") or fixture.get("id")
                if not fid:
                    continue

                if fid not in merged:
                    # Erste Begegnung mit diesem Fixture → übernehmen
                    merged[fid] = fixture
                    if "bookmakerOdds" not in merged[fid]:
                        merged[fid]["bookmakerOdds"] = {}
                else:
                    # Fixture existiert schon → nur bookmakerOdds ergänzen
                    if "bookmakerOdds" not in merged[fid]:
                        merged[fid]["bookmakerOdds"] = {}

                # bookmakerOdds aus dieser Antwort reinmergen
                bookie_odds = fixture.get("bookmakerOdds", {})
                merged[fid]["bookmakerOdds"].update(bookie_odds)

    result = list(merged.values())
    print(f"  → {len(result)} unique Fixtures von {len(BOOKMAKERS)} Buchmachers gemergt")
    return result


# --- Rest bleibt unverändert ---

def ist_in_naechsten_stunden(start_time: str, stunden: int = 24) -> bool:
    try:
        dt    = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
        jetzt = datetime.now(timezone.utc)
        grenze = jetzt + timedelta(hours=stunden)
        return jetzt <= dt <= grenze
    except Exception:
        return False


def parse_oddspapi_game(fixture: dict) -> dict | None:
    start_time = fixture.get("startTime", "")
    if not ist_in_naechsten_stunden(start_time, STUNDEN_VORAUS):
        return None

    heim = fixture.get("participant1Name", "")
    gast = fixture.get("participant2Name", "")
    liga = fixture.get("tournamentName", "")

    if not heim or not gast:
        return None

    try:
        dt = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
        spiel_zeit = dt.strftime("%d.%m.%Y %H:%M")
    except Exception:
        spiel_zeit = start_time

    bookie_odds = fixture.get("bookmakerOdds", {})

    heim_quoten  = []
    unent_quoten = []
    gast_quoten  = []
    bookie_details = []

    for bookie_name, bookie_data in bookie_odds.items():
        if not bookie_data.get("bookmakerIsActive", True):
            continue

        markets    = bookie_data.get("markets", {})
        market_101 = markets.get("101", {})
        outcomes   = market_101.get("outcomes", {})

        q_heim  = outcomes.get("101", {}).get("players", {}).get("0", {}).get("price", 0)
        q_unent = outcomes.get("102", {}).get("players", {}).get("0", {}).get("price", 0)
        q_gast  = outcomes.get("103", {}).get("players", {}).get("0", {}).get("price", 0)

        if q_heim > 1 and q_unent > 1 and q_gast > 1:
            heim_quoten.append(q_heim)
            unent_quoten.append(q_unent)
            gast_quoten.append(q_gast)
            bookie_details.append({
                "name":                bookie_name,
                "quote_heim":          q_heim,
                "quote_unentschieden": q_unent,
                "quote_gast":          q_gast,
            })

    if len(heim_quoten) < 3:
        return None

    konsens_heim  = round(sum(heim_quoten) / len(heim_quoten), 3)
    konsens_unent = round(sum(unent_quoten) / len(unent_quoten), 3)
    konsens_gast  = round(sum(gast_quoten) / len(gast_quoten), 3)

    beste_heim  = max(heim_quoten)
    beste_unent = max(unent_quoten)
    beste_gast  = max(gast_quoten)
    bookie_heim  = bookie_details[heim_quoten.index(beste_heim)]["name"]
    bookie_unent = bookie_details[unent_quoten.index(beste_unent)]["name"]
    bookie_gast  = bookie_details[gast_quoten.index(beste_gast)]["name"]

    return {
        "id":   fixture.get("fixtureId"),
        "liga": liga,
        "heim": heim,
        "gast": gast,
        "zeit": spiel_zeit,

        "quote_heim":          konsens_heim,
        "quote_unentschieden": konsens_unent,
        "quote_gast":          konsens_gast,

        "beste_quote_heim":          beste_heim,
        "beste_quote_heim_bookie":   bookie_heim,
        "beste_quote_unentschieden": beste_unent,
        "beste_quote_unent_bookie":  bookie_unent,
        "beste_quote_gast":          beste_gast,
        "beste_quote_gast_bookie":   bookie_gast,

        "anzahl_buchmacher": len(heim_quoten),
        "alle_buchmacher":   bookie_details,
    }


async def get_parsed_odds() -> list:
    raw    = await fetch_fixtures_with_odds()
    parsed = []
    for fixture in raw:
        p = parse_oddspapi_game(fixture)
        if p:
            parsed.append(p)
    print(f"  → {len(parsed)} Spiele in den nächsten {STUNDEN_VORAUS}h ({len(raw)} gesamt)")
    return parsed


async def fetch_results(sport: str = None) -> list:
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{BASE_URL}/fixtures",
                params={
                    "apiKey":   ODDSPAPI_KEY,
                    "status":   "finished",
                    "daysFrom": 1,
                },
                timeout=15,
            )
            if resp.status_code == 200:
                return resp.json()
    except Exception as e:
        print(f"  Results Fehler: {e}")
    return []
