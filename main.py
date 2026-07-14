import asyncio
import hashlib
import json
import logging
import os

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.responses import Response

from api.bbr import fetch_buildings
from api.boligsiden import build_url, check_for_sale
from api.dawa import fetch_addresses_in_polygon
from api.fbb import fetch_listed_buildings
from api.water import WaterIndex, fetch_water_bodies

DAWA_BASE = "https://api.dataforsyningen.dk"

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI(title="Sønderho Adresser")

_cache: dict[str, list[dict]] = {}

HELARSBUS_CODES = {"110", "120", "121", "122"}
FRITIDSHUS_CODES = {"510", "520"}


class SearchRequest(BaseModel):
    polygon: list[list[float]]


def polygon_cache_key(polygon: list[list[float]]) -> str:
    return hashlib.md5(json.dumps(polygon, sort_keys=True).encode()).hexdigest()


def classify(code: str | None) -> str:
    if code in HELARSBUS_CODES:
        return "helårshus"
    if code in FRITIDSHUS_CODES:
        return "fritidshus"
    return "andet"


def primary_building(buildings: list[dict]) -> dict:
    if not buildings:
        return {}
    residential = [
        b for b in buildings
        if str(b.get("byg021BygningensAnvendelse", "")) in HELARSBUS_CODES | FRITIDSHUS_CODES
    ]
    candidates = residential if residential else buildings
    return max(candidates, key=lambda b: b.get("byg038SamletBygningsareal") or 0)


def extract_building_data(building: dict) -> tuple:
    """Return (anvend_kode, boligareal, bebygget_areal, opfoerelse_aar, id_lokalId, tagmateriale)."""
    code = str(building.get("byg021BygningensAnvendelse") or "") or None
    boligareal = building.get("byg039BygningensSamledeBoligAreal")
    bebygget = building.get("byg041BebyggetAreal")
    aar = building.get("byg026Opførelsesår")
    id_lokal = building.get("id_lokalId")
    tagmateriale = str(building.get("byg033Tagdækningsmateriale") or "") or None
    return code, boligareal, bebygget, aar, id_lokal, tagmateriale


@app.get("/api/config")
async def get_config():
    """Returns whether BBR credentials are configured."""
    has_creds = bool(os.getenv("DATAFORDELER_USER") and os.getenv("DATAFORDELER_PASSWORD"))
    return {"bbr_enabled": has_creds}


@app.post("/api/search")
async def search(request: SearchRequest):
    cache_key = polygon_cache_key(request.polygon)
    if cache_key in _cache:
        logger.info("Cache hit (%s)", cache_key[:8])
        return _cache[cache_key]

    df_user = os.getenv("DATAFORDELER_USER", "")
    df_pass = os.getenv("DATAFORDELER_PASSWORD", "")
    bbr_enabled = bool(df_user and df_pass)

    async def safe_fetch_listed(client: httpx.AsyncClient, polygon: list) -> set:
        try:
            return await fetch_listed_buildings(client, polygon)
        except Exception as exc:
            logger.warning("FBB fejl: %s", exc)
            return set()

    async def safe_fetch_water(client: httpx.AsyncClient, polygon: list) -> list:
        try:
            return await fetch_water_bodies(client, polygon)
        except Exception as exc:
            logger.warning("Vanddata-fejl: %s", exc)
            return []

    async with httpx.AsyncClient(timeout=120.0) as client:
        logger.info("Henter adresser fra DAWA, fredningsdata fra FBB og vanddata fra OSM...")
        addresses, listed_buildings, water_lines = await asyncio.gather(
            fetch_addresses_in_polygon(client, request.polygon),
            safe_fetch_listed(client, request.polygon),
            safe_fetch_water(client, request.polygon),
        )
        logger.info("Fandt %d adresser, %d fredede bygninger%s",
                    len(addresses), len(listed_buildings),
                    " — beriger med BBR-data..." if bbr_enabled else " (ingen BBR-credentials)")

        semaphore = asyncio.Semaphore(20)

        async def enrich(addr: dict) -> dict:
            building: dict = {}
            if bbr_enabled:
                async with semaphore:
                    try:
                        buildings = await fetch_buildings(
                            client, addr["adgangsadresseid"], df_user, df_pass
                        )
                        building = primary_building(buildings)
                    except Exception as exc:
                        logger.debug("BBR fejl for %s: %s", addr["adgangsadresseid"], exc)

            code, boligareal, bebygget, aar, id_lokal, tagmateriale = extract_building_data(building)
            return {
                "id": addr["id"],
                "adresse": addr.get("betegnelse", ""),
                "vejnavn": addr.get("vejnavn", ""),
                "husnr": addr.get("husnr", ""),
                "postnr": addr.get("postnr", ""),
                "postnrnavn": addr.get("postnrnavn", ""),
                "x": addr.get("x"),
                "y": addr.get("y"),
                "type": classify(code) if code else "ukendt",
                "anvend_kode": code,
                "boligareal": boligareal,
                "bebygget_areal": bebygget,
                "opfoerelse_aar": aar,
                "tagmateriale": tagmateriale,
                "fredet": bool(id_lokal and id_lokal in listed_buildings),
                "vand_afstand": None,
            }

        results = list(await asyncio.gather(*[enrich(a) for a in addresses]))

    if water_lines and results:
        lat0 = sum(p[1] for p in request.polygon) / len(request.polygon)
        index = WaterIndex(water_lines, lat0)
        for r in results:
            if r["x"] is not None and r["y"] is not None:
                d = index.distance(r["x"], r["y"])
                r["vand_afstand"] = round(d) if d is not None else None
        logger.info("Beregnede afstand til vand for %d adresser (%d vandsegmenter)",
                    len(results), len(index.segments))

    logger.info("Færdig: %d resultater cachet", len(results))
    _cache[cache_key] = results
    return results


@app.get("/api/postnummer/{nr}")
async def postnummer_area(nr: str):
    """Return the geographic extent (bbox + center) of a postal code's addresses."""
    if not (nr.isdigit() and len(nr) == 4):
        return JSONResponse({"error": "Ugyldigt postnummer"}, status_code=400)

    async with httpx.AsyncClient(timeout=30.0) as client:
        meta = await client.get(f"{DAWA_BASE}/postnumre/{nr}")
        if meta.status_code != 200:
            return JSONResponse({"error": "Postnummer ikke fundet"}, status_code=404)
        navn = meta.json().get("navn", "")

        # Addresses come back in id order (spatially unsorted), so a few thousand
        # are enough to determine the extent. DAWA also rejects deep paging, so cap.
        addresses: list[dict] = []
        for page in range(1, 26):
            resp = await client.get(
                f"{DAWA_BASE}/adresser",
                params={"postnr": nr, "struktur": "mini", "per_side": 1000, "side": page},
            )
            if resp.status_code != 200:
                break
            batch = resp.json()
            if not batch:
                break
            addresses.extend(batch)
            if len(batch) < 1000:
                break

    xs = [a["x"] for a in addresses if a.get("x") is not None]
    ys = [a["y"] for a in addresses if a.get("y") is not None]
    if not xs or not ys:
        return JSONResponse({"error": "Ingen adresser i postnummeret"}, status_code=404)

    bbox = [min(xs), min(ys), max(xs), max(ys)]
    center = [(min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2]
    return {"nr": nr, "navn": navn, "bbox": bbox, "center": center, "antal": len(addresses)}


@app.get("/api/boligsiden")
async def boligsiden_check(vejnavn: str, husnr: str, postnr: str, postnrnavn: str):
    """Check if an address is currently for sale on boligsiden.dk."""
    url = build_url(vejnavn, husnr, postnr, postnrnavn)
    return await asyncio.get_event_loop().run_in_executor(None, check_for_sale, url)


@app.get("/")
async def read_index():
    return FileResponse(
        "static/index.html", headers={"Cache-Control": "no-cache, must-revalidate"}
    )


class NoCacheStaticFiles(StaticFiles):
    """Serve static files with no-cache so the browser always revalidates.

    Avoids stale app.js/style.css after edits (otherwise a hard refresh is needed).
    """

    def file_response(self, *args, **kwargs) -> Response:
        response = super().file_response(*args, **kwargs)
        response.headers["Cache-Control"] = "no-cache, must-revalidate"
        return response


app.mount("/static", NoCacheStaticFiles(directory="static"), name="static")
