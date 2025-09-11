from __future__ import annotations

import json
import re
from typing import Dict, List, Optional
from urllib.parse import urlencode, urljoin

import requests
from bs4 import BeautifulSoup, NavigableString, Tag


BASE_URL = "https://www.worldhistory.org"


def _clean_text(s: str) -> str:
    """壓縮空白與換行，保留句內單一空白。"""
    return re.sub(r"\s+", " ", (s or "").strip())


def _extract_type_and_author(ci_type_name_el: Optional[Tag]) -> (Optional[str], Optional[str]):
    """
    節點長相大致為：
      <div class="ci_type_name">
        Image <span class="ci_author">by Taipei: National Palace Museum</span>
      </div>
    需要把 type 與 author 拆開。
    """
    if not ci_type_name_el:
        return None, None

    author = None
    author_el = ci_type_name_el.select_one(".ci_author")
    if author_el:
        author = _clean_text(author_el.get_text())
        # 移除 "by " 開頭的字樣
        author = re.sub(r"^\s*by\s+", "", author, flags=re.I)

    # 拿掉 author 子節點後取剩餘純文字當型別名稱
    tmp = ci_type_name_el.encode_contents().decode("utf-8")
    if author_el:
        tmp = tmp.replace(str(author_el), "")
    type_text = BeautifulSoup(tmp, "html.parser").get_text()
    return _clean_text(type_text), author


def _parse_search_html(html: str, only_textual: bool = True, base_url: str = BASE_URL) -> Dict:
    soup = BeautifulSoup(html, "html.parser")

    # 解析查詢關鍵字
    query = None
    q_el = soup.select_one('#content_main form input[name="q"]')
    if q_el and q_el.get("value"):
        query = q_el.get("value")

    items: List[Dict] = []
    for a in soup.select("#ci_search_results .ci_list .content_item"):
        href = a.get("href") or ""
        url = urljoin(base_url, href)

        # 標題
        h3 = a.select_one(".ci_header h3")
        title = _clean_text(h3.get_text()) if h3 else None

        # 內容型別 + 作者
        type_name_el = a.select_one(".ci_type_name")
        type_name, author = _extract_type_and_author(type_name_el)

        # type id
        # 1=Definition, 2=Article, 3=Image (據頁面 data-ci-type-id 屬性)
        ci_type_id_raw = a.get("data-ci-type-id")
        try:
            ci_type_id = int(ci_type_id_raw) if ci_type_id_raw is not None else None
        except ValueError:
            ci_type_id = None

        # 只要文字內容的話，過濾掉非 1/2
        if only_textual and (ci_type_id not in (1, 2)):
            continue

        # 摘要
        prev = a.select_one(".ci_preview")
        summary = _clean_text(prev.get_text(" ")) if prev else None

        # 縮圖
        img = a.select_one("img.ci_image")
        image_url = img.get("src") if img else None
        if image_url:
            image_url = urljoin(base_url, image_url)

        if title and url:
            items.append({
                "title": title,
                "summary": summary,
                "url": url,
                "image": image_url,
                "author": author,
                "type": type_name,
                "ci_type_id": ci_type_id,
            })

    # 解析下一頁
    next_link_el = soup.select_one('nav.pagination a[rel*="next"]')
    next_page = next_link_el.get("href") if next_link_el else None
    if next_page:
        next_page = urljoin(base_url, next_page)

    return {
        "ok": True,
        "query": query,
        "count": len(items),
        "next_page": next_page,
        "items": items,
    }


def search_history_events(place: str, *, only_textual: bool = True, timeout: int = 12) -> Dict:
    """
    主函式：給定地點字串（如 'taipei'），回傳結構化 JSON（dict）。
    """
    place = (place or "").strip()
    if not place:
        return {"ok": False, "error": "empty place"}

    url = f"{BASE_URL}/search/?{urlencode({'q': place})}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.8",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Referer": f"{BASE_URL}/search/",
        "Connection": "close",
    }
    resp = requests.get(url, headers=headers, timeout=timeout)
    if resp.status_code != 200:
        return {"ok": False, "error": f"HTTP {resp.status_code}", "url": url}

    return _parse_search_html(resp.text, only_textual=only_textual, base_url=BASE_URL)


def parse_from_html_string(html: str, *, only_textual: bool = True) -> Dict:
    """
    若你已經離線存了 HTML（例如測試用的 history_test.txt），可用這個函式直接解析。
    """
    if not html:
        return {"ok": False, "error": "empty html"}
    return _parse_search_html(html, only_textual=only_textual, base_url=BASE_URL)


# --- FastAPI Router（加 GET 方便測，強化 headers） ---
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

router = APIRouter()

class EventsReq(BaseModel):
    place: str
    only_textual: bool = True

@router.post("/history/events")
def history_events_api(req: EventsReq):
    try:
        data = search_history_events(req.place, only_textual=req.only_textual)
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))
    if not data.get("ok"):
        raise HTTPException(status_code=502, detail=data.get("error", "fetch failed"))
    return data

# 方便用瀏覽器直接打：/api/history/events?place=Taipei
@router.get("/history/events")
def history_events_api_get(
    place: str = Query(..., min_length=1),
    only_textual: bool = Query(True)
):
    try:
        data = search_history_events(place, only_textual=only_textual)
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))
    if not data.get("ok"):
        raise HTTPException(status_code=502, detail=data.get("error", "fetch failed"))
    return data
