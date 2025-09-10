# globe-demo.py (ESM 版＋多鏡像回退)
import pathlib, requests
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, HTMLResponse
import uvicorn

ROOT = pathlib.Path(__file__).parent.resolve()
FRONTEND_DIR = ROOT / "frontend"
ASSETS_DIR = FRONTEND_DIR / "assets"
VENDOR_DIR = FRONTEND_DIR / "vendor"
ASSETS_DIR.mkdir(parents=True, exist_ok=True)
VENDOR_DIR.mkdir(parents=True, exist_ok=True)

PINNED_THREE_VER = "0.160.0"  # 使用新版 ESM
EARTH_TEXTURE = ASSETS_DIR / "earth_daymap_2k.jpg"
THREE_MODULE = VENDOR_DIR / "three.module.js"
ORBIT_JSM = VENDOR_DIR / "OrbitControls.js"

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

app = FastAPI(title="Globe Demo ESM")

@app.get("/", response_class=HTMLResponse)
def index():
    return FileResponse(FRONTEND_DIR / "index.html")

app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")

@app.get("/api/ping")
def ping():
    return {"ok": True}

if __name__ == "__main__":
    ensure_assets()
    uvicorn.run(app, host="127.0.0.1", port=8000)
