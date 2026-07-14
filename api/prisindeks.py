"""Markedspris-estimat ud fra tidligere frie handler (Boligsiden salgsregistreringer).

Model: log-lineær trend af kr/m² over tid → fremskriv hver handel til i dag →
områdets kr/m² = median af de fremskrevne værdier. Estimat pr. bolig kombinerer
områdets kr/m² × boligens m² med boligens egen sidste frie handel (fremskrevet).
Familiehandler (og auktioner uden areal) indgår ikke — de filtreres fra af kalderen.
"""
import math
from datetime import datetime

# Kun handler nyere end dette antal år bruges til trend/indeks (holder det relevant).
MAX_AGE_YEARS = 25
# Klamp årlig prisvækst til et fornuftigt interval (robusthed mod små/støjende samples).
MIN_GROWTH, MAX_GROWTH = -0.03, 0.15


def _year_frac(datestr: str) -> float:
    y, m, d = (int(p) for p in datestr[:10].split("-"))
    return y + (m - 1) / 12 + (d - 1) / 365


def _median(xs: list[float]) -> float | None:
    s = sorted(xs)
    n = len(s)
    if n == 0:
        return None
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2


def _now_frac() -> float:
    n = datetime.now()
    return n.year + (n.month - 1) / 12


def build_model(sales: list[dict]) -> dict:
    """sales: [{price, area, date}]. Returnerer områdets prismodel."""
    now = _now_frac()
    points: list[tuple[float, float]] = []
    for s in sales:
        price, area, dt = s.get("price"), s.get("area"), s.get("date")
        if not price or not area or not dt:
            continue
        year = _year_frac(dt)
        if now - year > MAX_AGE_YEARS:
            continue
        ppa = price / area
        if ppa > 0:
            points.append((year, math.log(ppa)))

    n = len(points)
    if n == 0:
        return {"n": 0, "kr_m2_i_dag": None, "aarlig_vaekst": 0.0, "b": 0.0, "now": now}

    b = 0.0
    growth = 0.0
    if n >= 4:  # kræv nok punkter til en meningsfuld trend
        xs = [x for x, _ in points]
        ys = [y for _, y in points]
        mx, my = sum(xs) / n, sum(ys) / n
        sxx = sum((x - mx) ** 2 for x in xs)
        sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
        if sxx > 0:
            growth = max(MIN_GROWTH, min(MAX_GROWTH, math.exp(sxy / sxx) - 1))
            b = math.log(1 + growth)

    adjusted = [math.exp(y + b * (now - x)) for x, y in points]
    kr = _median(adjusted)
    return {
        "n": n,
        "kr_m2_i_dag": round(kr) if kr else None,
        "aarlig_vaekst": round(growth, 4),
        "b": b,
        "now": now,
    }


def estimate(model: dict, m2: float | None, own_sales: list[dict]) -> dict:
    """Estimér markedspris for én bolig. own_sales: boligens egne frie handler [{price, date}]."""
    b, now, kr = model["b"], model["now"], model["kr_m2_i_dag"]

    est_areal = round(kr * m2) if (kr and m2) else None

    est_egen = None
    seneste = None
    valid = [s for s in own_sales if s.get("price") and s.get("date")]
    if valid:
        last = max(valid, key=lambda s: s["date"])
        seneste = {"pris": last["price"], "dato": last["date"][:10]}
        est_egen = round(last["price"] * math.exp(b * (now - _year_frac(last["date"]))))

    if est_egen and est_areal:
        # Vægt den nyere kilde højst: en frisk egen-handel vejer op til 0,7.
        age = now - _year_frac(last["date"])
        w = max(0.2, min(0.7, 1 - age / 20))
        marked = round(w * est_egen + (1 - w) * est_areal)
    else:
        marked = est_egen or est_areal

    return {
        "marked": marked,
        "marked_areal": est_areal,
        "marked_egen": est_egen,
        "seneste_salg": seneste,
        "antal_frie_salg": len(valid),
    }
