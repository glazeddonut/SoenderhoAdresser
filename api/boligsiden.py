import json
import re

import httpx
from curl_cffi import requests as cffi_requests

BOLIGSIDEN_API = "https://api.boligsiden.dk"


async def fetch_registrations(client: httpx.AsyncClient, address_id: str) -> dict | None:
    """Hent salgsregistreringer + offentlig vurdering for én adresse fra Boligsidens API.

    address_id er DAWA's enhedsadresse-id (matcher Boligsidens addressID).
    Returnerer None hvis adressen ikke findes hos Boligsiden.
    """
    resp = await client.get(
        f"{BOLIGSIDEN_API}/addresses/{address_id}",
        headers={"User-Agent": "SoenderhoAdresser/1.0"},
    )
    if resp.status_code != 200:
        return None
    data = resp.json()
    registrations = [
        {
            "amount": r.get("amount"),
            "area": r.get("area"),
            "date": r.get("date"),
            "perAreaPrice": r.get("perAreaPrice"),
            "type": r.get("type"),  # normal | family | other
        }
        for r in data.get("registrations", [])
    ]
    return {
        "registrations": registrations,
        "latestValuation": data.get("latestValuation"),
        "livingArea": data.get("livingArea"),
    }


def build_url(vejnavn: str, husnr: str, postnr: str, postnrnavn: str) -> str:
    def slug(s: str) -> str:
        s = str(s or "").lower()
        s = s.replace("æ", "ae").replace("ø", "oe").replace("å", "aa")
        s = re.sub(r"\s+", "-", s)
        s = re.sub(r"[^a-z0-9-]", "", s)
        s = re.sub(r"-+", "-", s)
        return s.strip("-")

    parts = "-".join(slug(x) for x in [vejnavn, husnr, postnr, postnrnavn])
    return f"https://www.boligsiden.dk/adresse/{parts}"


def check_for_sale(url: str) -> dict:
    """
    Fetch a boligsiden.dk address page using Chrome TLS-fingerprint impersonation
    (curl_cffi) to bypass Cloudflare. Detects active for-sale status via page
    title and extracts asking price from JSON-LD schema.org Product/Offer data.
    """
    try:
        resp = cffi_requests.get(url, impersonate="chrome", timeout=15)
        if resp.status_code != 200:
            return {"error": f"HTTP {resp.status_code}", "url": url}

        text = resp.text

        # Active listing: title starts with "Til salg:"
        title_m = re.search(r"<title>(.*?)</title>", text)
        title = title_m.group(1) if title_m else ""
        til_salg = title.lower().startswith("til salg")

        # Extract asking price from schema.org Product → Offer JSON-LD
        pris: int | None = None
        if til_salg:
            for raw in re.findall(
                r'<script type="application/ld\+json">(.*?)</script>', text, re.DOTALL
            ):
                try:
                    data = json.loads(raw)
                    items = data if isinstance(data, list) else [data]
                    for item in items:
                        if not isinstance(item, dict):
                            continue
                        if item.get("@type") == "Product":
                            offers = item.get("offers", {})
                            if isinstance(offers, dict):
                                p = offers.get("price")
                                if p is not None:
                                    pris = int(p)
                                    break
                    if pris is not None:
                        break
                except Exception:
                    pass

        return {"til_salg": til_salg, "pris": pris, "url": url}
    except Exception as exc:
        return {"error": str(exc), "url": url}
