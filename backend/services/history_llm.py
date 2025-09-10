from __future__ import annotations
from typing import Optional
import os
from dotenv import load_dotenv
from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel

# --- OpenAI (Responses API) ---
from openai import OpenAI

# --- Google Gemini ---
# pip install google-generativeai
import google.generativeai as genai

load_dotenv()
router = APIRouter()

# =========================
# Gemini setup and helpers
# =========================
GEMINI_TOKEN = os.getenv("GEMINI_TOKEN")
GEMINI_DEFAULT_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")


def _gemini_extract_text(resp) -> str:
    """
    Safely extract plain text from a Gemini response, even if Parts are present.
    """
    # 1) Aggregated .text from SDK
    try:
        t = getattr(resp, "text", None)
        if t:
            return t
    except Exception:
        pass
    # 2) Fallback: manually join candidates' parts
    try:
        texts = []
        for cand in getattr(resp, "candidates", []) or []:
            content = getattr(cand, "content", None)
            parts = getattr(content, "parts", None) if content else None
            if parts:
                for p in parts:
                    pt = getattr(p, "text", None)
                    if pt:
                        texts.append(pt)
        return "\n".join(texts).strip()
    except Exception:
        return ""


def _gemini_chat(prompt: str, model: Optional[str] = None, temperature: float = 0.2) -> str:
    """
    Simple chat with Gemini. Returns plain text. Raises if API/key error.
    Compatible with multiple google-generativeai SDK versions.
    """
    if not GEMINI_TOKEN:
        raise RuntimeError(
            "Missing GEMINI_TOKEN in environment. "
            "Create one in Google AI Studio and set it in your .env."
        )
    genai.configure(api_key=GEMINI_TOKEN)
    model_name = model or GEMINI_DEFAULT_MODEL
    gmodel = genai.GenerativeModel(model_name=model_name)

    gen_cfg = {"temperature": float(temperature)}
    try:
        resp = gmodel.generate_content(prompt, generation_config=gen_cfg)
    except Exception as e:
        # Some SDK versions are incompatible with generation_config; retry without it.
        if "GenerationConfig" in str(e) or "generation_config" in str(e):
            resp = gmodel.generate_content(prompt)
        else:
            raise
    text = _gemini_extract_text(resp)
    return text or ""


# ==================================
# 1) Gemini: offline knowledge mode
# ==================================
def make_history_info1(
    place: str,
    language: str = "中文",
    model: Optional[str] = None,
    temperature: float = 0.2,
) -> str:
    """
    Generate a place's historical summary using Gemini WITHOUT web browsing.
    - Emphasize known facts; avoid speculation.
    - Return bullet-style, concise text in the requested language.
    """
    prompt = (
        "Task: Given a place name, summarize its historical background WITHOUT browsing the web.\n"
        "Rules:\n"
        f"- Respond in {language}.\n"
        "- Highlight important civilizations, dynasties, or empires.\n"
        "- Mention major historical events, battles, or treaties.\n"
        "- Provide timeline context (centuries / years) when reasonably certain.\n"
        "- Include cultural or architectural heritage if well-known.\n"
        "- Use concise bullet points; keep within ~700 words.\n"
        "- Avoid fabrication; if uncertain, state the uncertainty explicitly.\n"
        f"\nPlace: {place}\n"
        "Output style:\n"
        "- Bullet points, one to two sentences per bullet; add Gregorian years where helpful.\n"
        "- Optionally end with 2–3 keywords as tags.\n"
    )
    return _gemini_chat(prompt, model=model, temperature=temperature)


# ================================
# 2) OpenAI: Responses + Web Search
# ================================
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
oa_client = OpenAI(api_key=OPENAI_API_KEY)


def make_history_info2(
    place: str,
    language: str = "中文",
    model: str = "gpt-5",
) -> str:
    """
    Generate a place's historical summary using OpenAI Responses API with web_search_preview.
    - Bullet-style, concise text in the requested language.
    - Citations are included in the model's reasoning context; we only extract the text here.
    """
    resp = oa_client.responses.create(
        model=model,
        input=[
            {
                "role": "developer",
                "content": [
                    {
                        "type": "input_text",
                        "text": (
                            "Given a place name, search and summarize its historical background.\n"
                            "- Highlight important civilizations, dynasties, or empires.\n"
                            "- Mention major historical events, battles, or treaties.\n"
                            "- Provide timeline context (centuries / years).\n"
                            "- If available, include cultural or architectural heritage.\n"
                            "- Use bullet points, concise style.\n"
                            f"- Respond in {language} within 700 words."
                        ),
                    }
                ],
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": f"Provide a complete historical summary of {place}",
                    }
                ],
            },
        ],
        text={"format": {"type": "text"}, "verbosity": "medium"},
        # reasoning removed for speed
        tools=[{"type": "web_search_preview"}],
        store=True,
        include=["web_search_call.action.sources"],  # keep citations metadata on the server
    )

    # Extract assistant text from Responses API output
    output_texts = []
    for item in resp.output:
        if getattr(item, "type", None) == "message":
            for c in getattr(item, "content", []) or []:
                if getattr(c, "type", None) == "output_text":
                    output_texts.append(getattr(c, "text", "") or "")

    return "\n".join(t for t in output_texts if t).strip()


# ================
# FastAPI routes
# ================
class HistoryReq(BaseModel):
    place: str
    language: str = "中文"


@router.post("/history/overview", response_class=JSONResponse)
def api_history_overview(req: HistoryReq):
    """
    Gemini (no web). Returns {ok, text}
    """
    try:
        text = make_history_info1(req.place, language=req.language)
        return JSONResponse({"ok": True, "text": text})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@router.post("/history/advanced", response_class=JSONResponse)
def api_history_advanced(req: HistoryReq):
    """
    OpenAI (web search). Returns {ok, text}
    """
    try:
        text = make_history_info2(req.place, language=req.language)
        return JSONResponse({"ok": True, "text": text})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


# ---------------- Minimal local examples ----------------
if __name__ == "__main__":
    # Example 1: Gemini (no web)
    try:
        print(make_history_info1("京都", language="繁體中文", temperature=0.25), "\n")
    except Exception as e:
        print("[Gemini] error:", e)

    # Example 2: OpenAI (with web search)
    try:
        print("===== OpenAI (web search) — Taipei =====")
        print(make_history_info2("京都", language="繁體中文"), "\n")
    except Exception as e:
        print("[OpenAI] error:", e)
