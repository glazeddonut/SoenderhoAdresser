import math
from collections import defaultdict

import httpx

OVERPASS_URL = "https://overpass-api.de/api/interpreter"

_EARTH_R = 6371000.0

# Water geometry rarely changes, so cache it per rounded bbox.
_water_cache: dict[str, list[list[tuple[float, float]]]] = {}


async def fetch_water_bodies(
    client: httpx.AsyncClient, polygon: list[list[float]], margin: float = 0.06
) -> list[list[tuple[float, float]]]:
    """Fetch OSM water features (coast, lakes, rivers) around the polygon.

    Returns a list of polylines [(lon,lat), ...] — coastlines/rivers as their line
    geometry, and lakes/water polygons as their shoreline ring.
    """
    lons = [p[0] for p in polygon]
    lats = [p[1] for p in polygon]
    south, west = min(lats) - margin, min(lons) - margin
    north, east = max(lats) + margin, max(lons) + margin
    key = f"{south:.2f},{west:.2f},{north:.2f},{east:.2f}"
    if key in _water_cache:
        return _water_cache[key]

    bbox = f"{south},{west},{north},{east}"
    query = (
        "[out:json][timeout:60];"
        "("
        f'way["natural"="coastline"]({bbox});'
        f'way["natural"="water"]({bbox});'
        f'way["waterway"~"^(river|canal|stream)$"]({bbox});'
        f'relation["natural"="water"]({bbox});'
        ");"
        "out geom;"
    )
    response = await client.post(
        OVERPASS_URL,
        data={"data": query},
        headers={"User-Agent": "SoenderhoAdresser/1.0"},
        timeout=90.0,
    )
    response.raise_for_status()
    data = response.json()

    lines: list[list[tuple[float, float]]] = []
    for el in data.get("elements", []):
        geom = el.get("geometry")
        if geom:
            lines.append([(pt["lon"], pt["lat"]) for pt in geom])
        elif el.get("members"):  # relation (multipolygon) — use each member ring
            for member in el["members"]:
                mgeom = member.get("geometry")
                if mgeom:
                    lines.append([(pt["lon"], pt["lat"]) for pt in mgeom])

    _water_cache[key] = lines
    return lines


class WaterIndex:
    """Spatial grid over projected water segments for fast nearest-distance queries."""

    def __init__(self, lines: list[list[tuple[float, float]]], lat0: float, cell: float = 300.0):
        self.cell = cell
        self.coslat = math.cos(math.radians(lat0))
        self.segments: list[tuple[float, float, float, float]] = []
        for line in lines:
            proj = [
                (math.radians(x) * _EARTH_R * self.coslat, math.radians(y) * _EARTH_R)
                for x, y in line
            ]
            for i in range(len(proj) - 1):
                self.segments.append((proj[i][0], proj[i][1], proj[i + 1][0], proj[i + 1][1]))

        self.grid: dict[tuple[int, int], list[int]] = defaultdict(list)
        for idx, (ax, ay, bx, by) in enumerate(self.segments):
            for cx in range(int(min(ax, bx) // cell), int(max(ax, bx) // cell) + 1):
                for cy in range(int(min(ay, by) // cell), int(max(ay, by) // cell) + 1):
                    self.grid[(cx, cy)].append(idx)

    def distance(self, lon: float, lat: float, max_rings: int = 250) -> float | None:
        """Shortest distance in meters from a point to any water segment, or None."""
        if not self.segments:
            return None
        px = math.radians(lon) * _EARTH_R * self.coslat
        py = math.radians(lat) * _EARTH_R
        cx0, cy0 = int(px // self.cell), int(py // self.cell)

        best = math.inf
        checked: set[int] = set()
        ring = 0
        while ring <= max_rings:
            for cx in range(cx0 - ring, cx0 + ring + 1):
                for cy in range(cy0 - ring, cy0 + ring + 1):
                    if max(abs(cx - cx0), abs(cy - cy0)) != ring:
                        continue  # only the perimeter of this ring
                    for idx in self.grid.get((cx, cy), ()):
                        if idx in checked:
                            continue
                        checked.add(idx)
                        d = _point_segment(px, py, *self.segments[idx])
                        if d < best:
                            best = d
            # Any unsearched segment lies in ring+1 or beyond, at least ring*cell away.
            if best <= ring * self.cell:
                break
            ring += 1
        return best if best != math.inf else None


def _point_segment(px: float, py: float, ax: float, ay: float, bx: float, by: float) -> float:
    dx, dy = bx - ax, by - ay
    seg_len2 = dx * dx + dy * dy
    if seg_len2 == 0.0:
        return math.hypot(px - ax, py - ay)
    t = ((px - ax) * dx + (py - ay) * dy) / seg_len2
    t = 0.0 if t < 0.0 else 1.0 if t > 1.0 else t
    cx, cy = ax + t * dx, ay + t * dy
    return math.hypot(px - cx, py - cy)
