import httpx

DATAFORDELER_BASE = "https://services.datafordeler.dk/BBR/BBRPublic/1/rest"


async def fetch_buildings(
    client: httpx.AsyncClient,
    adgangsadresse_id: str,
    username: str,
    password: str,
) -> list[dict]:
    # BBR calls DAWA's adgangsadresseid "husnummer"
    response = await client.get(
        f"{DATAFORDELER_BASE}/bygning",
        params={
            "husnummer": adgangsadresse_id,
            "username": username,
            "password": password,
            "format": "JSON",
        },
    )
    response.raise_for_status()
    return response.json()
