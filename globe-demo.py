# globe-demo.py — FastAPI static server + robust reverse geocoding (admin1/city)
import pathlib, requests
from fastapi import FastAPI, Query
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

ROOT = pathlib.Path(__file__).parent.resolve()
FRONTEND_DIR = ROOT / "frontend"
ASSETS_DIR = FRONTEND_DIR / "assets"
VENDOR_DIR = FRONTEND_DIR / "vendor"
ASSETS_DIR.mkdir(parents=True, exist_ok=True)
VENDOR_DIR.mkdir(parents=True, exist_ok=True)

PINNED_THREE_VER = "0.160.0"
EARTH_TEXTURE = ASSETS_DIR / "earth_daymap_2k.jpg"
THREE_MODULE  = VENDOR_DIR / "three.module.js"
ORBIT_JSM     = VENDOR_DIR / "OrbitControls.js"
COUNTRIES_GEO = ASSETS_DIR / "countries.geojson"

EARTH_MIRRORS = [
    "https://threejs.org/examples/textures/land_ocean_ice_cloud_2048.jpg",
    "https://cdn.jsdelivr.net/gh/mrdoob/three.js@r160/examples/textures/land_ocean_ice_cloud_2048.jpg",
    "https://raw.githubusercontent.com/mrdoob/three.js/r160/examples/textures/land_ocean_ice_cloud_2048.jpg",
]
THREE_MODULE_MIRRORS = [
    f"https://cdn.jsdelivr.net/npm/three@{PINNED_THREE_VER}/build/three.module.js",
    f"https://unpkg.com/three@{PINNED_THREE_VER}/build/three.module.js",
    f"https://raw.githubusercontent.com/mrdoob/three.js/r160/build/three.module.js",
]
ORBIT_MIRRORS = [
    f"https://cdn.jsdelivr.net/npm/three@{PINNED_THREE_VER}/examples/jsm/controls/OrbitControls.js",
    f"https://unpkg.com/three@{PINNED_THREE_VER}/examples/jsm/controls/OrbitControls.js",
    "https://raw.githubusercontent.com/mrdoob/three.js/r160/examples/jsm/controls/OrbitControls.js",
]
COUNTRIES_MIRRORS = [
    "https://raw.githubusercontent.com/johan/world.geo.json/master/countries.geo.json",
    "https://raw.githubusercontent.com/datasets/geo-countries/master/data/countries.geojson",
]

def download_first(urls, path: pathlib.Path, name: str):
    for url in urls:
        try:
            print(f"[setup] Fetch {name} from {url}")
            r = requests.get(url, timeout=30)
            r.raise_for_status()
            path.write_bytes(r.content)
            print(f"[setup] Wrote {path} ({len(r.content)} bytes)")
            return True
        except Exception as e:
            print(f"[setup] WARN: {name} failed from {url}: {e}")
    print(f"[setup] ERROR: All mirrors failed for {name}")
    return False

def ensure_assets():
    download_first(EARTH_MIRRORS, EARTH_TEXTURE, "Earth texture")
    download_first(THREE_MODULE_MIRRORS, THREE_MODULE, "three.module.js")
    download_first(ORBIT_MIRRORS, ORBIT_JSM, "OrbitControls.js")
    download_first(COUNTRIES_MIRRORS, COUNTRIES_GEO, "countries.geojson")

app = FastAPI(title="Time-Globe MVP")

# CORS（其實同源不需要，但為了擴充/外部前端也能調用，先放）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"],
)

@app.get("/", response_class=HTMLResponse)
def index():
    return FileResponse(FRONTEND_DIR / "index.html")

app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")

@app.get("/api/ping")
def ping():
    return {"ok": True}

# ---------- Reverse Geocoding (country→admin1→city) ----------
def normalize(resp: dict, src: str):
    if src == "bigdatacloud":
        # https://www.bigdatacloud.com/docs/api/reverse-geocode-client
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
        # https://nominatim.org/release-docs/latest/api/Reverse/
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
        # https://open-meteo.com/en/docs/geocoding-api
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

@app.get("/api/revgeo", response_class=JSONResponse)
def reverse_geocode(lat: float = Query(...), lon: float = Query(...)):
    # 1) BigDataCloud
    try:
        u = f"https://api.bigdatacloud.net/data/reverse-geocode-client?latitude={lat}&longitude={lon}&localityLanguage=en"
        r = requests.get(u, timeout=6)
        if r.ok:
            data = normalize(r.json(), "bigdatacloud")
            if any([data.get("admin1"), data.get("city")]):
                return data
    except Exception as e:
        print("[revgeo] bigdatacloud:", e)

    # 2) Nominatim（zoom 提高一點抓到更細的市鎮）
    try:
        u = "https://nominatim.openstreetmap.org/reverse"
        params = {"lat": lat, "lon": lon, "format": "jsonv2", "addressdetails": 1, "zoom": 14}
        headers = {"User-Agent": "time-globe/0.1 (contact: dev@time-globe.local)"}
        r = requests.get(u, params=params, headers=headers, timeout=8)
        if r.ok:
            data = normalize(r.json(), "nominatim")
            if any([data.get("admin1"), data.get("city")]):
                return data
    except Exception as e:
        print("[revgeo] nominatim:", e)

    # 3) Open-Meteo Geocoding
    try:
        u = f"https://geocoding-api.open-meteo.com/v1/reverse?latitude={lat}&longitude={lon}&language=en"
        r = requests.get(u, timeout=6)
        if r.ok:
            data = normalize(r.json(), "openmeteo")
            return data
    except Exception as e:
        print("[revgeo] openmeteo:", e)

    return {"source": None, "country": None, "country_code": None, "admin1": None, "admin2": None, "city": None}
# ----------------------------------------------------

if __name__ == "__main__":
    ensure_assets()
    uvicorn.run(app, host="127.0.0.1", port=8000)
