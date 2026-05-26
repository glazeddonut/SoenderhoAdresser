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

from api.bbr import fetch_buildings
from api.dawa import fetch_addresses_in_polygon

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
        if str(b.get("byg021BygningensAnvendelse", "") or
               b.get("BYG_ANVEND_KODE", "")) in HELARSBUS_CODES | FRITIDSHUS_CODES
    ]
    candidates = residential if residential else buildings

    def area(b: dict) -> float:
        return (
            b.get("byg038SamletBygningsareal")
            or b.get("BEBO_ARL")
            or 0
        )

    return max(candidates, key=area)


def extract_building_data(building: dict) -> tuple[str | None, int | None, int | None, int | None]:
    """Return (anvend_kode, boligareal, bebygget_areal, opfoerelse_aar)."""
    code = (
        str(building.get("byg021BygningensAnvendelse") or building.get("BYG_ANVEND_KODE") or "")
        or None
    )
    boligareal = building.get("byg038SamletBygningsareal") or building.get("BEBO_ARL")
    bebygget = building.get("byg041BebyggetAreal") or building.get("BYG_BEBYGGET_ARL")
    aar = building.get("byg_opforelsesaar") or building.get("OPFOERELSE_AAR")
    return code, boligareal, bebygget, aar


@app.get("/api/config")
async def get_config():
    """Returns whether BBR API key is configured."""
    return {"bbr_enabled": bool(os.getenv("DATAFORDELER_API_KEY"))}


@app.post("/api/search")
async def search(request: SearchRequest):
    cache_key = polygon_cache_key(request.polygon)
    if cache_key in _cache:
        logger.info("Cache hit (%s)", cache_key[:8])
        return _cache[cache_key]

    api_key = os.getenv("DATAFORDELER_API_KEY", "")
    bbr_enabled = bool(api_key)

    async with httpx.AsyncClient(timeout=60.0) as client:
        logger.info("Henter adresser fra DAWA...")
        addresses = await fetch_addresses_in_polygon(client, request.polygon)
        logger.info("Fandt %d adresser%s", len(addresses),
                    " — beriger med BBR-data..." if bbr_enabled else " (ingen BBR API-nøgle)")

        semaphore = asyncio.Semaphore(20)

        async def enrich(addr: dict) -> dict:
            building: dict = {}
            if bbr_enabled:
                async with semaphore:
                    try:
                        buildings = await fetch_buildings(
                            client, addr["adgangsadresseid"], api_key
                        )
                        building = primary_building(buildings)
                    except Exception as exc:
                        logger.debug("BBR fejl for %s: %s", addr["adgangsadresseid"], exc)

            code, boligareal, bebygget, aar = extract_building_data(building)
            return {
                "id": addr["id"],
                "adresse": addr.get("betegnelse", ""),
                "vejnavn": addr.get("vejnavn", ""),
                "husnr": addr.get("husnr", ""),
                "x": addr.get("x"),
                "y": addr.get("y"),
                "type": classify(code) if code else "ukendt",
                "anvend_kode": code,
                "boligareal": boligareal,
                "bebygget_areal": bebygget,
                "opfoerelse_aar": aar,
            }

        results = list(await asyncio.gather(*[enrich(a) for a in addresses]))

    logger.info("Færdig: %d resultater cachet", len(results))
    _cache[cache_key] = results
    return results


@app.get("/")
async def read_index():
    return FileResponse("static/index.html")


app.mount("/static", StaticFiles(directory="static"), name="static")
