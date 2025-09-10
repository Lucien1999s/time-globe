from pathlib import Path
import requests

PINNED_THREE_VER = "0.160.0"

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

def _download_first(urls, path: Path, name: str):
    if path.exists() and path.stat().st_size > 0:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    for url in urls:
        try:
            print(f"[assets] Fetch {name} from {url}")
            r = requests.get(url, timeout=30)
            r.raise_for_status()
            path.write_bytes(r.content)
            print(f"[assets] Wrote {path} ({len(r.content)} bytes)")
            return
        except Exception as e:
            print(f"[assets] WARN: {name} failed from {url}: {e}")
    print(f"[assets] ERROR: All mirrors failed for {name}")

def ensure_assets(frontend_dir: Path):
    assets = frontend_dir / "assets"
    vendor = frontend_dir / "vendor"
    EARTH_TEXTURE = assets / "earth_daymap_2k.jpg"
    THREE_MODULE  = vendor / "three.module.js"
    ORBIT_JSM     = vendor / "OrbitControls.js"
    COUNTRIES_GEO = assets / "countries.geojson"

    _download_first(EARTH_MIRRORS, EARTH_TEXTURE, "Earth texture")
    _download_first(THREE_MODULE_MIRRORS, THREE_MODULE, "three.module.js")
    _download_first(ORBIT_MIRRORS, ORBIT_JSM, "OrbitControls.js")
    _download_first(COUNTRIES_MIRRORS, COUNTRIES_GEO, "countries.geojson")
