from __future__ import annotations

import logging

import httpx

log = logging.getLogger(__name__)


async def geocode_yandex(address: str, api_key: str) -> tuple[float, float, str] | None:
    """Геокодит адрес через Yandex Geocoder. Возвращает (lat, lon, нормализованный адрес)."""
    full = f"Реутов, {address}" if "реутов" not in address.lower() else address
    params = {"apikey": api_key, "geocode": full, "format": "json", "results": 1, "lang": "ru_RU"}
    try:
        async with httpx.AsyncClient(timeout=10.0) as c:
            r = await c.get("https://geocode-maps.yandex.ru/1.x/", params=params)
            r.raise_for_status()
            data = r.json()
    except Exception as e:  # noqa: BLE001
        log.warning("Yandex geocoder failed: %s", e)
        return None
    members = data.get("response", {}).get("GeoObjectCollection", {}).get("featureMember", [])
    if not members:
        return None
    geo = members[0]["GeoObject"]
    pos = geo["Point"]["pos"]  # "lon lat"
    lon_s, lat_s = pos.split()
    name = geo.get("metaDataProperty", {}).get("GeocoderMetaData", {}).get("text", full)
    return float(lat_s), float(lon_s), name


def yandex_maps_link(lat: float, lon: float) -> str:
    return f"https://yandex.ru/maps/?pt={lon},{lat}&z=17&l=map"
