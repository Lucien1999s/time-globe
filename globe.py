# pip install "pyvista[all]" PyQt5
# globe.py
import os
import tempfile
import urllib.request
import pyvista as pv

# 關閉 panel，確保用 Qt 視窗
os.environ["PYVISTA_USE_PANEL"] = "0"

# 兩個備援貼圖 URL（NASA Blue Marble）
TEXTURE_URLS = [
    "https://neo.gsfc.nasa.gov/archive/bluemarble/bmng/world_8km/world.topo.bathy.200407.3x5400x2700.jpg",
    "https://neo.gsfc.nasa.gov/archive/bluemarble/bmng/world_8km/world.topo.bathy.200406.3x5400x2700.jpg",
]

def fetch_texture(urls):
    last_err = None
    for url in urls:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=30) as r, \
                 tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
                tmp.write(r.read())
                return tmp.name
        except Exception as e:
            print(f"[warn] fail {url}: {e!r}")
            last_err = e
    raise RuntimeError(f"all texture urls failed; last={last_err}")

tex_path = fetch_texture(TEXTURE_URLS)

# 建球體並套貼圖
sphere = pv.Sphere(radius=1.0, theta_resolution=180, phi_resolution=180)
sphere.texture_map_to_sphere(inplace=True)
tex = pv.read_texture(tex_path)

# 視窗/渲染
plotter = pv.Plotter(window_size=[1100, 820])

# 用 'ambient' 係數模擬環境光；並加一盞低強度 scenelight 當補光
plotter.add_mesh(
    sphere,
    texture=tex,
    smooth_shading=True,
    ambient=0.25,       # ← 環境光係數（0~1）
    diffuse=0.85,
    specular=0.05,
    specular_power=20.0
)

# 主光（key light）
key = pv.Light(
    position=(3, 5, 2),
    focal_point=(0, 0, 0),
    light_type="scenelight",
    intensity=1.0,
)
plotter.add_light(key)

# 補光（fill light）— 低強度 scenelight
fill = pv.Light(
    position=(-4, -2, -3),
    focal_point=(0, 0, 0),
    light_type="scenelight",
    intensity=0.35,
)
plotter.add_light(fill)

plotter.enable_anti_aliasing()
plotter.camera_position = "iso"  # 'xz'、'yz'、'iso' 等都可
plotter.show(title="3D Earth (PyVista + PyQt5)")
