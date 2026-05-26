import json

import httpx

DAWA_BASE = "https://api.dataforsyningen.dk"


async def fetch_addresses_in_polygon(
    client: httpx.AsyncClient, polygon: list[list[float]]
) -> list[dict]:
    # DAWA expects a closed GeoJSON ring wrapped in an outer array: [[[lon,lat], ...]]
    ring = polygon if polygon[0] == polygon[-1] else polygon + [polygon[0]]
    geo_polygon = json.dumps([ring], separators=(",", ":"))
    all_addresses: list[dict] = []
    page = 1
    while True:
        response = await client.get(
            f"{DAWA_BASE}/adresser",
            params={
                "polygon": geo_polygon,
                "struktur": "mini",
                "per_side": 1000,
                "side": page,
            },
        )
        response.raise_for_status()
        data = response.json()
        if not data:
            break
        all_addresses.extend(data)
        if len(data) < 1000:
            break
        page += 1
    return all_addresses
