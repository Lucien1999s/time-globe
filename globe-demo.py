import time
import random
import html
import urllib.parse
import requests
from bs4 import BeautifulSoup

DUCK_LITE_SEARCH = "https://lite.duckduckgo.com/lite/"

def _human_user_agent():
    return (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/119.0.0.0 Safari/537.36"
    )

def _fetch(url, params=None, timeout=12, max_retries=2, backoff=0.8):
    headers = {"User-Agent": _human_user_agent()}
    for attempt in range(max_retries + 1):
        try:
            r = requests.get(url, params=params, headers=headers, timeout=timeout)
            # 以 200 視為成功；其他狀態碼也嘗試回傳以利除錯
            if r.status_code == 200 and r.text:
                return r.text
            # 輕量退避
            time.sleep(backoff * (attempt + 1))
        except requests.RequestException:
            time.sleep(backoff * (attempt + 1))
    return ""

def _parse_duck_lite(html_text, max_results=5):
    """
    解析 DuckDuckGo Lite 結果頁。
    結構：<table> 中的多個 <tr>；每個結果通常在 <a> 後跟描述文字。
    """
    soup = BeautifulSoup(html_text, "html.parser")
    results = []
    # Lite 版結果常見在多個 <tr> 內，連結為 <a>；相鄰文字為摘要
    for a in soup.select("a"):
        href = a.get("href", "")
        text = a.get_text(" ", strip=True)
        if not href or not text:
            continue
        # 過濾導航/內部連結
        if href.startswith("/") or "duckduckgo.com" in href:
            continue
        # 找可能的摘要（a 所在行的後續文字）
        summary = ""
        # 嘗試從父層 <td>/<tr> 擷取相鄰文字
        parent = a.find_parent(["td", "tr"])
        if parent:
            # 取得父層文字，移除標題文字本身
            parent_text = parent.get_text(" ", strip=True)
            # 避免重複標題，並適度截斷
            summary = parent_text.replace(text, "").strip()
            # 清掉多餘冒號與空白
            summary = summary.lstrip(":-—| ").strip()
        # 乾淨化 URL
        clean_url = html.unescape(href)
        results.append((text, clean_url, summary))
        if len(results) >= max_results:
            break
    return results

def web_search(query: str, max_results: int = 5, polite_delay_sec: float = None) -> str:
    """
    免金鑰 Web 搜尋：輸入 str、輸出整段 str。
    主要使用 DuckDuckGo Lite 結果頁，解析標題、URL、摘要。
    """
    if polite_delay_sec is None:
        polite_delay_sec = round(random.uniform(0.4, 0.9), 2)  # 禮貌性延遲

    q = query.strip()
    if not q:
        return "（錯誤）請提供非空白的查詢字串。"

    # 取得結果頁 HTML
    payload = {"q": q}
    html_text = _fetch(DUCK_LITE_SEARCH, params=payload)
    if not html_text:
        return "（搜尋失敗）目前無法取得搜尋結果，可能是網路或對方暫時拒絕連線。稍後再試。"

    rows = _parse_duck_lite(html_text, max_results=max_results)
    if not rows:
        return "（沒有結果）可能是搜尋語法過於特殊，請嘗試更簡潔的關鍵字。"

    # 組裝輸出字串
    lines = [f"🔎 查詢：{q}", "-" * 48]
    for i, (title, url, summary) in enumerate(rows, 1):
        # 簡單截斷摘要，避免過長
        if len(summary) > 220:
            summary = summary[:217] + "..."
        # 防止 URL 過長造成換行混亂
        if len(url) > 200:
            short_url = url[:197] + "..."
        else:
            short_url = url
        lines.append(f"{i}. {title}\n   {short_url}")
        if summary:
            lines.append(f"   └ 摘要：{summary}")
        lines.append("")  # 空行分隔
        # 禮貌性延遲，避免太頻繁請求
        time.sleep(polite_delay_sec)

    return "\n".join(lines).strip()

# --- 範例執行 ---
if __name__ == "__main__":
    example_query = "TensorRT-LLM FP8 tutorial"
    output = web_search(example_query, max_results=5)
    print(output)
