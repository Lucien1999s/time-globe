# backend/services/wiki_place.py
from __future__ import annotations
from typing import Optional, Dict, Any, List, Tuple
from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse
from dotenv import load_dotenv
import os, urllib.parse, math, time, asyncio

import httpx  # ← 並發 HTTP

load_dotenv()
router = APIRouter()

# ===================== Config =====================
APP_UA = "time-globe/0.7 (wiki-place turbo)"
HTTP_TIMEOUT = 6.0             # 單請求超時（秒）
SEARCH_LIMIT = 6               # 每個 query 拿回的標題數
CANDIDATE_MAX = 8              # 總候選上限（合併去重後）
WIKIDATA_REFINE_TOPK = 2       # 初步打分後，只對前 K 名查 Wikidata
CACHE_TTL = 24 * 3600          # 24h

# ===================== HTTP Client =====================
def _proxies() -> Optional[Dict[str, str]]:
    pu = os.getenv("PROXY_URL")
    if pu:
        return {"http://": pu, "https://": pu}
    hp, sp = os.getenv("HTTP_PROXY"), os.getenv("HTTPS_PROXY")
    if hp or sp:
        return {"http://": hp or sp, "https://": sp or hp}
    return None

HTTP_HEADERS = {"User-Agent": APP_UA}
_client: httpx.AsyncClient | None = None

async def get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(
            headers=HTTP_HEADERS,
            proxy=_proxies(),
            timeout=httpx.Timeout(HTTP_TIMEOUT),
        )
    return _client

# ===================== Simple TTL Cache =====================
_cache: Dict[str, Tuple[float, Any]] = {}

def _ck(*parts: Any) -> str:
    return "|".join(map(str, parts))

def cache_get(key: str):
    item = _cache.get(key)
    if not item: return None
    ts, val = item
    if time.time() - ts > CACHE_TTL:
        _cache.pop(key, None)
        return None
    return val

def cache_set(key: str, val: Any):
    _cache[key] = (time.time(), val)

# ===================== Utils =====================
def _norm(s: Optional[str]) -> str:
    return (s or "").strip()

def _lc(s: Optional[str]) -> str:
    return _norm(s).lower()

def _clean_url(u: Optional[str]) -> Optional[str]:
    if not u: return None
    return u.replace("http://", "https://")

def haversine_km(lat1, lon1, lat2, lon2) -> float:
    if lat1 is None or lon1 is None or lat2 is None or lon2 is None:
        return float("inf")
    R = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(dlmb/2)**2
    return 2*R*math.asin(math.sqrt(a))

# ===================== Wikipedia / Wikidata endpoints =====================
WIKI_ACTION   = "https://{lang}.wikipedia.org/w/api.php"
WIKI_SUMMARY  = "https://{lang}.wikipedia.org/api/rest_v1/page/summary/{title}"
WIKIDATA_ENTITY = "https://www.wikidata.org/wiki/Special:EntityData/{qid}.json"

# ---------- primitives (async, with cache) ----------
async def wiki_search_titles(query: str, lang: str, limit: int = SEARCH_LIMIT) -> List[str]:
    key = _ck("search", lang, query, limit)
    hit = cache_get(key)
    if hit is not None:
        return hit
    url = WIKI_ACTION.format(lang=lang)
    params = {
        "action": "query", "format": "json",
        "list": "search",
        "srsearch": query,
        "srlimit": max(1, min(int(limit), 20)),
        "srnamespace": 0,
        "srinfo": "suggestion",
        "srprop": ""
    }
    cli = await get_client()
    try:
        r = await cli.get(url, params=params)
        if r.is_success:
            items = (r.json().get("query", {}).get("search") or [])
            titles = [it.get("title") for it in items if it.get("title")]
        else:
            titles = []
    except Exception:
        titles = []
    cache_set(key, titles)
    return titles

async def wiki_summary(lang: str, title: str) -> Dict[str, Any]:
    key = _ck("summary", lang, title)
    hit = cache_get(key)
    if hit is not None:
        return hit
    path = urllib.parse.quote((_norm(title)).replace(" ", "_"))
    url  = WIKI_SUMMARY.format(lang=lang, title=path)
    cli = await get_client()
    try:
        r = await cli.get(url)
        if not r.is_success:
            cache_set(key, {})
            return {}
        js = r.json()
        data = {
            "title": js.get("title") or title,
            "description": js.get("description"),
            "summary": _norm(js.get("extract")),
            "thumbnail": _clean_url((js.get("thumbnail") or {}).get("url")),
            "original_image": _clean_url((js.get("originalimage") or {}).get("source")),
            "url": _clean_url(((js.get("content_urls", {}) or {}).get("desktop", {}) or {}).get("page")),
            "lat": (js.get("coordinates") or {}).get("lat"),
            "lon": (js.get("coordinates") or {}).get("lon"),
            "type": js.get("type"),  # 'standard' | 'disambiguation' | ...
        }
    except Exception:
        data = {}
    cache_set(key, data)
    return data

async def wiki_pageprops_wikidata(lang: str, title: str) -> Optional[str]:
    key = _ck("pageprops", lang, title)
    hit = cache_get(key)
    if hit is not None:
        return hit
    url = WIKI_ACTION.format(lang=lang)
    params = {
        "action": "query", "format": "json",
        "prop": "pageprops",
        "titles": title,
        "ppprop": "wikibase_item"
    }
    cli = await get_client()
    try:
        r = await cli.get(url, params=params)
        if not r.is_success:
            cache_set(key, None)
            return None
        pages = (r.json().get("query", {}).get("pages") or {})
        qid = None
        for _, pg in pages.items():
            qid = (pg.get("pageprops") or {}).get("wikibase_item")
            if qid: break
    except Exception:
        qid = None
    cache_set(key, qid)
    return qid

async def wikidata_instanceof(qid: str) -> List[str]:
    if not qid:
        return []
    key = _ck("wdP31", qid)
    hit = cache_get(key)
    if hit is not None:
        return hit
    url = WIKIDATA_ENTITY.format(qid=qid)
    cli = await get_client()
    try:
        r = await cli.get(url)
        if not r.is_success:
            cache_set(key, [])
            return []
        js = r.json()
        ent = (js.get("entities") or {}).get(qid) or {}
        claims = ent.get("claims") or {}
        inst = claims.get("P31") or []
        out = []
        for c in inst:
            v = (((c.get("mainsnak") or {}).get("datavalue") or {}).get("value") or {})
            q = v.get("id")
            if q:
                out.append(q)
    except Exception:
        out = []
    cache_set(key, out)
    return out

# ---------- scoring ----------
_ALLOWED_PLACE_QIDS = {
    "Q486972","Q515","Q6256","Q82794","Q56061","Q133442","Q15642541","Q70208","Q1907114","Q1799794","Q5107",
}
_BANNED_QIDS = {"Q5","Q11424","Q482994","Q5398426","Q571","Q13442814","Q202444","Q101352"}

def _text_contains(hay: str, needle: Optional[str]) -> bool:
    h = _lc(hay); n = _lc(needle)
    return bool(n) and (n in h)

def coarse_score(idx: int, data: Dict[str, Any], ctx: Dict[str, Any]) -> float:
    # 初步打分（不含 Wikidata）
    score = max(0, 24 - idx * 4)
    title = _norm(data.get("title"))
    desc  = _norm(data.get("description"))
    summ  = _norm(data.get("summary"))
    blob  = f"{title}\n{desc}\n{summ}"

    if _text_contains(title, ctx.get("city")) or _text_contains(desc, ctx.get("city")):
        score += 20
    if _text_contains(blob, ctx.get("admin1")):
        score += 12
    if _text_contains(blob, ctx.get("country")) or _text_contains(title, ctx.get("country")):
        score += 8
    if _text_contains(title, ctx.get("query_name")):
        score += 4

    if (data.get("type") or "").lower() == "disambiguation":
        score -= 60

    km = haversine_km(ctx.get("lat"), ctx.get("lon"), data.get("lat"), data.get("lon"))
    if km < 10:   score += 30
    elif km < 40: score += 18
    elif km < 150:score += 9
    elif km < 500:score += 3
    elif km > 2000: score -= 4

    if data.get("lat") is not None and data.get("lon") is not None:
        score += 4

    return score

def refine_score(base: float, qids: List[str]) -> float:
    sc = base
    if any(q in _BANNED_QIDS for q in qids): sc -= 100
    if any(q in _ALLOWED_PLACE_QIDS for q in qids): sc += 28
    return sc

# ---------- core resolver (async) ----------
async def resolve_best_wiki(place: str, lang_pref: str, ctx: Dict[str, Any]) -> Tuple[Optional[Dict[str, Any]], str]:
    async def candidates_for(lang: str) -> List[str]:
        queries = [place]
        if ctx.get("admin1"):  queries.append(f"{place} {ctx['admin1']}")
        if ctx.get("country"): queries.append(f"{place} {ctx['country']}")
        # 去重後合併
        results = []
        seen = set()
        for q in queries:
            for t in await wiki_search_titles(q, lang=lang, limit=SEARCH_LIMIT):
                if t not in seen:
                    seen.add(t); results.append(t)
                if len(results) >= CANDIDATE_MAX:
                    break
            if len(results) >= CANDIDATE_MAX:
                break
        return results

    titles = await candidates_for(lang_pref)
    used_lang = lang_pref
    if not titles and lang_pref != "en":
        titles = await candidates_for("en")
        used_lang = "en"
    if not titles:
        return None, used_lang

    # 批量抓 summary（used_lang），空摘要才補抓 en
    summaries = await asyncio.gather(*[wiki_summary(used_lang, t) for t in titles])
    need_en = [i for i, d in enumerate(summaries) if not d.get("summary") and used_lang != "en"]
    if need_en:
        en_sums = await asyncio.gather(*[wiki_summary("en", titles[i]) for i in need_en])
        for j, i in enumerate(need_en):
            if en_sums[j].get("summary"):
                summaries[i] = en_sums[j]

    # 初步打分（不查 wikidata）
    bases = [coarse_score(i, summaries[i], {**ctx, "query_name": place}) for i in range(len(titles))]
    order = sorted(range(len(titles)), key=lambda i: bases[i], reverse=True)

    # 只對前 K 名補 Wikidata 類型，做細修分
    K = min(WIKIDATA_REFINE_TOPK, len(order))
    refined_scores = bases[:]
    if K > 0:
        top_idx = order[:K]
        # 先抓 pageprops(QID)
        qids = await asyncio.gather(*[
            wiki_pageprops_wikidata(used_lang, summaries[i].get("title") or titles[i]) for i in top_idx
        ])
        # 再抓 P31
        p31s = await asyncio.gather(*[
            wikidata_instanceof(q or "") for q in qids
        ])
        for j, i in enumerate(top_idx):
            refined_scores[i] = refine_score(bases[i], p31s[j])

    # 選最高分
    best_i = max(range(len(titles)), key=lambda i: refined_scores[i])
    best = summaries[best_i]
    # 回傳資料
    return (best if best and best.get("summary") else None), used_lang

# ---------- public API (async) ----------
async def get_place_basic(place: str,
                          lang: str = "zh",
                          *,
                          country: Optional[str] = None,
                          admin1: Optional[str] = None,
                          city: Optional[str] = None,
                          lat: Optional[float] = None,
                          lon: Optional[float] = None) -> Dict[str, Any]:
    ctx = {"country": country, "admin1": admin1, "city": city, "lat": lat, "lon": lon}
    data, used_lang = await resolve_best_wiki(place, lang, ctx)

    if not data:
        # 最終退路：單一標題 + 單次 summary
        titles = await wiki_search_titles(place, lang or "zh", limit=1)
        if not titles and lang != "en":
            titles = await wiki_search_titles(place, "en", limit=1)
            used_lang = "en"
        if titles:
            data = await wiki_summary(used_lang, titles[0])

    if not data:
        return {"ok": False, "query": place, "lang": used_lang, "error": "no_result"}

    # 最後補一次 QID（有 cache，幾乎零成本）
    qid = await wiki_pageprops_wikidata(used_lang, data.get("title") or place) or \
          await wiki_pageprops_wikidata("en",     data.get("title") or place)

    return {
        "ok": True,
        "source": "wikipedia",
        "query": place,
        "lang": used_lang,
        "title": data.get("title") or place,
        "description": data.get("description"),
        "summary": data.get("summary"),
        "url": data.get("url"),
        "thumbnail": data.get("thumbnail"),
        "original_image": data.get("original_image"),
        "lat": data.get("lat"),
        "lon": data.get("lon"),
        "wikidata_qid": qid,
    }

# ---------- FastAPI route (async) ----------
@router.get("/placeinfo", response_class=JSONResponse)
async def placeinfo_api(
    name: str = Query(..., description="Place name (locality/district/city)"),
    lang: str = Query("zh", description="Preferred language code, e.g., zh/en/ja/ko/es"),
    country: Optional[str] = Query(None),
    admin1:  Optional[str] = Query(None, description="State/Province/County"),
    city:    Optional[str] = Query(None, description="City/Town/Village"),
    lat:     Optional[float] = Query(None),
    lon:     Optional[float] = Query(None),
):
    data = await get_place_basic(name, lang, country=country, admin1=admin1, city=city, lat=lat, lon=lon)
    return JSONResponse(data)

# ---------- Local smoke test ----------
if __name__ == "__main__":
    import asyncio
    async def _go():
        info = await get_place_basic("信義", lang="zh", country="台灣", admin1="台北市", city="信義區", lat=25.033, lon=121.565)
        print(info)
    asyncio.run(_go())
