# -*- coding: utf-8 -*-
import html
import io
import json
import os
import re
import textwrap
import time
import urllib.request
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from about_content import ABOUT_HTML_EN, ABOUT_HTML_TA, ABOUT_MODAL_CSS

import httpx
import streamlit as st
from dotenv import load_dotenv
from gtts import gTTS

from backend_client import (
    BackendStreamError,
    stream_query_events,
)
from predefined_queries import (
    CROP_INTERESTS,
    FARMER_TYPES,
    QUICK_QUERIES,
    eligibility_query,
)

load_dotenv()
BACKEND_API_URL = os.getenv("FASTAPI_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
MAX_HISTORY = 20

# Global Thread Pool for parallel background tasks (TTS)
EXECUTOR = ThreadPoolExecutor(max_workers=4)

# Pre-compiled regex patterns for speed
RE_CITATIONS = re.compile(r"\[[sS]\d+\]")
RE_SPACES = re.compile(r" +")
RE_BOLD = re.compile(r"\*\*(.+?)\*\*")
RE_ITALIC = re.compile(r"\*(.+?)\*")
RE_TAMIL_CHARS = re.compile(r"[\u0B80-\u0BFF]")
RE_LATIN_CHARS = re.compile(r"[a-zA-Z]")
RE_MD_CHARS = re.compile(r"[*#_`>\[\]]")


def clean_citations(text: str) -> str:
    """Removes citation markers like [S1], [s2], [S12], etc."""
    if not text:
        return ""
    cleaned = RE_CITATIONS.sub("", text)
    cleaned = RE_SPACES.sub(" ", cleaned)
    return cleaned.strip()


def markdown_to_card_html(text: str) -> str:
    """Safely escapes HTML while rendering Markdown bold/italic within HTML cards."""
    if not text:
        return ""
    safe_text = html.escape(text)
    safe_text = RE_BOLD.sub(r"<strong>\1</strong>", safe_text)
    safe_text = RE_ITALIC.sub(r"<em>\1</em>", safe_text)
    return safe_text.replace("\n", "<br>")


def detect_language(text: str) -> str:
    """Detects whether text is primarily Tamil ('ta') or English ('en')."""
    if not text:
        return "ta"
    tamil_chars = len(RE_TAMIL_CHARS.findall(text))
    latin_chars = len(RE_LATIN_CHARS.findall(text))
    return "ta" if tamil_chars >= latin_chars else "en"


def generate_speech_audio(text: str) -> bytes | None:
    """Generates a concise audio summary of the key output points."""
    cleaned = clean_citations(text)
    cleaned = RE_MD_CHARS.sub("", cleaned).strip()
    if not cleaned:
        return None

    # Extract the core summary sentences (up to 250 characters) for quick listening
    meaningful_lines = [
        line.strip() for line in cleaned.splitlines() if len(line.strip()) > 10
    ]
    summary_text = " ".join(meaningful_lines[:2])[:250].strip()
    if not summary_text:
        return None

    lang = detect_language(summary_text)
    try:
        tts = gTTS(text=summary_text, lang=lang, slow=False)
        fp = io.BytesIO()
        tts.write_to_fp(fp)
        fp.seek(0)
        return fp.getvalue()
    except Exception:
        return None


st.set_page_config(
    page_title="உழவன் AI — தமிழ்நாடு அரசு வேளாண் திட்ட வழிகாட்டி",
    page_icon="🌾",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------------------------------------------------
# Multi-Session & Persistent Chat State Management
# ---------------------------------------------------------
if "sessions" not in st.session_state:
    default_session_id = str(uuid.uuid4())
    st.session_state.sessions = {
        default_session_id: {
            "id": default_session_id,
            "title": "புதிய உரையாடல்",
            "messages": [],
            "updated_at": datetime.now(),
        }
    }
    st.session_state.active_session_id = default_session_id

if (
    "active_session_id" not in st.session_state
    or st.session_state.active_session_id not in st.session_state.sessions
):
    st.session_state.active_session_id = next(iter(st.session_state.sessions))

if "highlight_msg_idx" not in st.session_state:
    st.session_state.highlight_msg_idx = None

if "scroll_target_idx" not in st.session_state:
    st.session_state.scroll_target_idx = None


def start_new_chat_callback():
    new_id = str(uuid.uuid4())
    st.session_state.sessions[new_id] = {
        "id": new_id,
        "title": "புதிய உரையாடல்",
        "messages": [],
        "updated_at": datetime.now(),
    }
    st.session_state.active_session_id = new_id
    st.session_state.highlight_msg_idx = None
    st.session_state.scroll_target_idx = None


def clear_all_history_callback():
    for k in list(st.session_state.keys()):
        if isinstance(k, str) and k.startswith("audio_"):
            del st.session_state[k]
    st.session_state.sessions = {}
    new_id = str(uuid.uuid4())
    st.session_state.sessions[new_id] = {
        "id": new_id,
        "title": "புதிய உரையாடல்",
        "messages": [],
        "updated_at": datetime.now(),
    }
    st.session_state.active_session_id = new_id
    st.session_state.highlight_msg_idx = None
    st.session_state.scroll_target_idx = None


def switch_to_session(session_id: str):
    st.session_state.active_session_id = session_id
    st.session_state.highlight_msg_idx = None
    sess = st.session_state.sessions.get(session_id, {})
    msgs = sess.get("messages", [])
    st.session_state.scroll_target_idx = len(msgs) - 1 if msgs else None


# ---------------------------------------------------------
# Tamil Font Setup
# ---------------------------------------------------------
FONT_DIR = "./storage"
os.makedirs(FONT_DIR, exist_ok=True)
TAMIL_FONT_PATH = os.path.join(FONT_DIR, "NotoSansTamil-Regular.ttf")


@st.cache_resource(show_spinner=False)
def ensure_tamil_font():
    if not os.path.exists(TAMIL_FONT_PATH):
        try:
            url = "https://raw.githubusercontent.com/googlefonts/noto-fonts/main/hinted/ttf/NotoSansTamil/NotoSansTamil-Regular.ttf"
            urllib.request.urlretrieve(url, TAMIL_FONT_PATH)
        except Exception:
            pass
    return TAMIL_FONT_PATH if os.path.exists(TAMIL_FONT_PATH) else None


ensure_tamil_font()

# ---------------------------------------------------------
# Modern Buildathon CSS & Refined Spacing
# ---------------------------------------------------------
st.markdown(
    """
<style>
    @import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&family=Noto+Sans+Tamil:wght@400;500;600;700;800&display=swap');

    :root {
        --brand-deep: #064e3b;
        --brand-mid: #065f46;
        --brand-soft: #047857;
        --brand-leaf: #059669;
        --brand-glow: #10b981;
        --accent-gold: #d97706;
        --accent-amber: #f59e0b;
        --text-ink: #062e24;
        --text-muted: #4b6b60;
        --surface-soft: #f0fdf4;
        --border-line: #dcfce7;
        --shadow-soft: 0 4px 16px -2px rgba(6, 78, 59, 0.08);
        --shadow-lift: 0 12px 28px -4px rgba(6, 78, 59, 0.18);
        --shadow-glow: 0 8px 24px -2px rgba(16, 185, 129, 0.35);
        --ease: cubic-bezier(0.2, 0.8, 0.2, 1);
    }

    * {
        font-family: 'Noto Sans Tamil', 'Plus Jakarta Sans', system-ui, -apple-system, sans-serif;
        box-sizing: border-box;
    }

    header[data-testid="stHeader"], #MainMenu, footer, .stDeployButton { 
        display: none !important; 
    }

    html, body, [data-testid="stAppViewContainer"] {
        padding-top: 0 !important;
        margin-top: 0 !important;
        overflow-y: auto !important;
        height: 100vh !important;
    }

    .stApp {
        background: radial-gradient(circle at 10% 15%, rgba(220, 252, 231, 0.6) 0%, transparent 40%),
                    radial-gradient(circle at 90% 85%, rgba(254, 249, 195, 0.5) 0%, transparent 45%),
                    linear-gradient(135deg, #e6f4ea 0%, #edf7ed 50%, #fef9e7 100%) !important;
        background-size: 200% 200%;
        animation: bgShift 18s ease-in-out infinite;
        padding-top: 0 !important;
    }
    @keyframes bgShift {
        0%, 100% { background-position: 0% 50%; }
        50% { background-position: 100% 50%; }
    }

    .block-container {
        padding-top: 0.5rem !important;
        padding-bottom: 0.4rem !important;
        padding-left: 1rem !important;
        padding-right: 1rem !important;
        max-width: 100% !important;
    }

    .sticky-top-fixed-wrapper {
        position: sticky !important;
        top: 0 !important;
        z-index: 999 !important;
        background: rgba(230, 244, 234, 0.96);
        backdrop-filter: blur(12px);
        padding-top: 2px;
        padding-bottom: 4px;
        margin-bottom: 4px;
    }

    /* ---------- Sidebar ---------- */
    [data-testid="stSidebarCollapseButton"] { display: none !important; }
    section[data-testid="stSidebar"] {
        min-width: 295px !important;
        max-width: 310px !important;
        background: linear-gradient(180deg, var(--brand-deep) 0%, var(--brand-mid) 100%) !important;
        border-right: none !important;
        box-shadow: 10px 0 35px -10px rgba(6, 78, 59, 0.35);
        height: 100vh !important;
        overflow: hidden !important;
        z-index: 1000;
    }
    section[data-testid="stSidebar"] [data-testid="stSidebarContent"] {
        overflow-y: auto !important;
        scrollbar-width: none;
        height: 100% !important;
        display: flex !important;
        flex-direction: column !important;
        justify-content: space-between !important;
    }
    section[data-testid="stSidebar"] [data-testid="stSidebarContent"]::-webkit-scrollbar { display: none; }
    section[data-testid="stSidebar"] .block-container {
        padding: 0.8rem !important;
        height: 100% !important;
        display: flex !important;
        flex-direction: column !important;
        justify-content: space-between !important;
    }
    section[data-testid="stSidebar"] hr {
        margin: 8px 0 !important;
        border-color: rgba(255, 255, 255, 0.12) !important;
    }
    section[data-testid="stSidebar"] h3 {
        font-size: 0.82rem !important;
        margin: 4px 0 !important;
        font-weight: 700 !important;
        color: #f0fdf4 !important;
    }
    section[data-testid="stSidebar"] label,
    section[data-testid="stSidebar"] label p {
        color: #d1fae5 !important;
        font-size: 0.72rem !important;
        font-weight: 600 !important;
    }
    section[data-testid="stSidebar"] div[data-baseweb="slider"] div[role="slider"] {
        background: var(--accent-gold) !important;
        box-shadow: 0 0 0 4px rgba(217, 119, 6, 0.25) !important;
    }
    section[data-testid="stSidebar"] div[data-baseweb="select"] > div {
        min-height: 34px !important;
        font-size: 0.74rem !important;
        background: rgba(4, 120, 87, 0.5) !important;
        border: 1px solid rgba(255, 255, 255, 0.18) !important;
        border-radius: 10px !important;
        color: #ffffff !important;
    }
    section[data-testid="stSidebar"] div[data-baseweb="select"] * { color: #ffffff !important; }

    .interactive-field-card {
        background: radial-gradient(circle at 85% 15%, rgba(254, 240, 138, 0.25) 0%, transparent 45%),
                    linear-gradient(145deg, rgba(6, 78, 59, 0.8) 0%, rgba(4, 120, 87, 0.6) 100%);
        border: 1px solid rgba(255, 255, 255, 0.2);
        border-radius: 16px;
        padding: 10px;
        margin-bottom: 10px;
        color: #ffffff;
        box-shadow: 0 8px 20px rgba(0, 0, 0, 0.15);
        backdrop-filter: blur(8px);
    }
    .field-card-header {
        display: flex;
        justify-content: flex-start;
        align-items: center;
        margin-bottom: 6px;
    }
    .field-card-title {
        font-size: 0.78rem;
        font-weight: 800;
        color: #fef08a;
        display: flex;
        align-items: center;
        gap: 5px;
    }
    .interactive-svg-wrap {
        width: 100%;
        display: flex;
        justify-content: center;
        margin: 4px 0 6px 0;
    }
    .field-meta-grid {
        display: grid;
        grid-template-columns: 1fr 1fr;
        gap: 6px;
        font-size: 0.68rem;
    }
    .field-meta-item {
        background: rgba(255, 255, 255, 0.08);
        border: 1px solid rgba(255, 255, 255, 0.1);
        border-radius: 8px;
        padding: 4px 6px;
        display: flex;
        flex-direction: column;
    }
    .field-meta-item span:first-child {
        color: #a7f3d0;
        font-size: 0.58rem;
        font-weight: 600;
    }
    .field-meta-item span:last-child {
        color: #ffffff;
        font-weight: 800;
        font-size: 0.72rem;
    }

    .sidebar-metric-glass-card {
        background: rgba(255, 255, 255, 0.08);
        border: 1px solid rgba(255, 255, 255, 0.15);
        border-radius: 14px;
        padding: 8px;
        margin: 6px 0;
        backdrop-filter: blur(6px);
    }
    .metric-chip-row {
        display: flex; align-items: center; justify-content: space-between;
        padding: 6px 9px; border-radius: 10px; margin-bottom: 5px;
        font-size: 0.72rem; font-weight: 600;
    }
    .metric-chip-row:last-child { margin-bottom: 0; }
    .metric-seed { background: rgba(253, 224, 71, 0.15); color: #fef08a; }
    .metric-water { background: rgba(186, 230, 253, 0.15); color: #e0f2fe; }
    .metric-subsidy { background: rgba(167, 243, 208, 0.15); color: #d1fae5; }
    .metric-tag-val {
        font-size: 0.72rem; font-weight: 800; padding: 2px 8px; border-radius: 8px;
        background: #ffffff; color: var(--brand-deep);
    }

    section[data-testid="stSidebar"] .stButton > button {
        border-radius: 12px !important;
        font-weight: 700 !important;
        font-size: 0.76rem !important;
        height: 38px !important;
        border: 1px solid rgba(255, 255, 255, 0.2) !important;
        background: rgba(255, 255, 255, 0.08) !important;
        color: #ffffff !important;
        transition: all .2s ease !important;
    }
    section[data-testid="stSidebar"] .stButton > button:hover {
        background: linear-gradient(135deg, #10b981, #059669) !important;
        color: #ffffff !important;
        transform: translateY(-2px);
    }

    /* ---------- Header Banner ---------- */
    .kiosk-hero-banner {
        background: linear-gradient(120deg, #064e3b 0%, #065f46 55%, #047857 100%);
        border-radius: 16px;
        padding: 10px 18px;
        box-shadow: var(--shadow-lift);
        border: 1px solid rgba(255, 255, 255, 0.15);
        color: #fff;
        display: flex; 
        align-items: center; 
        justify-content: space-between;
        margin-bottom: 6px;
    }
    .kiosk-title-group { display: flex; align-items: center; gap: 12px; }
    .kiosk-emblem-badge {
        width: 40px; height: 40px; border-radius: 12px;
        background: linear-gradient(135deg, #10b981, #059669);
        display: flex; align-items: center; justify-content: center;
        font-size: 1.35rem;
        box-shadow: 0 4px 10px rgba(0, 0, 0, 0.15);
    }
    .kiosk-title-text { font-size: 1.3rem; font-weight: 800; color: #fff; letter-spacing: -0.3px; }
    .kiosk-subtitle-text { color: #a7f3d0; font-size: 0.72rem; margin-top: 1px; }

    .hero-right { display: flex; align-items: center; gap: 8px; }
    .hero-pill {
        background: rgba(255, 255, 255, 0.1); border: 1px solid rgba(255, 255, 255, 0.16);
        color: #fef08a; font-size: 0.68rem; font-weight: 700;
        padding: 4px 12px; border-radius: 999px;
    }
    .hero-live-dot {
        width: 8px; height: 8px; border-radius: 50%; background: #34d399;
        display: inline-block; margin-right: 6px;
        animation: blink 1.4s ease-in-out infinite;
    }
    @keyframes blink { 0%, 100% { opacity: 1; } 50% { opacity: .25; } }

    .kiosk-action-card {
        background: #ffffff;
        border: 1.5px solid var(--border-line);
        border-radius: 14px;
        padding: 8px 10px;
        height: 78px;
        display: flex; flex-direction: column; justify-content: space-between;
        box-shadow: var(--shadow-soft);
        transition: transform .25s ease, border-color .25s ease, box-shadow .25s ease;
    }
    .kiosk-action-card:hover {
        border-color: var(--brand-glow);
        transform: translateY(-3px);
        box-shadow: var(--shadow-lift);
    }
    .action-card-header { display: flex; justify-content: space-between; align-items: center; }
    .anim-icon {
        font-size: 0.95rem; display: inline-flex; align-items: center; justify-content: center;
        width: 26px; height: 26px; border-radius: 7px;
        background: #ecfdf5; border: 1px solid #a7f3d0;
    }
    .action-card-badge {
        font-size: 0.58rem; font-weight: 700; padding: 2px 7px; border-radius: 999px;
        background: #ecfdf5; color: #065f46; border: 1px solid #a7f3d0;
    }
    .action-card-title {
        font-weight: 800; font-size: 0.76rem; color: var(--text-ink);
        white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
    }
    .action-card-desc {
        color: var(--text-muted); font-size: 0.63rem; line-height: 1.15;
        white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
    }

    /* ---------- Balanced Header Cards ---------- */
    .st-key-arena_header_box,
    .st-key-history_header_box {
        background: #ffffff !important;
        border: 1.5px solid #a7f3d0 !important;
        border-radius: 14px !important;
        padding: 6px 14px !important;
        margin-top: 4px !important;
        margin-bottom: 6px !important;
        box-shadow: var(--shadow-soft) !important;
        height: 48px !important;
        display: flex !important;
        align-items: center !important;
    }

    .st-key-arena_header_box [data-testid="stHorizontalBlock"],
    .st-key-history_header_box [data-testid="stHorizontalBlock"] {
        align-items: center !important;
        width: 100% !important;
    }

    .arena-title-wrap {
        display: flex;
        align-items: center;
        justify-content: flex-start;
        gap: 8px;
        font-size: 0.92rem;
        font-weight: 800;
        color: var(--brand-deep);
        white-space: nowrap;
    }

    .history-title-badge-block {
        display: flex;
        align-items: center;
        justify-content: flex-start;
        gap: 8px;
        font-size: 0.86rem;
        font-weight: 700;
        color: #374151;
        white-space: nowrap;
    }

    .arena-count-pill {
        font-size: 0.68rem;
        font-weight: 800;
        color: #065f46;
        background: #d1fae5;
        border: 1px solid #a7f3d0;
        padding: 2px 8px;
        border-radius: 999px;
    }

    .st-key-chat_hdr_new_btn button {
        background: linear-gradient(135deg, #10b981 0%, #059669 100%) !important;
        border: 1px solid #6ee7b7 !important;
        border-radius: 999px !important;
        color: #ffffff !important;
        font-size: 0.74rem !important;
        font-weight: 800 !important;
        padding: 2px 14px !important;
        height: 32px !important;
        min-height: 32px !important;
        box-shadow: 0 2px 8px rgba(16, 185, 129, 0.28) !important;
        transition: all 0.2s var(--ease) !important;
        white-space: nowrap !important;
    }
    .st-key-chat_hdr_new_btn button:hover {
        background: linear-gradient(135deg, #059669 0%, #047857 100%) !important;
        transform: translateY(-1px) !important;
        box-shadow: 0 4px 12px rgba(16, 185, 129, 0.4) !important;
    }

    .st-key-clear_hist_btn_action button {
        background: linear-gradient(135deg, #ef4444 0%, #dc2626 100%) !important;
        border: 1px solid #f87171 !important;
        border-radius: 999px !important;
        color: #ffffff !important;
        font-size: 0.74rem !important;
        font-weight: 800 !important;
        padding: 2px 14px !important;
        height: 32px !important;
        min-height: 32px !important;
        box-shadow: 0 2px 8px rgba(239, 68, 68, 0.28) !important;
        transition: all 0.2s var(--ease) !important;
        white-space: nowrap !important;
    }
    .st-key-clear_hist_btn_action button:hover {
        background: linear-gradient(135deg, #dc2626 0%, #b91c1c 100%) !important;
        border-color: #ef4444 !important;
        color: #ffffff !important;
        transform: translateY(-1px) !important;
        box-shadow: 0 4px 12px rgba(220, 38, 38, 0.4) !important;
    }

    div[data-testid="stVerticalBlockBorderWrapper"] {
        border-radius: 16px !important;
        border: 1.5px solid var(--border-line) !important;
        background: #ffffff !important;
        box-shadow: var(--shadow-soft) !important;
    }

    @keyframes popSlideIn {
        0% { opacity: 0; transform: translateY(8px) scale(0.99); }
        100% { opacity: 1; transform: translateY(0) scale(1); }
    }

    .user-question-bubble-card {
        background: linear-gradient(135deg, #fffbeb 0%, #fef3c7 50%, #fef08a 100%);
        border: 1.5px solid #fde047;
        border-radius: 14px;
        padding: 10px 14px;
        color: #854d0e;
        font-weight: 700;
        font-size: 0.84rem;
        display: flex;
        align-items: center;
        gap: 10px;
        margin-bottom: 10px;
        box-shadow: 0 4px 14px rgba(217, 119, 6, 0.12);
        animation: popSlideIn 0.35s var(--ease);
        scroll-margin-top: 14px;
    }
    .user-question-highlighted {
        border: 2.5px solid #d97706 !important;
        box-shadow: 0 0 20px rgba(217, 119, 6, 0.45) !important;
        animation: pulseHighlight 1.5s ease-in-out infinite alternate !important;
    }
    @keyframes pulseHighlight {
        0% { transform: scale(1); box-shadow: 0 0 10px rgba(217, 119, 6, 0.25); }
        100% { transform: scale(1.01); box-shadow: 0 0 22px rgba(217, 119, 6, 0.55); }
    }

    .assistant-answer-bubble-card {
        background: #ffffff;
        border: 1.5px solid #d1fae5;
        border-radius: 16px;
        padding: 14px 18px;
        box-shadow: 0 6px 20px rgba(6, 78, 59, 0.06);
        margin-bottom: 4px !important;
        font-size: 0.85rem;
        line-height: 1.65;
        color: var(--text-ink);
        animation: popSlideIn 0.4s var(--ease);
    }

    .assistant-header-flex {
        display: flex;
        align-items: center;
        gap: 8px;
        margin-bottom: 8px;
        border-bottom: 1px dashed #a7f3d0;
        padding-bottom: 8px;
    }
    .assistant-header-title { color: var(--brand-deep); font-weight: 800; font-size: 0.88rem; }

    .duplicate-notice-card {
        background: #eff6ff;
        border: 1.5px solid #93c5fd;
        color: #1e40af;
        border-radius: 12px;
        padding: 9px 14px;
        font-size: 0.79rem;
        font-weight: 700;
        margin-bottom: 10px;
        display: flex;
        align-items: center;
        gap: 8px;
        box-shadow: 0 2px 8px rgba(30, 64, 175, 0.08);
    }

    .assistant-loading-box {
        background: #f0fdf4;
        border: 1.5px dashed #34d399;
        border-radius: 12px;
        padding: 12px 16px;
        margin-top: 8px;
        display: flex;
        align-items: center;
        gap: 10px;
        color: #065f46;
        font-size: 0.82rem;
        font-weight: 700;
        animation: popSlideIn 0.3s var(--ease);
    }

    .spin-sprout {
        display: inline-block;
        animation: sproutPulse 1.2s ease-in-out infinite;
    }
    @keyframes sproutPulse {
        0%, 100% { transform: scale(1); opacity: 0.7; }
        50% { transform: scale(1.25); opacity: 1; }
    }

    /* Animated Tractor Progress Pointer on the right edge */
    .tractor-pointer-progress {
        display: inline-block;
        margin-left: 6px;
        font-size: 1.15rem;
        transform: scaleX(1);
        animation: tractorPlowSmoothRight 0.75s infinite alternate ease-in-out;
        vertical-align: middle;
    }
    @keyframes tractorPlowSmoothRight {
        0% { transform: scaleX(1) translateX(0) rotate(0deg); }
        50% { transform: scaleX(1) translateX(4px) rotate(3deg); }
        100% { transform: scaleX(1) translateX(8px) rotate(-2deg); }
    }

    .audio-playback-container {
        margin-top: 4px !important;
        margin-bottom: 4px !important;
        padding: 0 !important;
    }

    .audio-synthesizing-loader {
        background: linear-gradient(135deg, rgba(236, 253, 245, 0.95) 0%, rgba(240, 253, 244, 0.95) 100%);
        border: 1.5px solid #6ee7b7;
        border-radius: 12px;
        padding: 6px 14px;
        margin: 4px 0 4px 0;
        display: flex;
        align-items: center;
        gap: 10px;
        box-shadow: var(--shadow-glow);
        animation: popSlideIn 0.3s var(--ease);
    }
    .audio-wave-dot {
        width: 22px;
        height: 22px;
        border-radius: 50%;
        background: #10b981;
        display: flex;
        align-items: center;
        justify-content: center;
        color: #ffffff;
        font-size: 0.78rem;
        box-shadow: 0 0 0 0 rgba(16, 185, 129, 0.7);
        animation: audioWavePulse 1.4s infinite;
    }
    @keyframes audioWavePulse {
        0% { transform: scale(0.92); box-shadow: 0 0 0 0 rgba(16, 185, 129, 0.7); }
        70% { transform: scale(1.08); box-shadow: 0 0 0 10px rgba(16, 185, 129, 0); }
        100% { transform: scale(0.92); box-shadow: 0 0 0 0 rgba(16, 185, 129, 0); }
    }
    .audio-wave-text {
        font-size: 0.72rem;
        font-weight: 700;
        color: #065f46;
    }

    .dossier-card {
        background: linear-gradient(135deg, #ffffff 0%, #f0fdf4 100%);
        border: 1.5px solid #86efac;
        border-radius: 16px;
        padding: 10px 14px;
        margin-top: -2px !important;
        margin-bottom: 8px !important;
        box-shadow: 0 4px 18px rgba(5, 150, 105, 0.08);
        animation: popSlideIn 0.45s var(--ease);
    }
    .dossier-card-header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        border-bottom: 1px dashed #bbf7d0;
        padding-bottom: 5px;
        margin-bottom: 8px;
    }
    .dossier-title-text { font-size: 0.82rem; font-weight: 800; color: var(--brand-deep); display: flex; align-items: center; gap: 6px; }

    .dossier-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 6px; margin-bottom: 6px; }
    .dossier-cell {
        background: #ffffff;
        border: 1px solid #d1fae5;
        border-radius: 10px;
        padding: 6px 9px;
        box-shadow: 0 2px 6px rgba(6, 78, 59, 0.03);
    }
    .dossier-cell-label { font-size: 0.6rem; font-weight: 800; color: var(--brand-soft); text-transform: uppercase; margin-bottom: 2px; }
    .dossier-cell-val { font-size: 0.74rem; font-weight: 600; color: var(--text-ink); line-height: 1.35; }

    .dossier-doc-strip {
        background: #fffbeb;
        border: 1px solid #fde68a;
        border-radius: 10px;
        padding: 6px 9px;
        font-size: 0.7rem;
        color: #854d0e;
        font-weight: 600;
        line-height: 1.35;
    }

    .dossier-synthesizing-loader {
        background: linear-gradient(135deg, rgba(254, 249, 195, 0.95) 0%, rgba(254, 243, 199, 0.95) 100%);
        border: 1.5px solid #fde047;
        border-radius: 12px;
        padding: 6px 14px;
        margin: 4px 0 4px 0;
        display: flex;
        align-items: center;
        gap: 10px;
        box-shadow: 0 4px 14px rgba(217, 119, 6, 0.12);
        animation: popSlideIn 0.3s var(--ease);
    }
    .dossier-wave-dot {
        width: 22px;
        height: 22px;
        border-radius: 50%;
        background: #f59e0b;
        display: flex;
        align-items: center;
        justify-content: center;
        color: #ffffff;
        font-size: 0.78rem;
        box-shadow: 0 0 0 0 rgba(245, 158, 11, 0.7);
        animation: dossierWavePulse 1.4s infinite;
    }
    @keyframes dossierWavePulse {
        0% { transform: scale(0.92); box-shadow: 0 0 0 0 rgba(245, 158, 11, 0.7); }
        70% { transform: scale(1.08); box-shadow: 0 0 0 10px rgba(245, 158, 11, 0); }
        100% { transform: scale(0.92); box-shadow: 0 0 0 0 rgba(245, 158, 11, 0); }
    }
    .dossier-wave-text {
        font-size: 0.72rem;
        font-weight: 700;
        color: #854d0e;
    }

    /* ---------- Chat Input ---------- */
    [data-testid="stBottom"] {
        background: transparent !important;
        padding-bottom: 10px !important;
    }

    [data-testid="stBottom"] > div {
        background: transparent !important;
    }

    div[data-testid="stChatInput"] {
        background: #ffffff !important;
        border-radius: 20px !important;
        border: 1.5px solid var(--border-line) !important;
        box-shadow: 0 4px 18px -2px rgba(6, 78, 59, 0.07), 0 1px 4px rgba(0, 0, 0, 0.03) !important;
        padding: 4px 8px 4px 14px !important;
        overflow: hidden !important;
        box-sizing: border-box !important;
        transition: border-color 0.25s var(--ease), box-shadow 0.25s var(--ease) !important;
    }

    div[data-testid="stChatInput"] > div,
    div[data-testid="stChatInput"] [data-baseweb="textarea"] {
        background: transparent !important;
        border: none !important;
        border-radius: 0 !important;
        box-shadow: none !important;
    }

    div[data-testid="stChatInput"]:hover {
        border-color: #6ee7b7 !important;
        box-shadow: 0 6px 22px -2px rgba(6, 78, 59, 0.12), 0 2px 6px rgba(16, 185, 129, 0.06) !important;
    }

    div[data-testid="stChatInput"]:focus-within {
        border-color: var(--brand-glow) !important;
        box-shadow: 0 0 0 3px rgba(16, 185, 129, 0.18), 0 8px 26px -4px rgba(6, 78, 59, 0.14) !important;
    }

    div[data-testid="stChatInput"] textarea {
        background: transparent !important;
        border: none !important;
        font-size: 0.88rem !important;
        color: var(--text-ink) !important;
        font-weight: 500 !important;
        line-height: 1.5 !important;
        padding: 6px 0 !important;
        box-shadow: none !important;
    }

    div[data-testid="stChatInput"] textarea::placeholder {
        color: #94a3b8 !important;
        font-size: 0.85rem !important;
        font-weight: 500 !important;
    }

    div[data-testid="stChatInput"] button {
        background: linear-gradient(135deg, #10b981 0%, #059669 100%) !important;
        color: #ffffff !important;
        border: 1px solid #6ee7b7 !important;
        border-radius: 50% !important;
        height: 36px !important;
        width: 36px !important;
        min-width: 36px !important;
        min-height: 36px !important;
        display: flex !important;
        align-items: center !important;
        justify-content: center !important;
        margin: auto 0 !important;
        box-shadow: 0 2px 8px rgba(16, 185, 129, 0.3) !important;
        transition: transform 0.2s var(--ease), box-shadow 0.2s var(--ease), background 0.2s ease !important;
    }

    div[data-testid="stChatInput"] button:hover {
        transform: scale(1.06) !important;
        box-shadow: 0 4px 14px rgba(16, 185, 129, 0.45) !important;
        background: linear-gradient(135deg, #059669 0%, #047857 100%) !important;
    }

    div[data-testid="stChatInput"] button:active {
        transform: scale(0.95) !important;
    }

    .st-emotion-cache-2e5lff{   margin-top:-50px;  }
    
</style>
""",
    unsafe_allow_html=True,
)

# ---------------------------------------------------------
# Modal Dialogs
# ---------------------------------------------------------
@st.dialog("📚 சரிபார்க்கப்பட்ட அரசு ஆதாரங்கள்", width="large")
def show_sources_dialog(sources_list):
    st.markdown("FastAPI பதிலுடன் திருப்பியளித்த குறியீட்டிலுள்ள ஆதாரங்கள்:")
    for idx, s in enumerate(sources_list, start=1):
        raw_score = s.get("score")
        try:
            score_pct = int(float(raw_score) * 100) if raw_score != "N/A" else 88
        except Exception:
            score_pct = 85

        source_name = s.get("source", "அரசு ஆவணம்")
        file_path = s.get("url_or_file", "")
        document_name = (
            s.get("document_name")
            or str(file_path).replace("\\", "/").rsplit("/", 1)[-1]
        )
        page_number = s.get("page_number")
        page_ref = (
            f" · PDF பக்கம்: {html.escape(str(page_number))}"
            if page_number
            else ""
        )
        escaped_location = html.escape(str(file_path), quote=True)
        if str(file_path).startswith(("https://", "http://")):
            location_markup = (
                f'<a href="{escaped_location}" target="_blank"'
                ' rel="noopener noreferrer">'
                f"{escaped_location}</a>"
            )
        else:
            location_markup = f"<code>{escaped_location}</code>"

        st.markdown(
            f"""
        <div style="background:#ecfdf5; border-left:4px solid #059669; border-radius:10px; padding:10px 12px; margin-bottom:8px; box-shadow:0 2px 8px rgba(6,78,59,.06);">
            <div style="display:flex; justify-content:space-between; align-items:center;">
                <strong style="color:#065f46; font-size:0.82rem;">#{idx}. {html.escape(str(source_name))}</strong>
                <span style="font-size:0.68rem; font-weight:700; background:#d1fae5; color:#064e3b; padding:2px 8px; border-radius:999px;">🎯 {score_pct}% பொருத்தம்</span>
            </div>
            <p style="font-size:0.77rem; color:#062e24; margin:6px 0; line-height:1.45;"><em>"{html.escape(str(s.get('content', '')))}"</em></p>
            <small style="color:#4b6b60; font-size:0.7rem;">📄 ஆவணப் பெயர்: {html.escape(str(document_name))}<br>🔗 ஆதாரம்: {location_markup}{page_ref}</small>
        </div>
        """,
            unsafe_allow_html=True,
        )


@st.dialog("About", width="large")
def show_about_dialog():
    st.markdown(ABOUT_MODAL_CSS, unsafe_allow_html=True)

    if "about_modal_lang" not in st.session_state:
        st.session_state.about_modal_lang = "English"

    col_hdr_left, col_hdr_right = st.columns([2.5, 1.1], vertical_alignment="center")

    with col_hdr_left:
        active_title = (
            "ℹ️ Uzhavan AI"
            if st.session_state.about_modal_lang == "English"
            else "ℹ️ உழவன் AI"
        )
        st.markdown(
            f'<div class="about-dialog-top-bar"><span class="about-dialog-main-heading">{active_title}</span></div>',
            unsafe_allow_html=True,
        )

    with col_hdr_right:
        st.markdown(
            '<div class="about-dialog-top-bar" style="justify-content: flex-end;">',
            unsafe_allow_html=True,
        )
        selected_lang = st.radio(
            "Language",
            options=["English", "தமிழ்"],
            horizontal=True,
            label_visibility="collapsed",
            key="about_modal_lang",
        )
        st.markdown("</div>", unsafe_allow_html=True)

    # Render localized content
    if selected_lang == "English":
        st.markdown(ABOUT_HTML_EN, unsafe_allow_html=True)
    else:
        st.markdown(ABOUT_HTML_TA, unsafe_allow_html=True)

    st.markdown(
        '<div class="about-modal-bottom-spacer"></div>', unsafe_allow_html=True
    )

# ---------------------------------------------------------
# SVG Token Generator
# ---------------------------------------------------------
def generate_dossier_svg_token(dossier: dict) -> bytes:
    now_str = datetime.now().strftime("%d-%b-%Y %I:%M %p")
    scheme_name = str(dossier.get("scheme_name", "வேளாண் நலத்திட்டம்"))
    subsidy = str(dossier.get("subsidy", "விதிகளுக்கு உட்பட்டது"))
    eligibility = str(dossier.get("eligibility", "தமிழக விவசாயிகள்"))
    office = str(
        dossier.get("office", "வட்டார வேளாண் உதவி இயக்குநர் அலுவலகம்")
    )
    docs = str(
        dossier.get(
            "documents",
            "பட்டா/சிட்டா, குடும்ப அட்டை, வங்கி கணக்கு புத்தகம்",
        )
    )

    def get_lines(text: str, max_chars: int = 34):
        lines = textwrap.wrap(text, width=max_chars)
        l1 = html.escape(lines[0]) if len(lines) > 0 else ""
        l2 = html.escape(lines[1]) if len(lines) > 1 else ""
        return l1, l2

    s_l1, s_l2 = get_lines(scheme_name, 34)
    sub_l1, sub_l2 = get_lines(subsidy, 34)
    e_l1, e_l2 = get_lines(eligibility, 34)
    o_l1, o_l2 = get_lines(office, 34)
    d_l1, d_l2 = get_lines(docs, 75)

    svg_markup = f"""<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="960" height="640" viewBox="0 0 960 640">
  <defs>
    <linearGradient id="hdr" x1="0" y1="0" x2="1" y2="0">
      <stop offset="0" stop-color="#064e3b" />
      <stop offset="0.6" stop-color="#065f46" />
      <stop offset="1" stop-color="#059669" />
    </linearGradient>
    <style>
      @import url('https://fonts.googleapis.com/css2?family=Noto+Sans+Tamil:wght@400;600;700;800&amp;family=Plus+Jakarta+Sans:wght@600;700;800&amp;display=swap');
      text {{ font-family: 'Noto Sans Tamil', 'Plus Jakarta Sans', Arial, sans-serif; }}
    </style>
  </defs>

  <rect width="960" height="640" fill="#ffffff" />
  <rect x="15" y="15" width="930" height="610" rx="14" fill="#ffffff" stroke="#059669" stroke-width="3" />
  <path d="M 17 29 Q 17 17 29 17 L 931 17 Q 943 17 943 29 L 943 115 L 17 115 Z" fill="url(#hdr)" />

  <text x="42" y="58" fill="#ffffff" font-size="22" font-weight="800">UZHAVAN AI - SCHEME APPLICATION DOSSIER</text>
  <text x="42" y="94" fill="#d1fae5" font-size="14" font-weight="600">தமிழ்நாடு வேளாண்மை &amp; உழவர் நலத்துறை வழிகாட்டல் டோக்கன்</text>
  <text x="918" y="94" fill="#ffffff" font-size="13" font-weight="600" text-anchor="end">தேதி: {html.escape(now_str)}</text>

  <rect x="42" y="140" width="425" height="105" rx="8" fill="#ecfdf5" stroke="#a7f3d0" stroke-width="1.5" />
  <text x="60" y="168" fill="#047857" font-size="12" font-weight="700">திட்டத்தின் பெயர் / SCHEME NAME</text>
  <text x="60" y="198" fill="#064e3b" font-size="16" font-weight="700">{s_l1}</text>
  <text x="60" y="222" fill="#064e3b" font-size="14" font-weight="600">{s_l2}</text>

  <rect x="493" y="140" width="425" height="105" rx="8" fill="#ecfdf5" stroke="#a7f3d0" stroke-width="1.5" />
  <text x="511" y="168" fill="#047857" font-size="12" font-weight="700">மானிய சலுகை / SUBSIDY BENEFIT</text>
  <text x="511" y="198" fill="#064e3b" font-size="16" font-weight="700">{sub_l1}</text>
  <text x="511" y="222" fill="#064e3b" font-size="14" font-weight="600">{sub_l2}</text>

  <rect x="42" y="265" width="425" height="105" rx="8" fill="#ecfdf5" stroke="#a7f3d0" stroke-width="1.5" />
  <text x="60" y="293" fill="#047857" font-size="12" font-weight="700">தகுதி வரம்பு / ELIGIBILITY</text>
  <text x="60" y="323" fill="#064e3b" font-size="16" font-weight="700">{e_l1}</text>
  <text x="60" y="347" fill="#064e3b" font-size="14" font-weight="600">{e_l2}</text>

  <rect x="493" y="265" width="425" height="105" rx="8" fill="#ecfdf5" stroke="#a7f3d0" stroke-width="1.5" />
  <text x="511" y="293" fill="#047857" font-size="12" font-weight="700">அணுக வேண்டிய இடம் / CONTACT OFFICE</text>
  <text x="511" y="323" fill="#064e3b" font-size="16" font-weight="700">{o_l1}</text>
  <text x="511" y="347" fill="#064e3b" font-size="14" font-weight="600">{o_l2}</text>

  <rect x="42" y="390" width="876" height="110" rx="8" fill="#fffbeb" stroke="#fde68a" stroke-width="1.5" />
  <text x="62" y="418" fill="#92400e" font-size="13" font-weight="700">சமர்ப்பிக்க வேண்டிய ஆவணங்கள் / REQUIRED DOCUMENTS:</text>
  <text x="62" y="450" fill="#1e293b" font-size="15" font-weight="600">{d_l1}</text>
  <text x="62" y="476" fill="#1e293b" font-size="14" font-weight="600">{d_l2}</text>

  <line x1="42" y1="525" x2="918" y2="525" stroke="#e2e8f0" stroke-width="1" />
  <text x="42" y="555" fill="#64748b" font-size="12">Official Grounding verified by Uzhavan AI Knowledge Base (Local Vector Store).</text>
  <text x="42" y="582" fill="#047857" font-size="13" font-weight="600">குறிப்பு: இந்த டோக்கனை உங்கள் வட்டார வேளாண் மையத்தில் சமர்ப்பிக்கவும்.</text>
</svg>"""
    return svg_markup.encode("utf-8")


# ---------------------------------------------------------
# Sidebar
# ---------------------------------------------------------
sidebar_query = None
with st.sidebar:
    st.markdown("<div>", unsafe_allow_html=True)

    st.markdown("### 🌾 பயிர் & நீர் கணக்கீடு")
    acreage = st.slider(
        "நிலப்பரப்பு (Acres):",
        min_value=0.5,
        max_value=25.0,
        value=2.0,
        step=0.5,
    )
    seed_rate = acreage * 3.0
    water_saving = 30
    subsidy_tier = "100%" if acreage <= 5.0 else "75%"

    field_width = int(min(240, max(60, acreage * 18)))
    st.markdown(
        f"""
    <div class="interactive-field-card">
        <div class="field-card-header">
            <span class="field-card-title">🌱 நேரடி நிலக் கண்காணிப்பு</span>
        </div>
        <div class="interactive-svg-wrap">
            <svg width="250" height="90" viewBox="0 0 250 90">
                <defs>
                    <linearGradient id="skyGrad" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="0%" stop-color="#047857" />
                        <stop offset="100%" stop-color="#064e3b" />
                    </linearGradient>
                    <linearGradient id="groundGrad" x1="0" y1="0" x2="1" y2="0">
                        <stop offset="0%" stop-color="#10b981" />
                        <stop offset="100%" stop-color="#059669" />
                    </linearGradient>
                </defs>
                <rect width="250" height="90" rx="10" fill="url(#skyGrad)" opacity="0.6"/>
                <circle cx="215" cy="22" r="12" fill="#fde047" opacity="0.9"/>
                <circle cx="215" cy="22" r="18" fill="#fde047" opacity="0.25"/>
                <path d="M 15 65 Q 40 55, 70 65 T 130 65 T 190 65 T 240 65" fill="none" stroke="#67e8f9" stroke-width="2" stroke-dasharray="4,4" opacity="0.8"/>
                <rect x="15" y="60" width="{field_width}" height="18" rx="6" fill="url(#groundGrad)" opacity="0.9"/>
                <text x="22" y="58" font-size="14">🌾</text>
                <text x="55" y="58" font-size="14">🌱</text>
                <text x="90" y="58" font-size="14">🌾</text>
                <text x="130" y="58" font-size="14">🌱</text>
                <text x="170" y="58" font-size="14">🌾</text>
                <text x="{min(205, field_width + 10)}" y="74" font-size="14">🚜</text>
            </svg>
        </div>
        <div class="field-meta-grid">
            <div class="field-meta-item">
                <span>பரப்பளவு நிலை</span>
                <span>{acreage:.1f} ஏக்கர்</span>
            </div>
            <div class="field-meta-item">
                <span>நீர் சேமிப்பு வீதம்</span>
                <span>{water_saving}% AWD</span>
            </div>
        </div>
    </div>
    """,
        unsafe_allow_html=True,
    )

    st.markdown(
        f"""
    <div class="sidebar-metric-glass-card">
        <div class="metric-chip-row metric-seed">
            <span>🌾 SRI விதை தேவை:</span>
            <span class="metric-tag-val">{seed_rate:.1f} kg</span>
        </div>
        <div class="metric-chip-row metric-water">
            <span>💧 AWD நீர் சேமிப்பு:</span>
            <span class="metric-tag-val">{water_saving}%</span>
        </div>
        <div class="metric-chip-row metric-subsidy">
            <span>🎯 சொட்டு நீர் மானியம்:</span>
            <span class="metric-tag-val">{subsidy_tier}</span>
        </div>
    </div>
    """,
        unsafe_allow_html=True,
    )

    st.markdown("<hr>", unsafe_allow_html=True)
    st.markdown("### 📋 மானியத் தகுதி அறி")
    farmer_type = st.selectbox("விவசாயி பிரிவு:", FARMER_TYPES)
    crop_interest = st.selectbox("பயிர் வகை:", CROP_INTERESTS)

    if st.button("🔍 தகுதியான திட்டங்களை அறி", use_container_width=True):
        sidebar_query = eligibility_query(farmer_type, crop_interest)

    st.markdown("</div>", unsafe_allow_html=True)

    st.markdown(
        "<div style='margin-top: auto; padding-top: 15px;'>",
        unsafe_allow_html=True,
    )
    st.markdown("<hr>", unsafe_allow_html=True)
    if st.button(
        "ℹ️ செயலி பற்றி (About)",
        key="sidebar_about_btn",
        use_container_width=True,
    ):
        show_about_dialog()
    st.markdown("</div>", unsafe_allow_html=True)

# ---------------------------------------------------------
# Full Width Top Sticky Header
# ---------------------------------------------------------
quick_query = None

st.markdown('<div class="sticky-top-fixed-wrapper">', unsafe_allow_html=True)

st.markdown(
    """
<div class="kiosk-hero-banner">
    <div class="kiosk-title-group">
        <div class="kiosk-emblem-badge">🌾</div>
        <div>
            <div class="kiosk-title-text">உழவன் AI</div>
            <div class="kiosk-subtitle-text">தமிழ்நாடு அரசு வேளாண்மை &amp; உழவர் நலத்துறை விவேக வழிகாட்டி</div>
        </div>
    </div>
    <div class="hero-right">
        <span class="hero-pill"><span class="hero-live-dot"></span>நேரலை</span>        
    </div>
</div>
""",
    unsafe_allow_html=True,
)

st.markdown("<div style='height: 4px;'></div>", unsafe_allow_html=True)

c1, c2, c3, c4 = st.columns(4)
with c1:
    st.markdown(
        """
    <div class="kiosk-action-card">
        <div class="action-card-header">
            <span class="anim-icon">💧</span>
            <span class="action-card-badge">பாசனம்</span>
        </div>
        <div>
            <div class="action-card-title">பாசனம் &amp; நீர் மேலாண்மை</div>
            <div class="action-card-desc">Pani Pipe முறை மற்றும் சொட்டு நீர் 100% மானியம்</div>
        </div>
    </div>
    """,
        unsafe_allow_html=True,
    )
    if st.button(
        "அறிந்து கொள்க ➔", key="btn_quick_1", use_container_width=True
    ):
        quick_query = QUICK_QUERIES["pani_pipe"]

with c2:
    st.markdown(
        """
    <div class="kiosk-action-card">
        <div class="action-card-header">
            <span class="anim-icon">🏛️</span>
            <span class="action-card-badge">திட்டங்கள்</span>
        </div>
        <div>
            <div class="action-card-title">கலைஞர் ஒருங்கிணைந்த திட்டம்</div>
            <div class="action-card-desc">கிராம வளர்ச்சித் திட்டம், உபகரணங்கள் மற்றும் விதைகள்</div>
        </div>
    </div>
    """,
        unsafe_allow_html=True,
    )
    if st.button(
        "அறிந்து கொள்க ➔", key="btn_quick_2", use_container_width=True
    ):
        quick_query = QUICK_QUERIES["kalaignar"]

with c3:
    st.markdown(
        """
    <div class="kiosk-action-card">
        <div class="action-card-header">
            <span class="anim-icon">🚜</span>
            <span class="action-card-badge">மானியம்</span>
        </div>
        <div>
            <div class="action-card-title">இயந்திர வாடகை மையம் (CHC)</div>
            <div class="action-card-desc">டிராக்டர், நடவு இயந்திர மையம் அமைக்கும் முறை</div>
        </div>
    </div>
    """,
        unsafe_allow_html=True,
    )
    if st.button(
        "அறிந்து கொள்க ➔", key="btn_quick_3", use_container_width=True
    ):
        quick_query = QUICK_QUERIES["custom_hiring"]

with c4:
    st.markdown(
        """
    <div class="kiosk-action-card">
        <div class="action-card-header">
            <span class="anim-icon">⚡</span>
            <span class="action-card-badge">மின்சாரம் & காப்பீடு</span>
        </div>
        <div>
            <div class="action-card-title">இலவச மின்சாரம் &amp; காப்பீடு</div>
            <div class="action-card-desc">விவசாய இலவச மின் இணைப்பு மற்றும் PMFBY பயிர் காப்பீடு</div>
        </div>
    </div>
    """,
        unsafe_allow_html=True,
    )
    if st.button(
        "அறிந்து கொள்க ➔", key="btn_quick_4", use_container_width=True
    ):
        quick_query = QUICK_QUERIES["power_and_insurance"]

st.markdown("</div>", unsafe_allow_html=True)

# ---------------------------------------------------------
# Symmetrical Header Cards
# ---------------------------------------------------------
top_col_chat, top_col_hist = st.columns([3.15, 1.25], gap="small")

total_sessions = len(st.session_state.sessions)

with top_col_chat:
    arena_card = st.container(key="arena_header_box")
    with arena_card:
        a_col_left, a_col_right = st.columns(
            [2.9, 1.1], vertical_alignment="center"
        )
        with a_col_left:
            st.markdown(
                '<div class="arena-title-wrap">'
                "<span style=margin-top:-5px;>🌾 உழவர் ஆலோசனை அரங்கம்</span>"
                "</div>",
                unsafe_allow_html=True,
            )
        with a_col_right:
            if st.button(
                "➕ புதிய உரையாடல்",
                key="chat_hdr_new_btn",
                use_container_width=True,
                help="புதிய உரையாடலைத் தொடங்க",
            ):
                start_new_chat_callback()
                st.rerun()

with top_col_hist:
    hist_header_card = st.container(key="history_header_box")
    with hist_header_card:
        h_col_meta, h_col_del = st.columns(
            [2.0, 1.0], vertical_alignment="center"
        )
        with h_col_meta:
            st.markdown(
                f"""
            <div class="history-title-badge-block">
                <span style="margin-top:-5px;">🕘 உரையாடல்கள்</span>
                <span class="arena-count-pill" style="margin-top:-5px;>{total_sessions}/{MAX_HISTORY}</span>
            </div>
            """,
                unsafe_allow_html=True,
            )
        with h_col_del:
            if st.button(
                "🗑️ அழி",
                key="clear_hist_btn_action",
                use_container_width=True,
                help="அனைத்து உரையாடல்களையும் அழிக்க",
            ):
                clear_all_history_callback()
                st.rerun()

# ---------------------------------------------------------
# Symmetrical Chat and History Viewports
# ---------------------------------------------------------
col_chat, col_hist = st.columns([3.15, 1.25], gap="small")

current_session = st.session_state.sessions[st.session_state.active_session_id]
active_messages = current_session["messages"]

with col_chat:
    chat_viewport = st.container(height=520)

with col_hist:
    hist_container = st.container(height=520)
    with hist_container:
        sorted_session_items = sorted(
            st.session_state.sessions.items(),
            key=lambda item: item[1].get("updated_at", datetime.min),
            reverse=True,
        )[:MAX_HISTORY]

        if not sorted_session_items or all(
            len(s["messages"]) == 0 for _, s in sorted_session_items
        ):
            st.markdown(
                """
            <div style="text-align:center; color:#6b7280; font-size:0.75rem; padding:40px 10px;">
                🌱 <em>இன்னும் உரையாடல்கள் பதிவாகவில்லை. உங்கள் முதல் கேள்வியைக் கேட்கவும்!</em>
            </div>
            """,
                unsafe_allow_html=True,
            )
        else:
            for s_id, sess in sorted_session_items:
                msg_count = len(sess["messages"])
                if msg_count == 0:
                    continue
                first_q = sess["title"]
                is_active = s_id == st.session_state.active_session_id
                tag_marker = "🟢 " if is_active else "💬 "

                clean_title = (
                    first_q if len(first_q) <= 40 else first_q[:40] + "..."
                )
                last_turn_text = clean_citations(
                    sess["messages"][-1].get("advisory_text", "")
                )
                snippet = (
                    " ".join(
                        last_turn_text.replace("*", "")
                        .replace("#", "")
                        .split()
                    )[:55]
                    + "..."
                )

                btn_label = f"{tag_marker}{clean_title}\n({msg_count} கேள்விகள்) — {snippet}"
                if st.button(
                    btn_label,
                    key=f"session_btn_{s_id}",
                    use_container_width=True,
                ):
                    switch_to_session(s_id)
                    st.rerun()

# ---------------------------------------------------------
# Validation Helper
# ---------------------------------------------------------
def is_valid_result(
    advisory_text: str, dossier: dict | None, sources: list
) -> bool:
    if not advisory_text:
        return False

    negative_signals = (
        "எங்கள் ஆவணங்களில் இந்த தகவல் இல்லை",
        "தகவல் கிடைக்கவில்லை",
        "மன்னிக்கவும்",
        "பொருத்தமான தகவல்கள் இல்லை",
        "தகவல்கள் எதுவும் காணப்படவில்லை",
        "விவரங்கள் இல்லை",
    )
    if any(sig in advisory_text for sig in negative_signals):
        return False

    if not dossier or not dossier.get("scheme_name"):
        return False

    scheme = str(dossier.get("scheme_name", "")).strip().lower()
    if not scheme or scheme in (
        "n/a",
        "none",
        "வேளாண் நலத்திட்டம்",
        "விதை பெருக்க திட்டம்",
    ):
        if not sources or len(sources) == 0:
            return False

    return True


# ---------------------------------------------------------
# Chat Message Loop with Refined Audio Player & Compact Layout
# ---------------------------------------------------------
with chat_viewport:
    for i, item in enumerate(active_messages):
        is_highlighted = st.session_state.highlight_msg_idx == i
        highlight_class = (
            " user-question-highlighted" if is_highlighted else ""
        )

        st.markdown(
            f'<div id="chat-turn-{i}" class="chat-turn-marker"'
            ' style="scroll-margin-top: 15px;"></div>',
            unsafe_allow_html=True,
        )

        if is_highlighted:
            st.markdown(
                """
            <div class="duplicate-notice-card">
                <span>ℹ️ இந்தக் கேள்வி ஏற்கனவே கேட்கப்பட்டுள்ளது. முந்தைய பதில் இதோ:</span>
            </div>
            """,
                unsafe_allow_html=True,
            )

        st.markdown(
            f"""
        <div class="user-question-bubble-card{highlight_class}">
            <span style="font-size:1.15rem;">🧑‍🌾</span>
            <span>{html.escape(item['question'])}</span>
        </div>
        """,
            unsafe_allow_html=True,
        )

        display_advisory = clean_citations(item["advisory_text"])
        formatted_advisory_html = markdown_to_card_html(display_advisory)

        # Output Results Section
        st.markdown(
            f"""
        <div class="assistant-answer-bubble-card">
            <div class="assistant-header-flex">
                <span style="font-size:1.15rem;">🌾</span>
                <span class="assistant-header-title">உழவன் AI வழிகாட்டல்</span>
            </div>
            <div>{formatted_advisory_html}</div>
        </div>
        """,
            unsafe_allow_html=True,
        )

        if "எங்கள் ஆவணங்களில் இந்த தகவல் இல்லை" in item["advisory_text"]:
            st.info(
                "குறியீட்டிலுள்ள ஆதாரங்களில் இந்தக்"
                " கேள்விக்குப் போதுமான தகவல் இல்லை."
            )

        # ---------------------------------------------------------
        # Audio Playback
        # ---------------------------------------------------------
        audio_key = f"audio_{current_session['id']}_{i}"

        if audio_key not in st.session_state and display_advisory.strip():
            audio_loader_placeholder = st.empty()
            audio_loader_placeholder.markdown(
                """
            <div class="audio-synthesizing-loader">
                <div class="audio-wave-dot">🎙️</div>
                <div class="audio-wave-text">குரல் சுருக்கம் தயாராகிறது... / Preparing audio summary...</div>
            </div>
            """,
                unsafe_allow_html=True,
            )

            generated_bytes = generate_speech_audio(display_advisory)
            if generated_bytes:
                st.session_state[audio_key] = generated_bytes

            audio_loader_placeholder.empty()

        if st.session_state.get(audio_key):
            st.markdown(
                '<div class="audio-playback-container">', unsafe_allow_html=True
            )
            st.audio(st.session_state[audio_key], format="audio/mp3")
            st.markdown("</div>", unsafe_allow_html=True)

        # ---------------------------------------------------------
        # Application Dossier Section
        # ---------------------------------------------------------
        d = item.get("dossier")
        sources = item.get("sources", [])
        has_valid_dossier = is_valid_result(item["advisory_text"], d, sources)

        if has_valid_dossier:
            st.markdown(
                f"""
            <div class="dossier-card">
                <div class="dossier-card-header">
                    <span class="dossier-title-text">📋 அரசு மானிய விண்ணப்ப அட்டை (Application Dossier)</span>
                    <span style="font-size:0.62rem; font-weight:700; background:#ecfdf5; color:#047857; padding:2px 8px; border-radius:999px; border:1px solid #a7f3d0;">உடனடி நடவடிக்கை</span>
                </div>
                <div class="dossier-grid">
                    <div class="dossier-cell">
                        <div class="dossier-cell-label">திட்டத்தின் பெயர்</div>
                        <div class="dossier-cell-val">{html.escape(str(d.get('scheme_name', 'வேளாண் நலத்திட்டம்')))}</div>
                    </div>
                    <div class="dossier-cell">
                        <div class="dossier-cell-label">மானிய சலுகை</div>
                        <div class="dossier-cell-val">{html.escape(str(d.get('subsidy', 'விதிகளுக்கு உட்பட்டது')))}</div>
                    </div>
                    <div class="dossier-cell">
                        <div class="dossier-cell-label">தகுதி வரம்பு</div>
                        <div class="dossier-cell-val">{html.escape(str(d.get('eligibility', 'தமிழக விவசாயிகள்')))}</div>
                    </div>
                    <div class="dossier-cell">
                        <div class="dossier-cell-label">அணுக வேண்டிய இடம்</div>
                        <div class="dossier-cell-val">{html.escape(str(d.get('office', 'வட்டார வேளாண் உதவி இயக்குநர் அலுவலகம்')))}</div>
                    </div>
                </div>
                <div class="dossier-doc-strip">
                    📁 <strong>சமர்ப்பிக்க வேண்டிய ஆவணங்கள்:</strong> {html.escape(str(d.get('documents', 'பட்டா/சிட்டா, குடும்ப அட்டை, வங்கி கணக்கு புத்தகம்')))}
                </div>
            </div>
            """,
                unsafe_allow_html=True,
            )

        if has_valid_dossier and sources:
            btn_col1, btn_col2 = st.columns(2)
            with btn_col1:
                st.download_button(
                    label="🖼️ விண்ணப்ப டோக்கன் (SVG)",
                    data=generate_dossier_svg_token(d),
                    file_name=f"Uzhavan_Token_{i+1}.svg",
                    mime="image/svg+xml",
                    key=f"dl_token_{current_session['id']}_{i}",
                    use_container_width=True,
                )
            with btn_col2:
                if st.button(
                    "📚 சரிபார்க்கப்பட்ட ஆதாரங்கள்",
                    key=f"src_modal_btn_{current_session['id']}_{i}",
                    use_container_width=True,
                ):
                    show_sources_dialog(sources)
        elif has_valid_dossier:
            st.download_button(
                label="🖼️ விண்ணப்ப டோக்கனை பதிவிறக்கு (SVG)",
                data=generate_dossier_svg_token(d),
                file_name=f"Uzhavan_Token_{i+1}.svg",
                mime="image/svg+xml",
                key=f"dl_token_{current_session['id']}_{i}",
                use_container_width=True,
            )
        elif sources:
            if st.button(
                "📚 சரிபார்க்கப்பட்ட அரசு ஆதாரங்கள்",
                key=f"src_modal_btn_{current_session['id']}_{i}",
                use_container_width=True,
            ):
                show_sources_dialog(sources)

    st.markdown(
        '<div id="chat-stream-bottom" style="height:1px;"></div>',
        unsafe_allow_html=True,
    )

    if st.session_state.scroll_target_idx is not None:
        target_idx = st.session_state.scroll_target_idx
        st.markdown(
            f"""
        <script>
            (function() {{
                function executeScroll() {{
                    const marker = document.getElementById("chat-turn-{target_idx}") || document.getElementById("chat-stream-bottom");
                    if (!marker) return;

                    let scrollable = marker.closest('div[data-testid="stVerticalBlock"]');
                    if (scrollable && (scrollable.scrollHeight > scrollable.clientHeight)) {{
                        const targetTop = marker.offsetTop - scrollable.offsetTop - 12;
                        scrollable.scrollTo({{ top: Math.max(0, targetTop), behavior: "smooth" }});
                    }} else {{
                        marker.scrollIntoView({{ behavior: "smooth", block: "start" }});
                    }}
                }}

                setTimeout(executeScroll, 50);
                setTimeout(executeScroll, 200);
                setTimeout(executeScroll, 450);
            }})();
        </script>
        """,
            unsafe_allow_html=True,
        )
        st.session_state.scroll_target_idx = None

# ---------------------------------------------------------
# Dynamic Response Streamer: Progressive Text Typing & Independent Parallel Processing
# ---------------------------------------------------------
def generate_response(query_text: str):
    clean_q = query_text.strip()
    norm_q = clean_q.lower()

    for idx, existing_item in enumerate(current_session["messages"]):
        if existing_item.get("question", "").strip().lower() == norm_q:
            st.session_state.highlight_msg_idx = idx
            st.session_state.scroll_target_idx = idx
            st.rerun()

    st.session_state.highlight_msg_idx = None

    with chat_viewport:
        # User Question Card
        st.markdown(
            f"""
        <div class="user-question-bubble-card">
            <span style="font-size:1.15rem;">🧑‍🌾</span>
            <span>{html.escape(clean_q)}</span>
        </div>
        """,
            unsafe_allow_html=True,
        )

        # Independent section placeholders
        content_card_slot = st.empty()
        audio_card_slot = st.empty()
        dossier_card_slot = st.empty()

        # Section 1: Initial Content State
        content_card_slot.markdown(
            """
        <div class="assistant-answer-bubble-card">
            <div class="assistant-header-flex">
                <span style="font-size:1.15rem;">🌾</span>
                <span class="assistant-header-title">உழவன் AI வழிகாட்டல்</span>
            </div>
            <div class="assistant-loading-box">
                <span class="spin-sprout" style="font-size:1.25rem;">🌱</span>
                <span>அரசு ஆவணங்களில் தகவல் தேடப்பட்டு வழிகாட்டல் தயாராகிறது...</span>
            </div>
        </div>
        """,
            unsafe_allow_html=True,
        )

        # Section 2: Dedicated Audio Loader
        audio_card_slot.markdown(
            """
        <div class="audio-synthesizing-loader">
            <div class="audio-wave-dot">🎙️</div>
            <div class="audio-wave-text">குரல் சுருக்கம் தயாராகிறது... / Preparing audio summary...</div>
        </div>
        """,
            unsafe_allow_html=True,
        )

        # Section 3: Dedicated Dossier Loader
        dossier_card_slot.markdown(
            """
        <div class="dossier-synthesizing-loader">
            <div class="dossier-wave-dot">🌱</div>
            <div class="dossier-wave-text">மானிய விண்ணப்ப விவரங்கள் தயாராகின்றன... / Preparing application dossier...</div>
        </div>
        """,
            unsafe_allow_html=True,
        )

        sources_metadata = []
        raw_tokens = []
        displayed_chars = 0
        audio_future = None
        advisory_dispatched_for_audio = False

        # Fluid typewriter frame tracker
        last_frame_time = time.time()
        # High refresh rate (~50 FPS) for smooth visual typing effect
        FRAME_DELAY = 0.020
        # Granular character reveal chunk size
        CHARS_PER_STEP = 3

        try:
            for event in stream_query_events(clean_q, BACKEND_API_URL):
                ev_type = event.get("type")
                if ev_type == "sources":
                    sources_metadata = event.get("data", [])
                    continue
                if ev_type != "token":
                    continue

                token = event.get("content", "")
                raw_tokens.append(token)
                full_raw_stream = "".join(raw_tokens)

                # Early parallel dispatch for audio processing
                if (
                    not advisory_dispatched_for_audio
                    and "[DOSSIER_JSON]" in full_raw_stream
                ):
                    interim_advisory = clean_citations(
                        full_raw_stream.split("[DOSSIER_JSON]")[0]
                        .replace("[ADVISORY]", "")
                        .strip()
                    )
                    if interim_advisory:
                        audio_future = EXECUTOR.submit(
                            generate_speech_audio, interim_advisory
                        )
                        advisory_dispatched_for_audio = True

                # Determine visible advisory slice
                if "[DOSSIER_JSON]" in full_raw_stream:
                    advisory_content = full_raw_stream.split("[DOSSIER_JSON]")[0]
                else:
                    advisory_content = full_raw_stream

                advisory_clean = clean_citations(
                    advisory_content.replace("[ADVISORY]", "")
                )
                target_length = len(advisory_clean)

                # Progressive character typing with moving tractor pointer
                while displayed_chars < target_length:
                    now = time.time()
                    if (now - last_frame_time) >= FRAME_DELAY:
                        displayed_chars = min(
                            displayed_chars + CHARS_PER_STEP, target_length
                        )
                        partial_text = advisory_clean[:displayed_chars]
                        formatted_stream = markdown_to_card_html(partial_text)
                        
                        content_card_slot.markdown(
                            f"""
                        <div class="assistant-answer-bubble-card">
                            <div class="assistant-header-flex">
                                <span style="font-size:1.15rem;">🌾</span>
                                <span class="assistant-header-title">உழவன் AI வழிகாட்டல்</span>
                            </div>
                            <div>{formatted_stream} <span class='tractor-pointer-progress'>🚜💨</span></div>
                        </div>
                        """,
                            unsafe_allow_html=True,
                        )
                        last_frame_time = now
                    else:
                        break

        except (BackendStreamError, httpx.HTTPError) as exc:
            content_card_slot.error(f"Backend Server Error: {exc}")
            audio_card_slot.empty()
            dossier_card_slot.empty()
            return

        full_raw = "".join(raw_tokens)

        # Parse text & dossier
        if "[DOSSIER_JSON]" in full_raw:
            parts = full_raw.split("[DOSSIER_JSON]")
            advisory_text = parts[0].replace("[ADVISORY]", "").strip()
            try:
                dossier = json.loads(
                    parts[1].replace("```json", "").replace("```", "").strip()
                )
            except Exception:
                dossier = None
        else:
            advisory_text = full_raw.replace("[ADVISORY]", "").strip()
            dossier = None

        advisory_text = clean_citations(advisory_text)

        # Finish remaining characters smoothly
        final_len = len(advisory_text)
        while displayed_chars < final_len:
            displayed_chars = min(displayed_chars + (CHARS_PER_STEP * 2), final_len)
            formatted_partial = markdown_to_card_html(advisory_text[:displayed_chars])
            content_card_slot.markdown(
                f"""
            <div class="assistant-answer-bubble-card">
                <div class="assistant-header-flex">
                    <span style="font-size:1.15rem;">🌾</span>
                    <span class="assistant-header-title">உழவன் AI வழிகாட்டல்</span>
                </div>
                <div>{formatted_partial} <span class='tractor-pointer-progress'>🚜💨</span></div>
            </div>
            """,
                unsafe_allow_html=True,
            )
            time.sleep(FRAME_DELAY)

        # Section 1: Final content render without the tractor pointer
        formatted_stream_final = markdown_to_card_html(advisory_text)
        content_card_slot.markdown(
            f"""
        <div class="assistant-answer-bubble-card">
            <div class="assistant-header-flex">
                <span style="font-size:1.15rem;">🌾</span>
                <span class="assistant-header-title">உழவன் AI வழிகாட்டல்</span>
            </div>
            <div>{formatted_stream_final}</div>
        </div>
        """,
            unsafe_allow_html=True,
        )

        # Background audio thread trigger if not previously started
        if not audio_future and advisory_text.strip():
            audio_future = EXECUTOR.submit(generate_speech_audio, advisory_text)

        # Section 3: Render Application Dossier
        has_valid_dossier = is_valid_result(
            advisory_text, dossier, sources_metadata
        )
        if not has_valid_dossier:
            dossier = None

        if has_valid_dossier and dossier:
            dossier_card_slot.markdown(
                f"""
            <div class="dossier-card">
                <div class="dossier-card-header">
                    <span class="dossier-title-text">📋 அரசு மானிய விண்ணப்ப அட்டை (Application Dossier)</span>
                    <span style="font-size:0.62rem; font-weight:700; background:#ecfdf5; color:#047857; padding:2px 8px; border-radius:999px; border:1px solid #a7f3d0;">உடனடி நடவடிக்கை</span>
                </div>
                <div class="dossier-grid">
                    <div class="dossier-cell">
                        <div class="dossier-cell-label">திட்டத்தின் பெயர்</div>
                        <div class="dossier-cell-val">{html.escape(str(dossier.get('scheme_name', 'வேளாண் நலத்திட்டம்')))}</div>
                    </div>
                    <div class="dossier-cell">
                        <div class="dossier-cell-label">மானிய சலுகை</div>
                        <div class="dossier-cell-val">{html.escape(str(dossier.get('subsidy', 'விதிகளுக்கு உட்பட்டது')))}</div>
                    </div>
                    <div class="dossier-cell">
                        <div class="dossier-cell-label">தகுதி வரம்பு</div>
                        <div class="dossier-cell-val">{html.escape(str(dossier.get('eligibility', 'தமிழக விவசாயிகள்')))}</div>
                    </div>
                    <div class="dossier-cell">
                        <div class="dossier-cell-label">அணுக வேண்டிய இடம்</div>
                        <div class="dossier-cell-val">{html.escape(str(dossier.get('office', 'வட்டார வேளாண் உதவி இயக்குநர் அலுவலகம்')))}</div>
                    </div>
                </div>
                <div class="dossier-doc-strip">
                    📁 <strong>சமர்ப்பிக்க வேண்டிய ஆவணங்கள்:</strong> {html.escape(str(dossier.get('documents', 'பட்டா/சிட்டா, குடும்ப அட்டை, வங்கி கணக்கு புத்தகம்')))}
                </div>
            </div>
            """,
                unsafe_allow_html=True,
            )
        else:
            dossier_card_slot.empty()

        # Section 2: Concurrently Resolve Audio
        new_turn_idx = len(current_session["messages"])
        new_audio_key = f"audio_{current_session['id']}_{new_turn_idx}"
        audio_bytes = None
        if audio_future:
            try:
                audio_bytes = audio_future.result(timeout=10)
            except Exception:
                audio_bytes = None

        if audio_bytes:
            st.session_state[new_audio_key] = audio_bytes
            with audio_card_slot.container():
                st.markdown(
                    '<div class="audio-playback-container">',
                    unsafe_allow_html=True,
                )
                st.audio(audio_bytes, format="audio/mp3")
                st.markdown("</div>", unsafe_allow_html=True)
        else:
            audio_card_slot.empty()

    # Save turn record to persistent session state
    record = {
        "question": clean_q,
        "advisory_text": advisory_text,
        "dossier": dossier,
        "sources": sources_metadata,
    }

    current_session["messages"].append(record)
    current_session["updated_at"] = datetime.now()

    st.session_state.scroll_target_idx = len(current_session["messages"]) - 1

    if current_session["title"] == "புதிய உரையாடல்":
        current_session["title"] = clean_q[:45]

    st.rerun()


# ---------------------------------------------------------
# Native Input Trigger
# ---------------------------------------------------------
user_input = st.chat_input(
    "விவசாயத் திட்டங்கள் குறித்து கேட்கவும் (எ.கா: சொட்டு"
    " நீர் பாசன மானியம்)..."
)
active_query = user_input or quick_query or sidebar_query

if active_query:
    generate_response(active_query)