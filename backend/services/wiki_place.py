# backend/services/wiki_place.py
from __future__ import annotations
from typing import Optional, Dict, Any, List, Tuple
from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse
from dotenv import load_dotenv
import os, requests, urllib.parse, re

load_dotenv()
router = APIRouter()

# ---------- HTTP helpers ----------
APP_UA = "time-globe/0.5 (wiki-place module)"
UA = {"User-Agent": APP_UA}

def _proxies() -> Optional[Dict[str, str]]:
    pu = os.getenv("PROXY_URL")
    if pu:
        return {"http": pu, "https": pu}
    hp, sp = os.getenv("HTTP_PROXY"), os.getenv("HTTPS_PROXY")
    if hp or sp:
        return {"http": hp or sp, "https": sp or hp}
    return None

PROXIES = _proxies()

def _req_get(url: str, *, params=None, headers=None, timeout=15):
    h = {**UA, **(headers or {})}
    return requests.get(url, params=params, headers=h, timeout=timeout, proxies=PROXIES)

def _clean_url(u: Optional[str]) -> Optional[str]:
    if not u: return None
    return u.replace("http://", "https://")

# ---------- Wikipedia endpoints ----------
WIKI_ACTION   = "https://{lang}.wikipedia.org/w/api.php"
WIKI_SUMMARY  = "https://{lang}.wikipedia.org/api/rest_v1/page/summary/{title}"

# ---------- Wikipedia primitives ----------
def wiki_search_title(query: str, lang: str, limit: int = 1) -> Optional[str]:
    """
    Use MediaWiki action API to fetch the best title for a query.
    """
    url = WIKI_ACTION.format(lang=lang)
    params = {
        "action": "query", "format": "json",
        "list": "search", "srlimit": max(1, int(limit)),
        "srsearch": query,
        "srprop": ""
    }
    r = _req_get(url, params=params, timeout=12)
    if not r.ok:
        return None
    items = (r.json().get("query", {}).get("search") or [])
    if not items:
        return None
    return items[0].get("title") or None

def wiki_summary(lang: str, title: str) -> Dict[str, Any]:
    """
    Use REST Summary API to get description, extract, images, url, and coordinates.
    """
    path = urllib.parse.quote(title.replace(" ", "_"))
    url  = WIKI_SUMMARY.format(lang=lang, title=path)
    r = _req_get(url, timeout=12)
    if not r.ok:
        return {}
    js = r.json()
    data = {
        "title": js.get("title") or title,
        "description": js.get("description"),
        "summary": (js.get("extract") or "").strip(),
        "thumbnail": _clean_url((js.get("thumbnail") or {}).get("url")),
        "original_image": _clean_url((js.get("originalimage") or {}).get("source")),
        "url": _clean_url((js.get("content_urls", {}).get("desktop", {}) or {}).get("page")),
        "lat": (js.get("coordinates") or {}).get("lat"),
        "lon": (js.get("coordinates") or {}).get("lon"),
    }
    return data

def wiki_pageprops_wikidata(lang: str, title: str) -> Optional[str]:
    """
    Fetch wikibase_item (Wikidata QID) via pageprops.
    """
    url = WIKI_ACTION.format(lang=lang)
    params = {
        "action": "query", "format": "json",
        "prop": "pageprops",
        "titles": title,
        "ppprop": "wikibase_item"
    }
    r = _req_get(url, params=params, timeout=12)
    if not r.ok:
        return None
    pages = (r.json().get("query", {}).get("pages") or {})
    for _, pg in pages.items():
        qid = (pg.get("pageprops") or {}).get("wikibase_item")
        if qid:
            return qid
    return None

# ---------- Aggregation ----------
def get_place_basic(place: str, lang: str = "zh") -> Dict[str, Any]:
    """
    Resolve a place name to a Wikipedia summary with images and (if available) coordinates and Wikidata QID.
    Fallback chain: search in `lang` -> summary in `lang` -> if missing, search+summary in `en`.
    """
    used_lang = lang
    title = wiki_search_title(place, lang=lang, limit=1)

    if not title:
        # fallback to English search
        title = wiki_search_title(place, lang="en", limit=1)
        used_lang = "en" if title else lang

    if not title:
        return {"ok": False, "query": place, "lang": used_lang, "error": "no_title_found"}

    # Try summary in used_lang (zh preferred), fallback to English summary
    data = wiki_summary(used_lang, title)
    if not data.get("summary"):
        data = wiki_summary("en", title)
        used_lang = "en"

    # Attach Wikidata QID (try used_lang first, then en)
    qid = wiki_pageprops_wikidata(used_lang, data.get("title") or title) or \
          wiki_pageprops_wikidata("en", data.get("title") or title)

    out = {
        "ok": True,
        "source": "wikipedia",
        "query": place,
        "lang": used_lang,
        "title": data.get("title"),
        "description": data.get("description"),
        "summary": data.get("summary"),
        "url": data.get("url"),
        "thumbnail": data.get("thumbnail"),
        "original_image": data.get("original_image"),
        "lat": data.get("lat"),
        "lon": data.get("lon"),
        "wikidata_qid": qid,
    }
    return out

# ---------- FastAPI route ----------
@router.get("/placeinfo", response_class=JSONResponse)
def placeinfo_api(
    name: str = Query(..., description="Place name (city/region/country)"),
    lang: str = Query("zh", description="Preferred language, e.g., zh or en"),
):
    return JSONResponse(get_place_basic(name, lang))

# ---------- Local smoke test ----------
if __name__ == "__main__":
    info = get_place_basic("新北市", lang="zh")
    print(info)
