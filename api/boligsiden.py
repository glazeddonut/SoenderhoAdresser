import re
from curl_cffi import requests as cffi_requests


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
    Fetch a boligsiden.dk address page using a browser TLS fingerprint
    (curl_cffi / Chrome impersonation) to bypass Cloudflare.
    Returns {"til_salg": bool, "url": str} or {"error": str}.
    """
    try:
        resp = cffi_requests.get(url, impersonate="chrome", timeout=15)
        if resp.status_code != 200:
            return {"error": f"HTTP {resp.status_code}", "url": url}

        title_m = re.search(r"<title>(.*?)</title>", resp.text)
        title = title_m.group(1) if title_m else ""
        til_salg = title.lower().startswith("til salg")
        return {"til_salg": til_salg, "titel": title, "url": url}
    except Exception as exc:
        return {"error": str(exc), "url": url}
