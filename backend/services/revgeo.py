# backend/services/revgeo.py — reverse geocoding with fallbacks
from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse
import requests

router = APIRouter()

def _normalize(resp: dict, src: str):
    if src == "bigdatacloud":
        return {
            "source": "bigdatacloud",
            "confidence": resp.get("confidence"),
            "country": resp.get("countryName"),
            "country_code": (resp.get("countryCode") or "").upper() or None,
            "admin1": resp.get("principalSubdivision"),
            "admin2": resp.get("localityInfo", {}).get("administrative", [{}])[1].get("name")
                      if resp.get("localityInfo", {}).get("administrative") else None,
            "city": resp.get("city") or resp.get("locality") or None,
        }
    if src == "nominatim":
        addr = resp.get("address", {})
        city = addr.get("city") or addr.get("town") or addr.get("village") or addr.get("hamlet")
        return {
            "source": "nominatim",
            "confidence": None,
            "country": addr.get("country"),
            "country_code": (addr.get("country_code") or "").upper() or None,
            "admin1": addr.get("state"),
            "admin2": addr.get("county") or addr.get("region"),
            "city": city,
        }
    if src == "openmeteo":
        item = (resp.get("results") or [None])[0] or {}
        return {
            "source": "openmeteo",
            "confidence": item.get("elevation"),
            "country": item.get("country"),
            "country_code": (item.get("country_code") or "").upper() or None,
            "admin1": item.get("admin1"),
            "admin2": item.get("admin2"),
            "city": item.get("name"),
        }
    return {}

@router.get("/revgeo", response_class=JSONResponse)
def reverse_geocode(lat: float = Query(...), lon: float = Query(...)):
    # 1) BigDataCloud
    try:
        u = f"https://api.bigdatacloud.net/data/reverse-geocode-client?latitude={lat}&longitude={lon}&localityLanguage=en"
        r = requests.get(u, timeout=6)
        if r.ok:
            data = _normalize(r.json(), "bigdatacloud")
            if any([data.get("admin1"), data.get("city")]):
                return data
    except Exception as e:
        print("[revgeo] bigdatacloud:", e)

    # 2) Nominatim（zoom 拉高，需帶 UA）
    try:
        u = "https://nominatim.openstreetmap.org/reverse"
        params = {"lat": lat, "lon": lon, "format": "jsonv2", "addressdetails": 1, "zoom": 14}
        headers = {"User-Agent": "time-globe/0.1 (contact: dev@time-globe.local)"}
        r = requests.get(u, params=params, headers=headers, timeout=8)
        if r.ok:
            data = _normalize(r.json(), "nominatim")
            if any([data.get("admin1"), data.get("city")]):
                return data
    except Exception as e:
        print("[revgeo] nominatim:", e)

    # 3) Open-Meteo Geocoding
    try:
        u = f"https://geocoding-api.open-meteo.com/v1/reverse?latitude={lat}&longitude={lon}&language=en"
        r = requests.get(u, timeout=6)
        if r.ok:
            return _normalize(r.json(), "openmeteo")
    except Exception as e:
        print("[revgeo] openmeteo:", e)

    return {"source": None, "country": None, "country_code": None, "admin1": None, "admin2": None, "city": None}
