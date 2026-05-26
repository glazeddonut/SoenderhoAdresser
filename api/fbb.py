import httpx

FBB_WFS = "https://www.kulturarv.dk/geoserver/fbb/wfs"


async def fetch_listed_buildings(
    client: httpx.AsyncClient,
    polygon: list[list[float]],
) -> set[str]:
    """Return set of BBR id_lokalId values for fredede buildings in the polygon area.

    FBB WFS expects BBOX as minLat,minLon,maxLat,maxLon in EPSG:4326.
    The ois_id in FBB matches id_lokalId in BBR.
    """
    lons = [p[0] for p in polygon]
    lats = [p[1] for p in polygon]
    bbox = f"{min(lats)},{min(lons)},{max(lats)},{max(lons)},urn:ogc:def:crs:EPSG::4326"

    params = {
        "SERVICE": "WFS",
        "VERSION": "2.0.0",
        "REQUEST": "GetFeature",
        "TYPENAMES": "fbb:view_bygning_fredede",
        "outputFormat": "application/json",
        "BBOX": bbox,
    }
    response = await client.get(FBB_WFS, params=params, timeout=30.0)
    response.raise_for_status()
    data = response.json()

    return {
        f["properties"]["ois_id"]
        for f in data.get("features", [])
        if f["properties"].get("ois_id")
    }
