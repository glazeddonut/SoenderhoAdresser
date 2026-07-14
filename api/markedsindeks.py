"""Markedsprisudvikling for Fanø fra Finans Danmarks Boligmarkedsstatistik (RKR).

Hentes via Boligas API (`statistics/rkrsearch`), som eksponerer Finans Danmark-data
pr. område. `areaid=26720` = Fanø, `datatype=0` = gennemsnitlig kvadratmeterpris,
`rkrpropertytype`: 0 = parcel-/rækkehuse (→ helårshus), 2 = fritidshuse. Serien er
kvartalsvis og Fanø-specifik — bruges til at fremskrive hvert historisk salg fra dets
salgskvartal til i dag i stedet for en flad, konstant vækstrate.

Cloudflare-beskyttet → hentes med curl_cffi (Chrome-impersonation) + Referer/Origin.
"""
from curl_cffi import requests as cffi_requests

RKR_SEARCH = "https://api.boliga.dk/api/v2/statistics/rkrsearch"
_AREA_FANOE = 26720
# BBR-boligtype → Finans Danmarks rkrpropertytype
_PROPERTY_TYPE = {"helårshus": 0, "fritidshus": 2}
_HEADERS = {
    "Referer": "https://www.boliga.dk/",
    "Origin": "https://www.boliga.dk",
    "Accept": "application/json",
}


def _quarter(datestr: str) -> str:
    y, m = int(datestr[:4]), int(datestr[5:7])
    return f"{y}K{(m - 1) // 3 + 1}"


def fetch_market_index() -> dict[str, dict[str, float]]:
    """Returnér {"helårshus": {"YYYYKQ": kr/m²}, "fritidshus": {...}} for Fanø (synkront)."""
    series: dict[str, dict[str, float]] = {}
    for typ, ptype in _PROPERTY_TYPE.items():
        resp = cffi_requests.get(
            RKR_SEARCH,
            params={"areaid": _AREA_FANOE, "datatype": 0, "rkrpropertytype": ptype},
            impersonate="chrome",
            headers=_HEADERS,
            timeout=25,
        )
        resp.raise_for_status()
        s: dict[str, float] = {}
        for row in resp.json():
            value = row.get("value")
            if value:  # spring 0/None-kvartaler over
                s[_quarter(row["date"])] = value
        series[typ] = s
    return series


def index_at(series: dict[str, float], datestr: str) -> float | None:
    """Indeksværdi for salgsdatoens kvartal (falder tilbage til nærmeste tidligere kvartal)."""
    if not series:
        return None
    q = _quarter(datestr)
    if q in series:
        return series[q]
    keys = sorted(series)  # "YYYYKQ" sorterer kronologisk som streng
    earlier = [k for k in keys if k <= q]
    return series[earlier[-1]] if earlier else series[keys[0]]


def index_now(series: dict[str, float]) -> float | None:
    """Seneste (nyeste) indeksværdi."""
    if not series:
        return None
    return series[sorted(series)[-1]]


def index_cagr(series: dict[str, float], years: int = 5) -> float:
    """Årlig vækst i indekset over de seneste ~N år (kun til visning)."""
    if len(series) < 2:
        return 0.0
    keys = sorted(series)
    latest = keys[-1]
    now_v = series[latest]
    target = f"{int(latest[:4]) - years}{latest[4:]}"
    earlier = [k for k in keys if k <= target] or [keys[0]]
    then_v = series[earlier[-1]]
    return (now_v / then_v) ** (1 / years) - 1 if then_v > 0 else 0.0
