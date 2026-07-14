"""Markedspris-estimat ud fra tidligere frie handler (Boligsiden salgsregistreringer).

Hedonisk log-log model pr. boligtype:  ln(kr/m²) = niveau + b_tid·tid + b_areal·ln(areal).
- `tid` er en tidsfaktor der er 0 i dag. Enten fra Danmarks Statistiks faktiske prisindeks
  (`tid = ln(indeks_ved_salg / indeks_nu)`, se api/dst.py) eller — som fallback — år minus nu.
  Fordi tid=0 i dag, forsvinder b_tid ud af selve estimatet; den bruges kun til at fjerne
  markedsudviklingen fra de historiske handler, når niveauet fastsættes.
- `b_areal` fanger at kr/m² falder med boligstørrelsen (små huse er dyrere pr. m²).
Niveauet sættes robust som medianen af residualerne. Estimat = størrelsesjusteret kr/m² × m².
Boligens egen salgshistorik indgår IKKE i estimatet. Familiehandler filtreres fra af kalderen.
"""
import math

# Klamp årlig prisvækst (fallback-mode uden indeks) til et fornuftigt interval.
MIN_GROWTH, MAX_GROWTH = -0.03, 0.15
# Areal-elasticiteten (kr/m² vs. ln areal) klampes: kun aftagende, ikke ekstremt.
MIN_BSIZE, MAX_BSIZE = -0.8, 0.0
# Elasticiteten ift. markedsindekset klampes omkring 1 (lokalt marked ≈ regionalt).
MIN_BTID, MAX_BTID = 0.0, 2.0
# Mindste antal handler for at inkludere hhv. tidsled og størrelsesled.
MIN_N_TREND = 4
MIN_N_SIZE = 15
# Areal under dette (m²) betragtes som støj/fejl og springes over.
MIN_AREA = 15


def _median(xs: list[float]) -> float | None:
    s = sorted(xs)
    n = len(s)
    if n == 0:
        return None
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2


def _solve(a: list[list[float]], b: list[float]) -> list[float] | None:
    """Løs a·x = b med Gauss-elimination (lille, tæt matrix)."""
    n = len(b)
    m = [row[:] + [b[i]] for i, row in enumerate(a)]
    for c in range(n):
        piv = max(range(c, n), key=lambda r: abs(m[r][c]))
        if abs(m[piv][c]) < 1e-12:
            return None
        m[c], m[piv] = m[piv], m[c]
        d = m[c][c]
        m[c] = [v / d for v in m[c]]
        for r in range(n):
            if r != c:
                f = m[r][c]
                m[r] = [m[r][k] - f * m[c][k] for k in range(n + 1)]
    return [m[i][n] for i in range(n)]


def _ols(rows: list[tuple], k: int) -> list[float] | None:
    """OLS via normalligninger. rows[i] = (features..., y) med k features (inkl. konstant)."""
    xtx = [[sum(r[i] * r[j] for r in rows) for j in range(k)] for i in range(k)]
    xty = [sum(r[i] * r[k] for r in rows) for i in range(k)]
    return _solve(xtx, xty)


def build_model(sales: list[dict], growth_from_index: float | None = None) -> dict:
    """Byg prismodel. sales: [{price, area, tid}] hvor `tid` er tidsfaktoren (0 = i dag).

    growth_from_index: årlig vækst fra markedsindekset (kun til visning). Er den None,
    er `tid` = år−nu, og vækst/tidshældning klampes som en flad årlig rate.
    """
    indexed = growth_from_index is not None
    rows: list[tuple[float, float, float]] = []  # (tid, ln_area, ln_ppa)
    for s in sales:
        price, area, tid = s.get("price"), s.get("area"), s.get("tid")
        if not price or not area or area < MIN_AREA or tid is None:
            continue
        ppa = price / area
        if ppa > 0:
            rows.append((tid, math.log(area), math.log(ppa)))

    n = len(rows)
    empty = {"n": 0, "kr_m2_i_dag": None, "aarlig_vaekst": round(growth_from_index or 0.0, 4),
             "b_size": 0.0, "level": None, "ref_areal": None, "indekseret": indexed}
    if n == 0:
        return empty

    b_tid, b_size = 0.0, 0.0
    if n >= MIN_N_SIZE:
        coef = _ols([(1.0, tid, la, lppa) for tid, la, lppa in rows], 3)
        if coef:
            b_tid, b_size = coef[1], max(MIN_BSIZE, min(MAX_BSIZE, coef[2]))
    elif n >= MIN_N_TREND:
        coef = _ols([(1.0, tid, lppa) for tid, _, lppa in rows], 2)
        if coef:
            b_tid = coef[1]

    if indexed:
        b_tid = max(MIN_BTID, min(MAX_BTID, b_tid))
        growth = growth_from_index
    else:
        # Fallback: tid = år−nu, så b_tid er den årlige log-vækst → klamp den.
        growth = max(MIN_GROWTH, min(MAX_GROWTH, math.exp(b_tid) - 1))
        b_tid = math.log(1 + growth)

    # Robust niveau i dag (tid=0) = median af residualerne
    level = _median([lppa - b_tid * tid - b_size * la for tid, la, lppa in rows])
    ref_areal = _median([math.exp(la) for _, la, _ in rows])
    kr_ref = math.exp(level + b_size * math.log(ref_areal))
    return {
        "n": n,
        "kr_m2_i_dag": round(kr_ref),
        "aarlig_vaekst": round(growth, 4),
        "b_size": round(b_size, 4),
        "level": level,
        "ref_areal": round(ref_areal),
        "indekseret": indexed,
    }


def estimate(model: dict, m2: float | None, own_sales: list[dict]) -> dict:
    """Estimér markedspris: størrelsesjusteret kr/m² (i dag) × boligens m².

    Boligens egen salgshistorik indgår IKKE i estimatet (en gammel købspris fanger ikke
    efterfølgende istandsættelse). Den seneste frie handel returneres kun som oplysning.
    """
    level, b_size = model["level"], model["b_size"]

    marked = None
    kr_m2 = None
    if level is not None and m2 and m2 >= MIN_AREA:
        kr_m2 = round(math.exp(level + b_size * math.log(m2)))
        marked = round(kr_m2 * m2)

    seneste = None
    valid = [s for s in own_sales if s.get("price") and s.get("date")]
    if valid:
        last = max(valid, key=lambda s: s["date"])
        seneste = {"pris": last["price"], "dato": last["date"][:10]}

    return {
        "marked": marked,
        "kr_m2": kr_m2,
        "seneste_salg": seneste,
        "antal_frie_salg": len(valid),
    }
