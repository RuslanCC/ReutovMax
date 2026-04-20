from __future__ import annotations

import io
import logging

from PIL import ExifTags, Image

log = logging.getLogger(__name__)

_GPS_TAG = next((k for k, v in ExifTags.TAGS.items() if v == "GPSInfo"), None)


def _to_decimal(value: tuple, ref: str) -> float:
    d, m, s = (float(x) for x in value)
    result = d + m / 60.0 + s / 3600.0
    if ref in ("S", "W"):
        result = -result
    return result


def extract_gps(image_bytes: bytes) -> tuple[float, float] | None:
    """Достаёт (lat, lon) из EXIF фотографии или None."""
    try:
        with Image.open(io.BytesIO(image_bytes)) as img:
            exif = img._getexif() if hasattr(img, "_getexif") else None
    except Exception as e:  # noqa: BLE001
        log.debug("EXIF read failed: %s", e)
        return None
    if not exif or _GPS_TAG is None:
        return None
    gps = exif.get(_GPS_TAG)
    if not gps:
        return None
    gps_named = {ExifTags.GPSTAGS.get(k, k): v for k, v in gps.items()}
    try:
        lat = _to_decimal(gps_named["GPSLatitude"], gps_named["GPSLatitudeRef"])
        lon = _to_decimal(gps_named["GPSLongitude"], gps_named["GPSLongitudeRef"])
        return lat, lon
    except (KeyError, TypeError, ValueError):
        return None
