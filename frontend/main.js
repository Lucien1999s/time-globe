// frontend/main.js — UV-based picking (fixed latitude & Y sampling), highlight + 3D pin + no-bounce fly
import * as THREE from 'three';
import { OrbitControls } from '/static/vendor/OrbitControls.js';

let scene, camera, renderer, controls, raycaster, mouse, earth, pin;
let highlightLayer = null;   // 透明高亮層
let picker = null;           // { W,H, canvas, ctx, idMap, pickUV(u,v) }

let flyAnim = null;
let isFlying = false;
let pointerDown = null;      // {x,y,t}
let pointerMoved = false;

const RADIUS = 2;
const ZOOM = { min: RADIUS * 1.6, max: RADIUS * 8.0, speed: 0.8 };
const TAP  = { maxDistPx: 6, maxMs: 250 };

const APP = document.getElementById('app');
const HUD = document.getElementById('hud');

init();
animate();

async function init() {
  scene = new THREE.Scene();

  camera = new THREE.PerspectiveCamera(50, window.innerWidth / window.innerHeight, 0.1, 2000);
  camera.position.set(0, 0, 6);

  renderer = new THREE.WebGLRenderer({ antialias: true });
  renderer.setSize(window.innerWidth, window.innerHeight);
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  APP.appendChild(renderer.domElement);
  renderer.domElement.style.touchAction = 'none';

  controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = false; // 杜絕回彈
  controls.enablePan = false;
  controls.target.set(0, 0, 0);
  controls.minDistance = ZOOM.min;
  controls.maxDistance = ZOOM.max;
  controls.zoomSpeed   = ZOOM.speed;

  // 光
  scene.add(new THREE.AmbientLight(0xffffff, 0.7));
  const dir = new THREE.DirectionalLight(0xffffff, 0.8);
  dir.position.set(5, 5, 5);
  scene.add(dir);

  // 政治底圖 + ID 貼圖（UV 完全一致）
  const { baseTexture, idPicker, width: TEX_W, height: TEX_H } =
    await buildPoliticalBaseAndPicker('/static/assets/countries.geojson', {
      width: 2048, height: 1024,
      ocean: '#1b3a4e',
      landFill: '#2a526d',
      border: '#dbe7f3',
      borderWidth: 0.9,
      borderOpacity: 0.9
    });
  picker = idPicker;

  earth = new THREE.Mesh(
    new THREE.SphereGeometry(RADIUS, 96, 96),
    new THREE.MeshPhongMaterial({ map: baseTexture })
  );
  scene.add(earth);

  // 高亮層（透明第二球）
  highlightLayer = makeHighlightLayer(TEX_W, TEX_H);
  scene.add(highlightLayer.mesh);

  // 3D 定位 pin
  pin = createPin();
  pin.visible = false;
  scene.add(pin);

  // 拾取
  raycaster = new THREE.Raycaster();
  mouse = new THREE.Vector2();

  // 事件
  const el = renderer.domElement;
  el.addEventListener('pointerdown', onPointerDown, { passive: true });
  el.addEventListener('pointermove', onPointerMove, { passive: true });
  el.addEventListener('pointerup',   onPointerUp,   { passive: true });

  window.addEventListener('resize', onResize, false);
}

function onResize() {
  camera.aspect = window.innerWidth / window.innerHeight;
  camera.updateProjectionMatrix();
  renderer.setSize(window.innerWidth, window.innerHeight);
}

function onPointerDown(e) {
  pointerDown = { x: e.clientX, y: e.clientY, t: performance.now() };
  pointerMoved = false;
  cancelFlightIfAny();
}

function onPointerMove(e) {
  if (!pointerDown) return;
  const dx = e.clientX - pointerDown.x;
  const dy = e.clientY - pointerDown.y;
  const d2 = dx * dx + dy * dy;
  const thresholdPx = TAP.maxDistPx * (window.devicePixelRatio || 1);
  if (d2 > thresholdPx * thresholdPx) pointerMoved = true;
}

function onPointerUp(e) {
  if (!pointerDown) return;
  const dt = performance.now() - pointerDown.t;
  const moved = pointerMoved;
  pointerDown = null; pointerMoved = false;
  if (moved || dt > TAP.maxMs) return; // 拖曳/按太久：不當點擊

  // Raycast 命中
  const rect = renderer.domElement.getBoundingClientRect();
  mouse.x = ((e.clientX - rect.left) / rect.width) * 2 - 1;
  mouse.y = -((e.clientY - rect.top) / rect.height) * 2 + 1;
  raycaster.setFromCamera(mouse, camera);
  const hit = raycaster.intersectObject(earth)[0];
  if (!hit) return;

  // === 以 UV 為準（Geometry 的 v: 0=南極, 1=北極） ===
  const u = ((hit.uv?.x ?? 0) % 1 + 1) % 1;
  const v = ((hit.uv?.y ?? 0) % 1 + 1) % 1;

  // 正確緯度：lat = -90 + 180*v  （台灣 v≈0.62 → +23°）
  const lon = u * 360 - 180;
  const lat = -90 + 180 * v;

  // 讀 ID 畫布像素：Canvas 原點在上方 → y = (1 - v) * H
  const picked = picker.pickUV(u, v); // { feature, name, iso3 } 或 null

  if (picked) {
    HUD.textContent = `Lat ${lat.toFixed(4)}°, Lon ${lon.toFixed(4)}° — ${picked.name} (${picked.iso3 || '—'})`;
    highlightLayer.clear();
    highlightLayer.paint(picked.feature);
  } else {
    HUD.textContent = `Lat ${lat.toFixed(4)}°, Lon ${lon.toFixed(4)}°`;
    highlightLayer.clear();
  }

  // pin 用命中點方向（視覺最準）
  const dir = hit.point.clone().normalize();
  setPinAtDirection(dir);
  flyToDirection(dir, 1000);
}

function cancelFlightIfAny() {
  if (isFlying) {
    flyAnim = null;
    isFlying = false;
    controls.enabled = true;
    controls.update();
  }
}

/* ===== 3D Pin / 飛行（無回彈） ===== */
function createPin() {
  const g = new THREE.Group();
  const stemH = 0.18, stemR = 0.012;
  const stem = new THREE.Mesh(
    new THREE.CylinderGeometry(stemR, stemR, stemH, 16),
    new THREE.MeshPhongMaterial({ color: 0xff8080, shininess: 60 })
  );
  stem.position.y = stemH / 2;
  const headR = 0.05;
  const head = new THREE.Mesh(
    new THREE.SphereGeometry(headR, 20, 20),
    new THREE.MeshPhongMaterial({ color: 0xff3b3b, shininess: 80 })
  );
  head.position.y = stemH + headR;
  const base = new THREE.Mesh(
    new THREE.CylinderGeometry(0.018, 0.018, 0.005, 24),
    new THREE.MeshPhongMaterial({ color: 0xff6666, shininess: 30 })
  );
  base.position.y = 0.0025;
  g.add(base, stem, head);
  return g;
}
function setPinAtDirection(dir) {
  const yAxis = new THREE.Vector3(0, 1, 0);
  const tipOffset = 0.01;
  pin.position.copy(dir).multiplyScalar(RADIUS + tipOffset);
  pin.quaternion.setFromUnitVectors(yAxis, dir);
  pin.visible = true;
}
function flyToDirection(targetDir, duration = 1200) {
  const r0 = THREE.MathUtils.clamp(camera.position.length(), ZOOM.min, ZOOM.max);
  const fromDir = camera.position.clone().normalize();
  const toDir   = targetDir.clone().normalize();
  const start = performance.now();
  const ease = t => (t < 0.5) ? 2 * t * t : -1 + (4 - 2 * t) * t;

  isFlying = true;
  controls.enabled = false;

  flyAnim = (now) => {
    const t = Math.min(1, (now - start) / duration);
    const k = ease(t);
    const dir = slerpDir(fromDir, toDir, k);
    camera.position.copy(dir).multiplyScalar(r0);
    camera.lookAt(0, 0, 0);
    if (t >= 1) {
      camera.position.copy(toDir).multiplyScalar(r0);
      camera.lookAt(0, 0, 0);
      flyAnim = null;
      isFlying = false;
      controls.enabled = true;
      controls.update();
    }
  };
}
function slerpDir(a, b, t) {
  const dot = THREE.MathUtils.clamp(a.dot(b), -1, 1);
  if (dot > 0.9995) return a.clone().lerp(b, t).normalize();
  const omega = Math.acos(dot), sinO = Math.sin(omega);
  return a.clone().multiplyScalar(Math.sin((1 - t) * omega) / sinO)
         .add(b.clone().multiplyScalar(Math.sin(t * omega) / sinO)).normalize();
}

/* ===== 底圖 + ID 貼圖（UV 一致） ===== */
async function buildPoliticalBaseAndPicker(url, opt) {
  const geo = await fetch(url).then(r => r.json());
  const W = opt.width || 2048, H = opt.height || 1024;

  // 底圖
  const base = document.createElement('canvas'); base.width = W; base.height = H;
  const bctx = base.getContext('2d');

  // ID 圖（用於 picking）
  const idc = document.createElement('canvas'); idc.width = W; idc.height = H;
  const ictx = idc.getContext('2d', { willReadFrequently: true });
  ictx.imageSmoothingEnabled = false;

  // 海洋
  bctx.fillStyle = opt.ocean || '#0b2238'; bctx.fillRect(0, 0, W, H);
  ictx.fillStyle = 'rgb(0,0,0)'; ictx.fillRect(0, 0, W, H); // id=0 → 海

  const idMap = new Map(); let nextId = 1;

  const drawRings = (ctx, rings, shiftPx, mode /*'fill'|'stroke'*/) => {
    ctx.beginPath();
    for (const ring of rings) {
      const unwrapped = unwrapRing(ring);
      unwrapped.forEach(([L, lat], i) => {
        const x = ((L + 180) / 360) * W + shiftPx;
        const y = ((90 - lat) / 180) * H;
        if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
      });
      ctx.closePath();
    }
    if (mode === 'fill') {
      // @ts-ignore
      ctx.fill('evenodd'); // 支援洞
    } else {
      ctx.stroke();
    }
  };

  bctx.lineWidth = opt.borderWidth ?? 0.9;
  bctx.strokeStyle = opt.border || '#dbe7f3';
  bctx.globalAlpha = opt.borderOpacity ?? 0.9;
  bctx.fillStyle = opt.landFill || '#112f51';
  bctx.globalCompositeOperation = 'source-over';

  for (const f of geo.features) {
    const geom = f.geometry; if (!geom) continue;
    const id = nextId++; const r = id & 255, g8 = (id >> 8) & 255, b = (id >> 16) & 255;
    const colorStr = `rgb(${r},${g8},${b})`;
    idMap.set((r) | (g8 << 8) | (b << 16), f);

    if (geom.type === 'Polygon') {
      for (const s of [-W, 0, W]) { drawRings(bctx, geom.coordinates, s, 'fill'); }
      // 外框
      for (const s of [-W, 0, W]) {
        bctx.beginPath();
        const outer = unwrapRing(geom.coordinates[0]);
        outer.forEach(([L, lat], i) => {
          const x = ((L + 180) / 360) * W + s;
          const y = ((90 - lat) / 180) * H;
          if (i === 0) bctx.moveTo(x, y); else bctx.lineTo(x, y);
        });
        bctx.closePath(); bctx.stroke();
      }
      // ID 填色
      ictx.save(); ictx.fillStyle = colorStr;
      for (const s of [-W, 0, W]) { drawRings(ictx, geom.coordinates, s, 'fill'); }
      ictx.restore();

    } else if (geom.type === 'MultiPolygon') {
      for (const poly of geom.coordinates) {
        for (const s of [-W, 0, W]) { drawRings(bctx, poly, s, 'fill'); }
        for (const s of [-W, 0, W]) {
          bctx.beginPath();
          const outer = unwrapRing(poly[0]);
          outer.forEach(([L, lat], i) => {
            const x = ((L + 180) / 360) * W + s;
            const y = ((90 - lat) / 180) * H;
            if (i === 0) bctx.moveTo(x, y); else bctx.lineTo(x, y);
          });
          bctx.closePath(); bctx.stroke();
        }
        ictx.save(); ictx.fillStyle = colorStr;
        for (const s of [-W, 0, W]) { drawRings(ictx, poly, s, 'fill'); }
        ictx.restore();
      }
    }
  }

  const baseTexture = new THREE.CanvasTexture(base);
  baseTexture.anisotropy = 4;
  baseTexture.wrapS = THREE.RepeatWrapping;
  baseTexture.wrapT = THREE.RepeatWrapping;
  // 使用預設 flipY=true；與 SphereGeometry UV 對齊
  baseTexture.needsUpdate = true;

  const idPicker = {
    W, H, canvas: idc, ctx: ictx, idMap,
    // 讀像素：Canvas 原點在上方 → y = (1 - v) * H
    pickUV: (u, v) => {
      let x = Math.floor(((u % 1 + 1) % 1) * W);
      let y = Math.floor((1 - ((v % 1 + 1) % 1)) * H);
      if (x < 0) x = 0; if (x >= W) x = W - 1;
      if (y < 0) y = 0; if (y >= H) y = H - 1;
      const p = ictx.getImageData(x, y, 1, 1).data; // [r,g,b,a]
      const colorInt = (p[0]) | (p[1] << 8) | (p[2] << 16);
      const feature = idMap.get(colorInt);
      if (!feature) return null;
      return { feature, name: countryName(feature.properties), iso3: countryISO3(feature.properties) };
    }
  };

  return { baseTexture, idPicker, width: W, height: H };
}

/* ===== 高亮層（透明第二球） ===== */
function makeHighlightLayer(W, H) {
  const canvas = document.createElement('canvas');
  canvas.width = W; canvas.height = H;
  const ctx = canvas.getContext('2d');

  const texture = new THREE.CanvasTexture(canvas);
  texture.wrapS = THREE.RepeatWrapping;
  texture.wrapT = THREE.RepeatWrapping;
  // 同樣使用預設 flipY=true
  texture.needsUpdate = true;

  const material = new THREE.MeshBasicMaterial({
    map: texture, transparent: true, depthWrite: false, opacity: 1.0
  });
  const mesh = new THREE.Mesh(
    new THREE.SphereGeometry(RADIUS + 0.001, 96, 96),
    material
  );

  const clear = () => { ctx.clearRect(0, 0, W, H); texture.needsUpdate = true; };

  const paint = (feature) => {
    clear();
    ctx.fillStyle = 'rgba(255, 215, 0, 0.30)';
    ctx.strokeStyle = 'rgba(255, 255, 255, 0.95)';
    ctx.lineWidth = 1.2;

    const drawRings = (rings, shiftPx) => {
      ctx.beginPath();
      for (const ring of rings) {
        const unwrapped = unwrapRing(ring);
        unwrapped.forEach(([L, lat], i) => {
          const x = ((L + 180) / 360) * W + shiftPx;
          const y = ((90 - lat) / 180) * H;
          if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
        });
        ctx.closePath();
      }
      // @ts-ignore
      ctx.fill('evenodd');
    };

    const g = feature.geometry; if (!g) return;
    if (g.type === 'Polygon') {
      for (const s of [-W, 0, W]) drawRings(g.coordinates, s);
      for (const s of [-W, 0, W]) {
        ctx.beginPath();
        const outer = unwrapRing(g.coordinates[0]);
        outer.forEach(([L, lat], i) => {
          const x = ((L + 180) / 360) * W + s;
          const y = ((90 - lat) / 180) * H;
          if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
        });
        ctx.closePath(); ctx.stroke();
      }
    } else if (g.type === 'MultiPolygon') {
      for (const poly of g.coordinates) {
        for (const s of [-W, 0, W]) drawRings(poly, s);
        for (const s of [-W, 0, W]) {
          ctx.beginPath();
          const outer = unwrapRing(poly[0]);
          outer.forEach(([L, lat], i) => {
            const x = ((L + 180) / 360) * W + s;
            const y = ((90 - lat) / 180) * H;
            if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
          });
          ctx.closePath(); ctx.stroke();
        }
      }
    }
    texture.needsUpdate = true;
  };

  return { canvas, ctx, texture, mesh, clear, paint };
}

/* ===== 共用工具 ===== */
function unwrapRing(ring) {
  const out = [];
  let prev = null, offset = 0;
  for (const [lon, lat] of ring) {
    let L = lon + offset;
    if (prev !== null) {
      const diff = L - prev;
      if (diff > 180)      { offset -= 360; L = lon + offset; }
      else if (diff < -180){ offset += 360; L = lon + offset; }
    }
    out.push([L, lat]); prev = L;
  }
  return out;
}
function countryName(p) {
  return p?.ADMIN || p?.NAME_LONG || p?.NAME || p?.name || p?.SOVEREIGNT || p?.COUNTRY || 'Unknown';
}
function countryISO3(p) {
  return p?.ISO_A3 || p?.iso_a3 || p?.ADM0_A3 || p?.WB_A3 || null;
}

function animate(now) {
  requestAnimationFrame(animate);
  if (!isFlying) controls.update();
  if (flyAnim) flyAnim(now);
  renderer.render(scene, camera);
}
