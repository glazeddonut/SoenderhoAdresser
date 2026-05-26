import httpx

DATAFORDELER_BASE = "https://services.datafordeler.dk/BBR/BBRPublic/1/rest"


async def fetch_buildings(
    client: httpx.AsyncClient,
    adgangsadresse_id: str,
    api_key: str,
) -> list[dict]:
    response = await client.get(
        f"{DATAFORDELER_BASE}/bygning",
        params={
            "AdgangsadresseId": adgangsadresse_id,
            "token": api_key,
            "format": "JSON",
        },
    )
    response.raise_for_status()
    return response.json()
