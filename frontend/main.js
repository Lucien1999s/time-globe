// frontend/main.js — globe + side panel (wiki + LLM) + reverse geo + country picking
import * as THREE from 'three';
import { OrbitControls } from '/static/vendor/OrbitControls.js';

let scene, camera, renderer, controls, raycaster, mouse, earth, pin;
let highlightLayer = null;   // 高亮透明層
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

let placeinfoAbort = null;

// === 新增：UI 語言值 → Wikipedia 語言碼 ===
function uiLangToWikiLang(v) {
  switch ((v || "").toLowerCase()) {
    case "繁體中文": return "zh";
    case "english":   return "en";
    case "日本語":    return "ja";
    case "한국어":     return "ko";
    case "español":   return "es";
    default:          return "zh";
  }
}

// === 新增：最後一次點擊的上下文（送後端打分用） ===
let lastCtx = { lat: null, lon: null, country: null, admin1: null, city: null };

function buildHistoryQuery(placeName, ctx) {
  const parts = [
    ctx?.country || null,
    ctx?.admin1 || null,
    ctx?.city || null,
    placeName || null,
  ];

  // 去重、去空白
  const seen = new Set();
  const out = [];
  for (const s of parts) {
    const t = (s || "").trim();
    if (!t) continue;
    const key = t.toLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);
    out.push(t);
  }
  return out.join(", ");
}

// side panel elements
const EL = {
  thumb: document.getElementById('place-thumb'),
  title: document.getElementById('place-title'),
  desc: document.getElementById('place-desc'),
  url: document.getElementById('place-url'),
  summary: document.getElementById('place-summary'),
  lang: document.getElementById('lang-select'),
  btnOverview: document.getElementById('btn-overview'),
  btnAdvanced: document.getElementById('btn-advanced'),
  out: document.getElementById('history-output'),
};

// 歷史事件 UI 元素
const EV = {
  fab: document.getElementById('events-fab'),
  panel: document.getElementById('events-panel'),
  list: document.getElementById('events-list'),
  close: document.getElementById('events-close'),
};

// 預設占位內容（專業版）
const DEFAULTS = {
  title: 'Time-Globe：Beyond Space & Time',
  desc: 'Click the globe for Wiki summary, images, links, plus history and timeline.',
  summary: 'Tip: Rotate (drag), Zoom (scroll), Select (tap). Side button shows History/Timeline.',
  img: '/static/assets/default.jpg',
  url: '#'
};

// 一鍵套用預設資訊卡
function setDefaultCard() {
  EL.title.textContent = DEFAULTS.title;
  EL.desc.textContent = DEFAULTS.desc;
  EL.summary.textContent = DEFAULTS.summary;
  EL.thumb.src = DEFAULTS.img;
  EL.thumb.style.display = 'block';       // 確保顯示
  EL.url.href = DEFAULTS.url;
  EL.out.textContent = '';                // 清空歷史區塊
}

let lastPlaceName = null;  // derived place string for wiki/history

init();
animate();

async function init() {
  scene = new THREE.Scene();
  // 背景星空
  scene.background = makeStarfieldTexture({ w: 2048, h: 1024, stars: 1200, nebula: 0.08 });

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
    new THREE.MeshPhongMaterial({
      map: baseTexture,
      specular: new THREE.Color(0x335577),
      shininess: 18,
      emissive: 0x000000
    })
  );
  scene.add(earth);

  // 大氣層：反面繪製、微透明
  const atmosphere = new THREE.Mesh(
    new THREE.SphereGeometry(RADIUS + 0.05, 64, 64),
    new THREE.MeshBasicMaterial({ color: 0x66ccff, transparent: true, opacity: 0.08, side: THREE.BackSide })
  );
  scene.add(atmosphere);

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

  // 側欄按鈕綁定前/後都可，先把預設卡片顯示出來
  setDefaultCard();

  // 側欄按鈕
  if (EL.btnOverview) EL.btnOverview.addEventListener('click', onClickOverview);
  if (EL.btnAdvanced) EL.btnAdvanced.addEventListener('click', onClickAdvanced);
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

async function onPointerUp(e) {
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

  // === 以 UV 為準（SphereGeometry: v=0 南極 / v=1 北極） ===
  const u = ((hit.uv?.x ?? 0) % 1 + 1) % 1;
  const v = ((hit.uv?.y ?? 0) % 1 + 1) % 1;

  // 正確緯度公式：lat = -90 + 180*v
  const lon = u * 360 - 180;
  const lat = -90 + 180 * v;

  // 用 ID 貼圖取國家
  const picked = picker.pickUV(u, v); // { feature, name, iso3 } 或 null

  // 先更新 HUD（國家）
  if (picked) {
    HUD.textContent = `Lat ${lat.toFixed(4)}°, Lon ${lon.toFixed(4)}° — ${picked.name}`;
    highlightLayer.clear();
    highlightLayer.paint(picked.feature);
  } else {
    HUD.textContent = `Lat ${lat.toFixed(4)}°, Lon ${lon.toFixed(4)}°`;
    highlightLayer.clear();
  }

  // pin + 飛行到命中方向
  const dir = hit.point.clone().normalize();
  setPinAtDirection(dir);
  flyToDirection(dir, 1000);

  // 反向地理編碼 → 推導 place 名稱 → 拉 Wiki/Info 卡
  const ctx = await enrichWithRevGeo(lat, lon, picked?.name);
  const place = ctx.place || picked?.name || `(${lat.toFixed(3)}, ${lon.toFixed(3)})`;
  lastPlaceName = place;
  await fetchAndRenderPlaceInfo(place, lastCtx);

  // 只要有 city，就顯示「歷史事件」FAB（用 city 當關鍵字）
  if (lastCtx.city) {
    EV.fab.style.display = 'inline-block';
    EV.fab.classList.add('pulse');
    EV.fab.setAttribute('title', `查看 ${lastCtx.city} 的相關歷史文章`);
  } else {
    // 沒有 city → 隱藏 FAB 並關閉面板
    EV.fab.style.display = 'none';
    if (EV.panel) EV.panel.classList.remove('open');
  }
}

/* ---------- 反向地理編碼：補上州/省、城市，並回傳完整上下文 ---------- */
async function enrichWithRevGeo(lat, lon, countryNameFromPicker) {
  const url = `/api/revgeo?lat=${lat.toFixed(6)}&lon=${lon.toFixed(6)}`;
  try {
    const res = await fetch(url, { cache: "no-store" });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const j = await res.json();

    const admin1  = j.admin1 || null;
    const city    = j.city || null;
    const country = j.country || countryNameFromPicker || null;

    // Compose place: prefer City > Admin1 > Country
    const place = city || admin1 || country || null;

    // Update HUD tail
    if (admin1 || city) {
      const suffix = [admin1, city].filter(Boolean).join(" › ");
      appendHudDetail(suffix);
    } else if (country) {
      appendHudDetail(country);
    } else {
      appendHudDetail("(no city)");
    }

    // 同步 lastCtx
    lastCtx = { lat, lon, country, admin1, city };
    return { place, country, admin1, city };
  } catch (err) {
    console.warn("[revgeo] failed", err);
    appendHudDetail("(revgeo failed)");
    const country = countryNameFromPicker || null;
    lastCtx = { lat, lon, country, admin1: null, city: null };
    return { place: country, country, admin1: null, city: null };
  }
}

// 估算海洋名稱（粗略分區）— 讓點到海上也能展示資訊
function oceanNameByLatLon(lat, lon) {
  if (lat > 66) return "Arctic Ocean";
  if (lat < -60) return "Southern Ocean";
  // 簡單經度分段：大略即可
  const L = ((lon + 540) % 360) - 180; // normalize
  if (L >= -70 && L <= 20) return "Atlantic Ocean";
  if (L > 20 && L <= 150) return "Indian Ocean";
  return "Pacific Ocean";
}

// 把細節安全「追加」到 HUD 末端，不覆蓋前半段
function appendHudDetail(text) {
  if (!text) return;
  const hasDetail = / — [^—]+$/.test(HUD.textContent);
  if (hasDetail) {
    HUD.textContent = HUD.textContent.replace(/ — [^—]+$/, ` — ${text}`);
  } else {
    HUD.textContent = `${HUD.textContent} — ${text}`;
  }
}

/* ---------- 拉 Wiki Place 基本資料並渲染卡片（上下文加權 + Abort） ---------- */
async function fetchAndRenderPlaceInfo(placeName, ctx) {
  // 點擊地圖時自動打開 side panel
  if (document.body.classList.contains('side-collapsed')) {
    document.body.classList.remove('side-collapsed');
    const btnToggle = document.getElementById('toggle-side');
    if (btnToggle) btnToggle.textContent = '❯';  // 保持箭頭方向正確
  }
  try {
    // Abort any previous in-flight request
    if (placeinfoAbort) placeinfoAbort.abort();
    placeinfoAbort = new AbortController();

    const uiLang = EL.lang ? EL.lang.value : "繁體中文";
    const lang = uiLangToWikiLang(uiLang);

    const q = new URLSearchParams({ name: placeName, lang });
    if (ctx?.country) q.set("country", ctx.country);
    if (ctx?.admin1)  q.set("admin1",  ctx.admin1);
    if (ctx?.city)    q.set("city",    ctx.city);
    if (typeof ctx?.lat === "number") q.set("lat", String(ctx.lat));
    if (typeof ctx?.lon === "number") q.set("lon", String(ctx.lon));

    EL.summary.textContent = "Loading basic info…";

    const res = await fetch(`/api/placeinfo?${q.toString()}`, {
      cache: "no-store",
      signal: placeinfoAbort.signal
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const j = await res.json();

    if (!j.ok) {
      EL.title.textContent = placeName;
      EL.desc.textContent = "";
      EL.summary.textContent = "No Wikipedia info found.";
      EL.thumb.src = DEFAULTS.img;
      EL.thumb.style.display = "block";
      EL.url.href = "#";
      EL.out.textContent = "";
      return;
    }

    EL.title.textContent = j.title || placeName;
    EL.desc.textContent = j.description || "";
    EL.summary.textContent = j.summary || "(no summary)";
    EL.url.href = j.url || "#";

    const img = j.original_image || j.thumbnail || DEFAULTS.img;
    EL.thumb.src = img;
    EL.thumb.style.display = "block";

    EL.out.textContent = "";
  } catch (err) {
    if (err.name === "AbortError") return; // 被新請求中止：安靜返回
    console.error("[placeinfo]", err);
    EL.title.textContent = placeName || DEFAULTS.title;
    EL.desc.textContent = "";
    EL.summary.textContent = "Failed to load place info.";
    EL.thumb.src = DEFAULTS.img;
    EL.thumb.style.display = "block";
    EL.url.href = "#";
  } finally {
    // 清空 controller，避免 memory leak
    placeinfoAbort = null;
  }
}


/* ---------- 歷史摘要（Gemini） / 進階（OpenAI+Search） ---------- */
async function onClickOverview() {
  if (!lastPlaceName) return;
  const queryPlace = buildHistoryQuery(lastPlaceName, lastCtx);
  await runHistory("/api/history/overview", queryPlace, EL.lang.value);
}

async function onClickAdvanced() {
  if (!lastPlaceName) return;
  const queryPlace = buildHistoryQuery(lastPlaceName, lastCtx);
  await runHistory("/api/history/advanced", queryPlace, EL.lang.value);
}

async function runHistory(endpoint, place, language) {
  const btns = [EL.btnOverview, EL.btnAdvanced, EL.lang];
  try {
    btns.forEach(b => b.disabled = true);
    EL.out.textContent = "Generating…";
    const res = await fetch(endpoint, {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({ place, language })
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const j = await res.json();
    if (j.ok) EL.out.textContent = j.text || "(no content)";
    else EL.out.textContent = `Error: ${j.error || "unknown error"}`;
  } catch (err) {
    console.error("[history]", err);
    EL.out.textContent = "Failed to generate history.";
  } finally {
    btns.forEach(b => b.disabled = false);
  }
}

/* ---------- 飛行與 3D pin（無回彈） ---------- */
function cancelFlightIfAny() {
  if (isFlying) {
    flyAnim = null;
    isFlying = false;
    controls.enabled = true;
    controls.update();
  }
}

// ====== 彩色定位 PIN（含發光與脈衝圈） ======
function createPin() {
  const g = new THREE.Group();

  // 立體針身（雙色）
  const stemH = 0.18, stemR = 0.012;
  const stem = new THREE.Mesh(
    new THREE.CylinderGeometry(stemR, stemR, stemH, 24),
    new THREE.MeshPhysicalMaterial({ color: 0x00d2ff, roughness: 0.35, metalness: 0.3 })
  );
  stem.position.y = stemH / 2;

  // 球形針頭（亮面）
  const headR = 0.055;
  const head = new THREE.Mesh(
    new THREE.SphereGeometry(headR, 28, 28),
    new THREE.MeshPhysicalMaterial({ color: 0xff4dd2, roughness: 0.2, metalness: 0.5, emissive: 0x441122, emissiveIntensity: 0.35 })
  );
  head.position.y = stemH + headR;

  // 底座薄環
  const base = new THREE.Mesh(
    new THREE.CylinderGeometry(0.02, 0.02, 0.006, 32),
    new THREE.MeshPhysicalMaterial({ color: 0xffffff, roughness: 0.6, metalness: 0.1 })
  );
  base.position.y = 0.003;

  // 針頭外發光（sprite）
  const glowTex = makeRadialGlowTexture(256, 256);
  const glow = new THREE.Sprite(new THREE.SpriteMaterial({ map: glowTex, transparent: true, depthWrite: false, opacity: 0.9 }));
  glow.scale.set(0.26, 0.26, 0.26);
  glow.position.y = stemH + headR;

  // 地表脈衝圈（沿法線展開）
  const pulse = new THREE.Mesh(
    new THREE.RingGeometry(0.05, 0.001, 64),
    new THREE.MeshBasicMaterial({ color: 0x00e0ff, transparent: true, opacity: 0.75, side: THREE.DoubleSide, depthWrite: false })
  );
  pulse.rotation.x = -Math.PI / 2;  // 初始朝上，後續用四元數對齊法線
  pulse.userData = { t0: performance.now(), speed: 1.2 };

  g.add(base, stem, head, glow, pulse);
  g.userData = { glow, pulse };
  g.visible = false;
  return g;
}
// 針對某方向放置 pin（dir 為單位向量）
function setPinAtDirection(dir) {
  const yAxis = new THREE.Vector3(0, 1, 0);
  const tipOffset = 0.01;
  pin.position.copy(dir).multiplyScalar(RADIUS + tipOffset);
  pin.quaternion.setFromUnitVectors(yAxis, dir);

  // 讓脈衝圈貼著地表並沿切平面展開
  const pulse = pin.userData.pulse;
  const quat = new THREE.Quaternion().setFromUnitVectors(new THREE.Vector3(0, 1, 0), dir);
  pulse.quaternion.copy(quat);
  pulse.position.copy(dir).multiplyScalar(RADIUS + 0.001);

  pin.visible = true;
}

// 建立中心亮到邊緣透明的放射狀貼圖（給 glow）
function makeRadialGlowTexture(w, h) {
  const c = document.createElement('canvas');
  c.width = w; c.height = h;
  const ctx = c.getContext('2d');
  const grad = ctx.createRadialGradient(w/2, h/2, 0, w/2, h/2, Math.max(w,h)/2);
  grad.addColorStop(0.0, 'rgba(255, 255, 255, 0.95)');
  grad.addColorStop(0.3, 'rgba(255, 128, 220, 0.55)');
  grad.addColorStop(0.6, 'rgba(0, 210, 255, 0.35)');
  grad.addColorStop(1.0, 'rgba(0, 0, 0, 0.0)');
  ctx.fillStyle = grad;
  ctx.fillRect(0, 0, w, h);
  const tex = new THREE.CanvasTexture(c);
  tex.needsUpdate = true;
  return tex;
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

/* ---------- 底圖 + ID 貼圖（UV 一致） ---------- */
async function buildPoliticalBaseAndPicker(url, opt) {
  const geo = await fetch(url).then(r => r.json());
  const W = opt.width || 2048, H = opt.height || 1024;

  // === 底圖畫布 ===
  const base = document.createElement('canvas'); base.width = W; base.height = H;
  const bctx = base.getContext('2d');

  // 海洋：垂直漸層（深→淺）
  const oceanGrad = bctx.createLinearGradient(0, 0, 0, H);
  oceanGrad.addColorStop(0,   '#0a2236');
  oceanGrad.addColorStop(0.5, '#0f2f4a');
  oceanGrad.addColorStop(1,   '#133a58');
  bctx.fillStyle = oceanGrad; bctx.fillRect(0, 0, W, H);

  // 經緯網（每 15 度），極淡
  bctx.strokeStyle = 'rgba(255,255,255,0.06)';
  bctx.lineWidth = 0.6;
  for (let lon = -180; lon <= 180; lon += 15) {
    const x = ((lon + 180) / 360) * W;
    bctx.beginPath(); bctx.moveTo(x, 0); bctx.lineTo(x, H); bctx.stroke();
  }
  for (let lat = -75; lat <= 75; lat += 15) {
    const y = ((90 - lat) / 180) * H;
    bctx.beginPath(); bctx.moveTo(0, y); bctx.lineTo(W, y); bctx.stroke();
  }

  // === ID 貼圖（國家拾取用） ===
  const idc = document.createElement('canvas'); idc.width = W; idc.height = H;
  const ictx = idc.getContext('2d', { willReadFrequently: true });
  ictx.imageSmoothingEnabled = false;
  ictx.fillStyle = 'rgb(0,0,0)'; ictx.fillRect(0, 0, W, H); // id=0 代表海

  const idMap = new Map(); let nextId = 1;

  // 大洲調色盤
  const CONT_COLORS = {
    'africa'         : '#7fb069',
    'europe'         : '#f7b267',
    'asia'           : '#f4845f',
    'north america'  : '#6db1ff',
    'south america'  : '#b089f7',
    'oceania'        : '#4fd1c5',
    'australia'      : '#4fd1c5',
    'antarctica'     : '#b9c2d0'
  };
  const pickContinent = (p) => {
    const c = (p?.CONTINENT || p?.continent || p?.region_un || p?.REGION_UN || '').toString().toLowerCase().trim();
    if (CONT_COLORS[c]) return CONT_COLORS[c];
    // 例外對映
    if (c === 'latin america and the caribbean') return CONT_COLORS['south america'];
    if (c === 'asia-pacific') return CONT_COLORS['asia'];
    return null;
  };
  const hashColor = (s, sat=65, light=55) => {
    // 國碼雜湊備援
    let h = 0; for (let i=0;i<s.length;i++){h=(h*31 + s.charCodeAt(i))|0;}
    h = (h>>>0)%360;
    return `hsl(${h} ${sat}% ${light}%)`;
  };

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
    if (mode === 'fill') ctx.fill('evenodd'); else ctx.stroke();
  };

  // 國界樣式
  bctx.lineWidth = opt.borderWidth ?? 0.9;
  bctx.strokeStyle = opt.border || 'rgba(255,255,255,0.85)';

  for (const f of geo.features) {
    const g = f.geometry; if (!g) continue;

    // 依大洲選填色，否則用國碼雜湊
    const contFill = pickContinent(f.properties);
    const fillColor = contFill || hashColor(countryISO3(f.properties) || countryName(f.properties));
    bctx.fillStyle = fillColor;

    // 給 ID 圖一個遞增顏色編碼
    const id = nextId++; const r = id & 255, g8 = (id >> 8) & 255, b = (id >> 16) & 255;
    const idColor = `rgb(${r},${g8},${b})`;
    idMap.set((r) | (g8 << 8) | (b << 16), f);

    if (g.type === 'Polygon') {
      for (const s of [-W, 0, W]) drawRings(bctx, g.coordinates, s, 'fill');
      for (const s of [-W, 0, W]) drawRingsBorder(bctx, g.coordinates[0], s);
      ictx.save(); ictx.fillStyle = idColor;
      for (const s of [-W, 0, W]) drawRings(ictx, g.coordinates, s, 'fill');
      ictx.restore();

    } else if (g.type === 'MultiPolygon') {
      for (const poly of g.coordinates) {
        for (const s of [-W, 0, W]) drawRings(bctx, poly, s, 'fill');
        for (const s of [-W, 0, W]) drawRingsBorder(bctx, poly[0], s);
        ictx.save(); ictx.fillStyle = idColor;
        for (const s of [-W, 0, W]) drawRings(ictx, poly, s, 'fill');
        ictx.restore();
      }
    }
  }

  // 邊界描邊的子函式（單一外環）
  function drawRingsBorder(ctx, outerRing, shiftPx) {
    ctx.beginPath();
    const outer = unwrapRing(outerRing);
    outer.forEach(([L, lat], i) => {
      const x = ((L + 180) / 360) * W + shiftPx;
      const y = ((90 - lat) / 180) * H;
      if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
    });
    ctx.closePath(); ctx.stroke();
  }

  // 轉 CanvasTexture
  const baseTexture = new THREE.CanvasTexture(base);
  baseTexture.anisotropy = 4;
  baseTexture.wrapS = THREE.RepeatWrapping;
  baseTexture.wrapT = THREE.RepeatWrapping;
  baseTexture.needsUpdate = true;

  const idPicker = {
    W, H, canvas: idc, ctx: ictx, idMap,
    pickUV: (u, v) => {
      let x = Math.floor(((u % 1 + 1) % 1) * W);
      let y = Math.floor((1 - ((v % 1 + 1) % 1)) * H);
      x = Math.min(Math.max(x, 0), W - 1);
      y = Math.min(Math.max(y, 0), H - 1);
      const p = ictx.getImageData(x, y, 1, 1).data;
      const colorInt = (p[0]) | (p[1] << 8) | (p[2] << 16);
      const feature = idMap.get(colorInt);
      if (!feature) return null;
      return { feature, name: countryName(feature.properties), iso3: countryISO3(feature.properties) };
    }
  };

  return { baseTexture, idPicker, width: W, height: H };
}

/* ---------- 高亮層（透明第二球） ---------- */
function makeHighlightLayer(W, H) {
  const canvas = document.createElement('canvas');
  canvas.width = W; canvas.height = H;
  const ctx = canvas.getContext('2d');

  const texture = new THREE.CanvasTexture(canvas);
  texture.wrapS = THREE.RepeatWrapping;
  texture.wrapT = THREE.RepeatWrapping;
  // 與底圖相同方向（flipY=true）
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

/* ---------- 共用工具 ---------- */
function makeStarfieldTexture({ w=2048, h=1024, stars=3000, nebula=0.0 } = {}) {
  const c = document.createElement('canvas'); c.width = w; c.height = h;
  const ctx = c.getContext('2d');

  // 背景：宇宙黑到深藍微漸層
  const g = ctx.createLinearGradient(0, 0, 0, h);
  g.addColorStop(0, '#010207'); 
  g.addColorStop(1, '#02030b');
  ctx.fillStyle = g; ctx.fillRect(0, 0, w, h);

  // 隨機星點
  for (let i = 0; i < stars; i++) {
    const x = Math.random() * w, y = Math.random() * h;
    const r = Math.random() * 1.2 + 0.2;
    const a = Math.random() * 0.6 + 0.4;
    const hue = (Math.random() < 0.15) ? (200 + Math.random()*40) : (0 + Math.random()*60);
    ctx.fillStyle = `hsla(${hue}, 80%, 85%, ${a})`;
    ctx.beginPath(); ctx.arc(x, y, r, 0, Math.PI*2); ctx.fill();
  }

  // 淡淡星雲（可選）
  if (nebula > 0) {
    const blobs = Math.floor(6 * nebula) + 2;
    for (let i=0; i<blobs; i++) {
      const nx = Math.random()*w, ny = Math.random()*h;
      const nr = Math.random()*200 + 120;
      const grd = ctx.createRadialGradient(nx, ny, 0, nx, ny, nr);
      grd.addColorStop(0, 'rgba(150, 80, 255, 0.08)');
      grd.addColorStop(1, 'rgba(0,0,0,0)');
      ctx.fillStyle = grd; ctx.beginPath();
      ctx.arc(nx, ny, nr, 0, Math.PI*2); ctx.fill();
    }
  }

  const tex = new THREE.CanvasTexture(c);
  tex.needsUpdate = true;
  return tex;
}

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

function escapeHtml(s) {
  return (s || "").replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}

// 若 city 含非英文字，嘗試用 en-Wikipedia 取英文標題；失敗就用原字串
async function toLatinCityForEvents(city) {
  if (!city) return city;
  if (/[A-Za-z]/.test(city)) return city;  // 已是英文

  try {
    const q = new URLSearchParams({ name: city, lang: 'en' });
    const res = await fetch(`/api/placeinfo?${q.toString()}`, { cache: 'no-store' });
    if (res.ok) {
      const j = await res.json();
      if (j?.ok && j.title) return j.title;
    }
  } catch (e) {
    console.warn('[events] toLatinCityForEvents failed:', e);
  }
  return city;
}

function renderEvents(items = []) {
  EV.list.innerHTML = "";
  if (!items.length) {
    const empty = document.createElement('div');
    empty.style.padding = '12px';
    empty.style.color = '#cbd6e6';
    empty.textContent = 'No results.';
    EV.list.appendChild(empty);
    return;
  }
  for (const it of items) {
    const a = document.createElement('a');
    a.className = 'event-card';
    a.href = it.url || '#';
    a.target = '_blank'; a.rel = 'noopener';
    a.innerHTML = `
      <div class="thumb">
        <img src="${escapeHtml(it.image || '/static/assets/default.jpg')}" alt="">
      </div>
      <div class="body">
        <h3>${escapeHtml(it.title || '(untitled)')}</h3>
        <p>${escapeHtml(it.summary || '')}</p>
        <div class="meta">${escapeHtml([it.author, it.type].filter(Boolean).join(' · '))}</div>
      </div>
    `;
    EV.list.appendChild(a);
  }
}

async function fetchEventsFor(place, only_textual = true) {
  const p = (place || "").trim();
  if (!p) return { ok: false, items: [], error: "empty place" };

  const res = await fetch('/api/history/events', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ place: p, only_textual })
  });
  if (!res.ok) return { ok: false, items: [], error: `HTTP ${res.status}` };

  const j = await res.json();
  const items = Array.isArray(j.items) ? j.items : [];
  return { ok: true, items, query: j.query || p };
}

/* ---------- 逐幀 ---------- */
function animate(now) {
  requestAnimationFrame(animate);
  if (!isFlying) controls.update();
  if (flyAnim) flyAnim(now);
  renderer.render(scene, camera);
}

// === Toggle side panel ===
const btnToggle = document.getElementById('toggle-side');
if (btnToggle) {
  btnToggle.addEventListener('click', () => {
    document.body.classList.toggle('side-collapsed');
    // 箭頭方向變換
    btnToggle.textContent = document.body.classList.contains('side-collapsed') ? '❮' : '❯';
  });
}

if (EV.fab) {
  EV.fab.addEventListener('click', async () => {
    EV.fab.classList.remove('pulse');

    // 打開面板 & 先顯示 Loading
    EV.panel.classList.add('open');
    EV.panel.setAttribute('aria-hidden', 'false');
    EV.list.innerHTML = '<div style="padding:12px;color:#cbd6e6">Loading…</div>';

    const city = (lastCtx.city || '').trim();
    const country = (lastCtx.country || '').trim();

    if (!city && !country) {
      EV.list.innerHTML = '<div style="padding:12px;color:#cbd6e6">請先點擊地球選擇一座城市或國家，再試一次。</div>';
      return;
    }

    let data = null;
    let usedFallback = false;

    // 1) 先用「城市」查
    if (city) {
      data = await fetchEventsFor(city, true);
      const hasCityResults = data && data.ok && data.items.length > 0;

      // 2) 城市失敗或沒結果 → 用「國家」查
      if (!hasCityResults && country) {
        usedFallback = true;
        data = await fetchEventsFor(country, true);
      }
    } else {
      // 沒城市，但有國家 → 直接用「國家」
      usedFallback = true;
      data = await fetchEventsFor(country, true);
    }

    // 3) 成功與否處理
    if (!(data && data.ok)) {
      EV.list.innerHTML = '<div style="padding:12px;color:#ff9aa2">載入失敗，請稍後再試。</div>';
      return;
    }

    // 4) 渲染結果
    renderEvents(data.items);

    // 5) 若啟用 fallback，在列表頂端加一行提示（不動 CSS 也能好看）
    if (usedFallback) {
      const note = document.createElement('div');
      note.style.cssText =
        'padding:8px 10px;margin:6px 8px 10px;' +
        'border:1px solid rgba(255,255,255,0.08);background:rgba(255,255,255,0.05);' +
        'border-radius:8px;color:#9fb5d1;font-size:12px;';
      if (city) {
        note.textContent = `No result of'${city}', use '${country}' to search.`;
      } else {
        note.textContent = `use country '${country}' to search.`;
      }
      EV.list.prepend(note);
    }

    // 6) 完全沒資料時的提示（renderEvents 會顯示 No results.，這裡再補中文說明）
    if (data.items.length === 0) {
      const tip = document.createElement('div');
      tip.style.cssText = 'padding:8px 10px;margin:6px 8px;color:#cbd6e6;font-size:12px;';
      tip.textContent = '目前沒有符合的文章，換個城市或國家再試試。';
      EV.list.appendChild(tip);
    }
  });
}
if (EV.close) {
  EV.close.addEventListener('click', () => {
    EV.panel.classList.remove('open');
    EV.panel.setAttribute('aria-hidden', 'true');
  });
}
