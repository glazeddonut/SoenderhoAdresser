import httpx

DATAFORDELER_BASE = "https://services.datafordeler.dk/BBR/BBRPublic/1/rest"

# BBR building usage codes → classification
HELARSBUS_CODES = {"110", "120", "121", "122"}
FRITIDSHUS_CODES = {"510", "520"}


async def fetch_buildings(
    client: httpx.AsyncClient,
    adgangsadresse_id: str,
    username: str,
    password: str,
) -> list[dict]:
    response = await client.get(
        f"{DATAFORDELER_BASE}/bygning",
        params={
            "AdgangsadresseId": adgangsadresse_id,
            "username": username,
            "password": password,
            "format": "JSON",
        },
    )
    response.raise_for_status()
    return response.json()
