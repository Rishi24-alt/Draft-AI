# ╔══════════════════════════════════════════════════════════════════╗
# ║                        Draft AI — app.py                        ║
# ║         AI-powered engineering drawing analysis tool            ║
# ║                       by Rishi  ·  2025                         ║
# ╚══════════════════════════════════════════════════════════════════╝

import streamlit as st
from utils import (
    analyze_drawing,
    generate_pdf,
    extract_title_block,
    analyze_gdt,
    analyze_design_concerns,
    analyze_material,
    analyze_manufacturing,
    detect_dimensions,
    # ── 5 new features ──
    analyze_tolerance_stackup,
    analyze_manufacturability_score,
    estimate_cost,
    detect_missing_dimensions,
    compare_revisions,
)
import json, os, re, time, base64, shutil
from datetime import datetime
from pathlib import Path


# ══════════════════════════════════════════════════════════════════
# CONSTANTS
# ══════════════════════════════════════════════════════════════════

CHATS_FILE          = "saved_chats.json"     # Persisted chat sessions
RATE_LIMIT_FILE     = "rate_limits.json"     # Per-IP request tracking
LIBRARY_FILE        = "drawing_library.json" # Drawing library metadata
LIBRARY_DIR         = "drawing_library"      # Folder for saved drawings

MAX_CHATS           = 20   # Max saved chats before oldest is dropped
MAX_FILE_SIZE_MB    = 10   # Max upload size in megabytes
MAX_REQUESTS_PER_IP = 2    # Max AI requests per hour per user

# Ensure drawing library folder exists on startup
Path(LIBRARY_DIR).mkdir(exist_ok=True)


# ══════════════════════════════════════════════════════════════════
# SECURITY — File validation & rate limiting
# ══════════════════════════════════════════════════════════════════

def validate_file(f):
    """
    Validate uploaded file using magic bytes (not just file extension).
    Supports PNG, JPEG, and WEBP formats.
    Returns (is_valid: bool, file_type: str | None)
    """
    h = f.read(12)
    f.seek(0)
    if h[:8] == b'\x89PNG\r\n\x1a\n':              return True, "png"
    if h[:3] == b'\xff\xd8\xff':                    return True, "jpeg"
    if h[:4] == b'RIFF' and h[8:12] == b'WEBP':    return True, "webp"
    return False, None


def check_file_size(f):
    """Return file size in megabytes without consuming the stream."""
    f.seek(0, 2)
    size = f.tell()
    f.seek(0)
    return size / (1024 * 1024)


def load_rate_limits():
    """Load rate limit records from disk. Returns empty dict if missing."""
    if os.path.exists(RATE_LIMIT_FILE):
        try:
            with open(RATE_LIMIT_FILE) as f:
                return json.load(f)
        except:
            pass
    return {}


def save_rate_limits(d):
    """Persist rate limit records to disk."""
    with open(RATE_LIMIT_FILE, "w") as f:
        json.dump(d, f)


def get_client_ip():
    """
    Get the client's IP address from request headers.
    Works on Streamlit Cloud (x-forwarded-for) and falls back to 'local'.
    """
    try:
        h  = st.context.headers
        ip = h.get("x-forwarded-for", h.get("x-real-ip", "local"))
        return ip.split(",")[0].strip()
    except:
        return "local"


def check_rate_limit(ip):
    """
    Check if this IP is allowed to make another request.
    Resets the counter after 1 hour.
    Returns (allowed: bool, remaining: int)
    """
    lim = load_rate_limits()
    now = time.time()
    if ip not in lim:
        lim[ip] = {"count": 0, "window_start": now}
    e = lim[ip]
    if now - e["window_start"] > 3600:
        e["count"]        = 0
        e["window_start"] = now
    if e["count"] >= MAX_REQUESTS_PER_IP:
        save_rate_limits(lim)
        return False, 0
    return True, MAX_REQUESTS_PER_IP - e["count"]


def increment_rate_limit(ip):
    """Increment the request counter for this IP."""
    lim = load_rate_limits()
    now = time.time()
    if ip not in lim:
        lim[ip] = {"count": 0, "window_start": now}
    lim[ip]["count"] += 1
    save_rate_limits(lim)


# ══════════════════════════════════════════════════════════════════
# DRAWING LIBRARY — Save, load, search, delete drawings
# ══════════════════════════════════════════════════════════════════

def load_library():
    """Load drawing library metadata from disk."""
    if os.path.exists(LIBRARY_FILE):
        try:
            with open(LIBRARY_FILE) as f:
                return json.load(f)
        except:
            pass
    return {}


def save_library(lib):
    """Persist drawing library metadata to disk."""
    with open(LIBRARY_FILE, "w") as f:
        json.dump(lib, f)


def add_to_library(uploaded_file, tags="", notes=""):
    """
    Save an uploaded drawing to the library folder with metadata.
    Uses a timestamp prefix to avoid filename collisions.
    Returns the unique ID (uid) of the saved entry.
    """
    lib  = load_library()
    name = uploaded_file.name
    ts   = datetime.now().strftime("%Y%m%d_%H%M%S")
    uid  = f"{ts}_{name}"
    dest = os.path.join(LIBRARY_DIR, uid)

    uploaded_file.seek(0)
    with open(dest, "wb") as f:
        f.write(uploaded_file.read())
    uploaded_file.seek(0)

    lib[uid] = {
        "name":    name,
        "uid":     uid,
        "path":    dest,
        "tags":    [t.strip() for t in tags.split(",") if t.strip()],
        "notes":   notes,
        "added":   datetime.now().strftime("%d %b %Y, %H:%M"),
        "size_mb": round(check_file_size(uploaded_file), 2),
    }
    save_library(lib)
    return uid


def delete_from_library(uid):
    """Remove a drawing from the library folder and its metadata entry."""
    lib = load_library()
    if uid in lib:
        try:
            os.remove(lib[uid]["path"])
        except:
            pass
        del lib[uid]
        save_library(lib)


# ══════════════════════════════════════════════════════════════════
# CHAT PERSISTENCE — Save and restore chat sessions
# ══════════════════════════════════════════════════════════════════

def load_chats():
    """Load saved chat sessions from disk."""
    if os.path.exists(CHATS_FILE):
        try:
            with open(CHATS_FILE) as f:
                return json.load(f)
        except:
            pass
    return {}


def save_chats(chats):
    """Persist chat sessions to disk."""
    with open(CHATS_FILE, "w") as f:
        json.dump(chats, f)


def persist_chat():
    """
    Save the current chat session under the current drawing name.
    Automatically removes the oldest session if MAX_CHATS is exceeded.
    """
    name = st.session_state.current_drawing_name
    if not name:
        return
    st.session_state.saved_chats[name] = {
        "messages_display": list(st.session_state.messages_display),
        "chat_history":     list(st.session_state.chat_history),
        "image":            st.session_state.get("current_drawing_image"),
    }
    if len(st.session_state.saved_chats) > MAX_CHATS:
        del st.session_state.saved_chats[next(iter(st.session_state.saved_chats))]
    save_chats(st.session_state.saved_chats)


# ══════════════════════════════════════════════════════════════════
# MESSAGE FORMATTER — Convert AI text to styled HTML bubbles
# ══════════════════════════════════════════════════════════════════

def fmt(text):
    """
    Convert plain AI response text to HTML for chat display.
    Handles: headings, ordered lists, unordered lists, bold, plain paragraphs.
    Escapes HTML special characters to prevent injection.
    """
    text    = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    lines   = text.split("\n")
    html    = ""
    in_list = False

    for line in lines:
        s = line.strip()
        if not s:
            continue

        # Headings (## or ###)
        if s.startswith("### ") or s.startswith("## "):
            if in_list:
                html   += f'</{in_list}>'
                in_list = False
            h     = re.sub(r'^#+\s*', '', s)
            h     = re.sub(r'\*\*(.*?)\*\*', r'<strong>\1</strong>', h)
            html += f'<p style="margin:10px 0 4px;font-weight:600;color:#fff;font-size:14px;">{h}</p>'

        # Ordered list (1. item)
        elif re.match(r'^\d+\.', s):
            if in_list != "ol":
                if in_list: html += f'</{in_list}>'
                html   += '<ol style="margin:4px 0 4px 20px;padding:0;color:#fff;">'
                in_list = "ol"
            item  = re.sub(r'^\d+\.\s*', '', s)
            item  = re.sub(r'\*\*(.*?)\*\*', r'<strong>\1</strong>', item)
            html += f'<li style="margin-bottom:4px;line-height:1.7;font-size:14px;">{item}</li>'

        # Unordered list (- or •)
        elif s.startswith("- ") or s.startswith("• ") or re.match(r'^[•○◦]\s', s):
            if in_list != "ul":
                if in_list: html += f'</{in_list}>'
                html   += '<ul style="margin:4px 0 4px 20px;padding:0;color:#fff;">'
                in_list = "ul"
            item  = re.sub(r'^[-•○◦]\s*', '', s)
            item  = re.sub(r'\*\*(.*?)\*\*', r'<strong>\1</strong>', item)
            html += f'<li style="margin-bottom:4px;line-height:1.7;font-size:14px;">{item}</li>'

        # Plain paragraph
        else:
            if in_list:
                html   += f'</{in_list}>'
                in_list = False
            lh    = re.sub(r'\*\*(.*?)\*\*', r'<strong>\1</strong>', s)
            html += f'<p style="margin:4px 0;line-height:1.7;font-size:14px;color:#fff;">{lh}</p>'

    if in_list:
        html += f'</{in_list}>'
    return html


def render_dim_table(json_str):
    """
    Parse dimension detection JSON and render it as a styled HTML table.
    Falls back to plain text rendering if JSON parsing fails.
    """
    try:
        clean = json_str.strip()
        if "```" in clean:
            clean = re.sub(r'```[a-z]*', '', clean).replace("```", "").strip()
        data  = json.loads(clean)
        dims  = data.get("dimensions", data) if isinstance(data, dict) else data
        if not dims:
            return fmt(json_str)

        rows = ""
        for i, d in enumerate(dims):
            bg       = "rgba(255,255,255,0.02)" if i % 2 == 0 else "rgba(255,255,255,0.04)"
            label    = str(d.get("label",     "—"))
            value    = str(d.get("value",     "—"))
            unit     = str(d.get("unit",      "—"))
            tol      = str(d.get("tolerance", "—"))
            location = str(d.get("location",  "—"))
            dtype    = str(d.get("type",      "—"))
            rows += f'''<tr style="background:{bg};">
                <td style="padding:7px 12px;color:rgba(255,255,255,0.5);font-size:12px;">{label}</td>
                <td style="padding:7px 12px;color:#f97316;font-weight:600;font-size:14px;">{value}</td>
                <td style="padding:7px 12px;color:rgba(255,255,255,0.6);font-size:12px;">{unit}</td>
                <td style="padding:7px 12px;color:rgba(255,255,255,0.5);font-size:12px;">{tol}</td>
                <td style="padding:7px 12px;color:rgba(255,255,255,0.4);font-size:11px;">{dtype}</td>
                <td style="padding:7px 12px;color:rgba(255,255,255,0.35);font-size:11px;">{location}</td>
            </tr>'''

        summary = data.get("summary", "") if isinstance(data, dict) else ""
        sum_row = (
            f'<div style="padding:8px 12px;font-size:11px;color:rgba(255,255,255,0.35);'
            f'border-top:1px solid rgba(255,255,255,0.06);">{summary}</div>'
            if summary else ""
        )

        return f'''<div style="background:rgba(249,115,22,0.04);border:1px solid rgba(249,115,22,0.15);border-radius:10px;overflow:hidden;">
            <div style="padding:8px 14px;font-size:10px;font-family:JetBrains Mono,monospace;color:#f97316;letter-spacing:2px;text-transform:uppercase;border-bottom:1px solid rgba(249,115,22,0.12);">
                📏 DIMENSIONS DETECTED — {len(dims)} found
            </div>
            <table style="width:100%;border-collapse:collapse;">
                <thead><tr style="border-bottom:1px solid rgba(255,255,255,0.06);">
                    <th style="padding:6px 12px;text-align:left;font-size:10px;color:rgba(255,255,255,0.25);font-weight:500;">LABEL</th>
                    <th style="padding:6px 12px;text-align:left;font-size:10px;color:rgba(255,255,255,0.25);font-weight:500;">VALUE</th>
                    <th style="padding:6px 12px;text-align:left;font-size:10px;color:rgba(255,255,255,0.25);font-weight:500;">UNIT</th>
                    <th style="padding:6px 12px;text-align:left;font-size:10px;color:rgba(255,255,255,0.25);font-weight:500;">TOLERANCE</th>
                    <th style="padding:6px 12px;text-align:left;font-size:10px;color:rgba(255,255,255,0.25);font-weight:500;">TYPE</th>
                    <th style="padding:6px 12px;text-align:left;font-size:10px;color:rgba(255,255,255,0.25);font-weight:500;">LOCATION</th>
                </tr></thead>
                <tbody>{rows}</tbody>
            </table>{sum_row}
        </div>'''
    except:
        return fmt(json_str)


def render_title_block(raw):
    """
    Parse title block key-value text and render it as a styled HTML table.
    Skips any fields marked as 'not specified'.
    """
    rows = ""
    for line in raw.strip().split("\n"):
        if ":" in line:
            parts = line.split(":", 1)
            k     = parts[0].strip()
            v     = parts[1].strip() if len(parts) > 1 else "—"
            if v and v.lower() != "not specified":
                rows += (
                    f'<tr>'
                    f'<td style="padding:7px 14px;color:rgba(255,255,255,0.45);font-size:12px;'
                    f'font-family:JetBrains Mono,monospace;white-space:nowrap;'
                    f'border-bottom:1px solid rgba(255,255,255,0.04);">{k}</td>'
                    f'<td style="padding:7px 14px;color:#fff;font-size:13px;'
                    f'border-bottom:1px solid rgba(255,255,255,0.04);">{v}</td>'
                    f'</tr>'
                )
    return f'''<div style="background:rgba(249,115,22,0.05);border:1px solid rgba(249,115,22,0.18);border-radius:10px;overflow:hidden;">
        <div style="padding:8px 14px;font-size:10px;font-family:JetBrains Mono,monospace;color:#f97316;
                    letter-spacing:2px;text-transform:uppercase;border-bottom:1px solid rgba(249,115,22,0.12);">
            🏷️ TITLE BLOCK
        </div>
        <table style="width:100%;border-collapse:collapse;">{rows}</table>
    </div>'''


# ══════════════════════════════════════════════════════════════════
# PAGE CONFIG
# ══════════════════════════════════════════════════════════════════

st.set_page_config(
    page_title="Draft AI",
    page_icon=":pencil:",
    layout="wide",
    initial_sidebar_state="expanded",
)


# ══════════════════════════════════════════════════════════════════
# GLOBAL CSS STYLES
# ══════════════════════════════════════════════════════════════════

st.markdown("""
<style>

/* ── FONTS — Professional system stack (Helvetica Neue primary) ── */
@import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@300;400;500;600;700&family=DM+Mono:wght@400;500&display=swap');

/* ── RESET ── */
* { box-sizing: border-box; }

/* ── BASE PAGE BACKGROUND ── */
html, body                          { background: #0a0a0a !important; font-family: 'Helvetica Neue', Helvetica, Arial, 'DM Sans', sans-serif; letter-spacing: -0.01em; }
[data-testid="stAppViewContainer"]  { background: #0a0a0a !important; }
[data-testid="stMain"]              { background: #0a0a0a !important; overflow-y: auto !important; }

/* ── SUBTLE RADIAL GLOW (decorative background) ── */
[data-testid="stAppViewContainer"]::before {
    content: '';
    position: fixed;
    top: 0; left: 0;
    width: 100%; height: 100%;
    background:
        radial-gradient(ellipse 50% 40% at 20% 20%, rgba(249,115,22,0.035) 0%, transparent 70%),
        radial-gradient(ellipse 40% 30% at 80% 80%, rgba(249,115,22,0.025) 0%, transparent 70%);
    pointer-events: none;
    z-index: 0;
}

/* ── MAIN CONTENT CONTAINER ── */
.block-container {
    max-width: 900px !important;
    margin: 0 auto !important;
    padding: 40px 8px 120px 8px !important;
    min-height: 100vh !important;
}

/* ── HIDE STREAMLIT DEFAULT UI (deploy button, menu, footer) ── */
.stDeployButton, #MainMenu, footer { display: none !important; }

/* ── SIDEBAR TOGGLE BUTTON ── */
[data-testid="collapsedControl"] {
    position: fixed !important;
    top: 18px !important;
    left: 18px !important;
    z-index: 99999 !important;
    display: flex !important;
    visibility: visible !important;
    opacity: 1 !important;
    background: rgba(249,115,22,0.12) !important;
    border: 1px solid rgba(249,115,22,0.28) !important;
    border-radius: 6px !important;
    padding: 6px 10px !important;
    cursor: pointer !important;
}
[data-testid="collapsedControl"] svg {
    color: #f97316 !important;
    fill: #f97316 !important;
    width: 18px !important;
    height: 18px !important;
}

/* ── PAGE SCROLL ── */
html, body { overflow-y: auto; }
[data-testid="stAppViewContainer"] { overflow-y: auto !important; height: 100vh; }

/* ── STREAMLIT HEADER ── */
[data-testid="stHeader"] { background: transparent !important; }

/* ── SIDEBAR PANEL ── */
[data-testid="stSidebar"] {
    background: #0d0d0d !important;
    border-right: 1px solid rgba(255,255,255,0.04) !important;
}
[data-testid="stSidebar"] > div:first-child { padding: 28px 18px !important; }

/* Sidebar branding */
.sb-logo {
    font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif;
    font-size: 22px;
    font-weight: 700;
    letter-spacing: -0.03em;
    color: #fff;
    margin-bottom: 2px;
    margin-top: -12px;
}
.sb-logo span { color: #f97316; }
.sb-sub {
    font-size: 10px;
    color: rgba(255,255,255,0.18);
    font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif;
    letter-spacing: 0.04em;
    margin-top: -2px;
    margin-bottom: 20px;
    text-transform: uppercase;
}

/* Sidebar section labels */
.sb-label {
    font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif;
    font-size: 9px;
    letter-spacing: 0.12em;
    text-transform: uppercase;
    color: rgba(255,255,255,0.2);
    margin-bottom: 8px;
    margin-top: 16px;
    font-weight: 600;
}

/* Sidebar quota */
.sb-quota       { font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif; font-size: 11px; color: rgba(255,255,255,0.2); margin-bottom: 12px; }
.sb-quota span  { color: #f97316; font-weight: 600; }

/* Sidebar buttons */
[data-testid="stSidebar"] .stButton > button {
    background: rgba(255,255,255,0.03) !important;
    border: 1px solid rgba(255,255,255,0.06) !important;
    color: rgba(255,255,255,0.55) !important;
    border-radius: 6px !important;
    font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif !important;
    font-size: 12px !important;
    font-weight: 400 !important;
    padding: 9px 12px !important;
    width: 100% !important;
    text-align: left !important;
    margin-bottom: 3px !important;
    transition: all 0.12s !important;
    letter-spacing: 0em !important;
}
[data-testid="stSidebar"] .stButton > button:hover {
    background: rgba(249,115,22,0.07) !important;
    border-color: rgba(249,115,22,0.18) !important;
    color: #f97316 !important;
}

/* ── SPINNING GEAR ANIMATION ── */
@keyframes spinGear { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }
.gear-spin { display: inline-block; animation: spinGear 6s linear infinite; }

/* ── TOP NAV BAR ── */
.top-nav {
    display: flex !important;
    align-items: center !important;
    justify-content: space-between !important;
    padding: 16px 12px 14px 12px !important;
    border-bottom: 1px solid rgba(255,255,255,0.05);
    margin-bottom: 12px;
    margin-top: 0 !important;
    background: rgba(10,10,10,0.98) !important;
    z-index: 100;
}

/* ── FILE UPLOADER ── */
[data-testid="stFileUploader"] > div {
    border: 1.5px dashed rgba(255,255,255,0.07) !important;
    background: rgba(255,255,255,0.015) !important;
    border-radius: 8px !important;
    padding: 8px 14px !important;
}
[data-testid="stFileUploader"] > div:hover           { border-color: rgba(249,115,22,0.28) !important; }
[data-testid="stFileUploader"] label                 { display: none !important; }
[data-testid="stFileUploader"] button                {
    background: rgba(249,115,22,0.09) !important;
    border: 1px solid rgba(249,115,22,0.2) !important;
    color: #f97316 !important;
    border-radius: 5px !important;
    font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif !important;
    font-size: 11px !important;
    font-weight: 500 !important;
    letter-spacing: 0.02em !important;
}
[data-testid="stFileUploaderDropzoneInstructions"]   {
    font-size: 11px !important;
    color: rgba(255,255,255,0.18) !important;
    font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif !important;
}
[data-testid="stImage"] img {
    border-radius: 6px !important;
    border: 1px solid rgba(255,255,255,0.06) !important;
    max-height: 130px !important;
    object-fit: contain !important;
}

/* ── SECTION LABELS ── */
.section-label {
    font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif;
    font-size: 9px;
    letter-spacing: 0.12em;
    text-transform: uppercase;
    color: rgba(255,255,255,0.18);
    margin-bottom: 8px;
    font-weight: 600;
}

/* ── ALL ACTION BUTTONS ── */
.stButton > button {
    background: rgba(255,255,255,0.03) !important;
    border: 1px solid rgba(255,255,255,0.07) !important;
    color: rgba(255,255,255,0.75) !important;
    border-radius: 6px !important;
    font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif !important;
    font-size: 12px !important;
    font-weight: 400 !important;
    letter-spacing: 0em !important;
    padding: 10px 10px !important;
    width: 100% !important;
    transition: all 0.12s !important;
    text-align: center !important;
}
.stButton > button:hover {
    background: rgba(249,115,22,0.07) !important;
    border-color: rgba(249,115,22,0.22) !important;
    color: #f97316 !important;
}

/* Primary "Analyze" submit button */
.stButton > button[kind="primary"] {
    background: #f97316 !important;
    border: none !important;
    color: #fff !important;
    font-weight: 600 !important;
    font-size: 13px !important;
    letter-spacing: 0.02em !important;
    border-radius: 6px !important;
    text-align: center !important;
    padding: 13px !important;
}
.stButton > button[kind="primary"]:hover { background: #e86910 !important; }

/* ── CHAT MESSAGES ── */
.msg-row      { display: flex; margin-bottom: 20px; }
.msg-row.user { justify-content: flex-end; }
.msg-row.ai   { justify-content: flex-start; gap: 12px; align-items: flex-start; }

.bubble-user {
    background: rgba(249,115,22,0.09);
    border: 1px solid rgba(249,115,22,0.18);
    border-radius: 14px 14px 3px 14px;
    padding: 11px 16px;
    max-width: 72%;
    font-size: 13px;
    font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif;
    color: rgba(255,255,255,0.9);
    line-height: 1.65;
}

.ai-avatar {
    width: 26px; height: 26px;
    flex-shrink: 0;
    background: rgba(249,115,22,0.1);
    border: 1px solid rgba(249,115,22,0.18);
    border-radius: 50%;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 11px;
    font-weight: 700;
    color: #f97316;
    font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif;
    margin-top: 2px;
    letter-spacing: -0.04em;
}

.bubble-ai  { max-width: 88%; font-size: 13px; color: rgba(255,255,255,0.85); line-height: 1.7; font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif; }

.chat-empty {
    text-align: center;
    padding: 60px 0 40px;
    color: rgba(255,255,255,0.1);
    font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif;
    font-size: 10px;
    letter-spacing: 0.12em;
    text-transform: uppercase;
    font-weight: 500;
}

/* ── STICKY BOTTOM INPUT BAR ── */
.sticky-wrap {
    position: fixed;
    bottom: 0; left: 0; right: 0;
    height: 90px;
}
.sticky-inner { max-width: 900px; margin: 0 auto; padding: 0 24px; }

.stTextArea textarea {
    background: rgba(255,255,255,0.04) !important;
    border: 1px solid rgba(255,255,255,0.09) !important;
    border-radius: 8px !important;
    color: rgba(255,255,255,0.9) !important;
    font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif !important;
    font-size: 13px !important;
    padding: 12px 16px !important;
    resize: none !important;
    line-height: 1.6 !important;
    letter-spacing: 0em !important;
}
.stTextArea textarea:focus        { border-color: rgba(249,115,22,0.4) !important; box-shadow: 0 0 0 3px rgba(249,115,22,0.06) !important; outline: none !important; }
.stTextArea textarea::placeholder { color: rgba(255,255,255,0.18) !important; }
.stTextArea label                 { display: none !important; }
[data-testid="InputInstructions"] { display: none !important; }

/* ── PDF DOWNLOAD BUTTON ── */
.stDownloadButton button {
    background: rgba(255,255,255,0.04) !important;
    border: 1px solid rgba(255,255,255,0.09) !important;
    color: rgba(255,255,255,0.7) !important;
    border-radius: 6px !important;
    font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif !important;
    font-size: 12px !important;
    padding: 13px 8px !important;
    width: 100% !important;
    font-weight: 400 !important;
}
.stDownloadButton button:hover {
    background: rgba(249,115,22,0.08) !important;
    border-color: rgba(249,115,22,0.25) !important;
    color: #f97316 !important;
}

/* ── TEXT INPUT ── */
.stTextInput input {
    background: rgba(255,255,255,0.04) !important;
    border: 1px solid rgba(255,255,255,0.07) !important;
    border-radius: 6px !important;
    color: rgba(255,255,255,0.85) !important;
    font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif !important;
    font-size: 13px !important;
    padding: 8px 12px !important;
}
.stTextInput input:focus { border-color: rgba(249,115,22,0.38) !important; outline: none !important; }
.stTextInput label       { color: rgba(255,255,255,0.35) !important; font-size: 11px !important; font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif !important; }

/* ── DRAWING LIBRARY CARDS ── */
.lib-card {
    background: rgba(255,255,255,0.025);
    border: 1px solid rgba(255,255,255,0.06);
    border-radius: 8px;
    padding: 12px 14px;
    margin-bottom: 8px;
    transition: border-color 0.12s;
}
.lib-card:hover  { border-color: rgba(249,115,22,0.22); }
.lib-name        { font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif; font-size: 13px; font-weight: 600; color: #fff; margin-bottom: 4px; letter-spacing: -0.01em; }
.lib-meta        { font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif; font-size: 11px; color: rgba(255,255,255,0.25); }
.lib-tag         { display: inline-block; background: rgba(249,115,22,0.08); border: 1px solid rgba(249,115,22,0.18); color: rgba(249,115,22,0.85); font-size: 10px; padding: 2px 7px; border-radius: 4px; margin: 3px 3px 0 0; font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif; font-weight: 500; letter-spacing: 0.02em; }

/* ── ALERTS AND SPINNER ── */
[data-testid="stAlert"]     { background: rgba(249,115,22,0.06) !important; border: 1px solid rgba(249,115,22,0.15) !important; border-radius: 6px !important; font-size: 12px !important; font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif !important; }
[data-testid="stSpinner"] p { color: rgba(255,255,255,0.22) !important; font-size: 11px !important; font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif !important; }

/* ── FOOTER CREDIT ── */
.footer-txt      { font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif; font-size: 9px; color: rgba(255,255,255,0.12); text-align: center; padding: 4px 0 2px; letter-spacing: 0.06em; text-transform: uppercase; }
.footer-txt span { color: #f97316; }

/* ── SPLASH SCREEN ── */
#draft-ai-splash {
    position: fixed;
    inset: 0;
    background: #0a0a0a;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    z-index: 999999;
    animation: splashFade 0.5s ease 2.8s forwards;
}
@keyframes splashFade {
    from { opacity: 1; pointer-events: all; }
    to   { opacity: 0; pointer-events: none; }
}
.splash-title {
    font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif;
    font-size: 48px;
    font-weight: 700;
    letter-spacing: -0.04em;
    color: #fff;
    margin-bottom: 10px;
}
.splash-title span { color: #f97316; }
.splash-sub {
    font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif;
    font-size: 13px;
    font-weight: 400;
    color: rgba(255,255,255,0.3);
    letter-spacing: 0.12em;
    text-transform: uppercase;
    animation: splashSubFade 0.6s ease 0.4s both;
}
@keyframes splashSubFade {
    from { opacity: 0; transform: translateY(6px); }
    to   { opacity: 1; transform: translateY(0); }
}
.splash-bar-wrap {
    margin-top: 40px;
    width: 160px;
    height: 2px;
    background: rgba(255,255,255,0.06);
    border-radius: 2px;
    overflow: hidden;
}
.splash-bar {
    height: 100%;
    background: #f97316;
    border-radius: 2px;
    animation: splashBarFill 2.6s ease forwards;
}
@keyframes splashBarFill {
    from { width: 0%; }
    to   { width: 100%; }
}

</style>
""", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════
# SPLASH SCREEN — shown for 3 seconds on first load
# ══════════════════════════════════════════════════════════════════

if "splash_shown" not in st.session_state:
    st.session_state.splash_shown = True
    st.markdown("""
<div id="draft-ai-splash">
    <div class="splash-title">Draft <span>AI</span></div>
    <div class="splash-sub">Get your design analysis in seconds</div>
    <div class="splash-bar-wrap"><div class="splash-bar"></div></div>
</div>
""", unsafe_allow_html=True)

for k, v in [
    ("chat_history",         []),
    ("messages_display",     []),
    ("current_drawing_name", None),
    ("title_block_data",     None),
    ("active_tab",           "analyze"),
    ("show_revision_panel",  False), 
    ("uploader_key",         0),  # Toggle for revision comparison UI
]:
    if k not in st.session_state:
        st.session_state[k] = v

if "saved_chats" not in st.session_state:
    st.session_state.saved_chats = load_chats()


# ══════════════════════════════════════════════════════════════════
# SIDEBAR
# ══════════════════════════════════════════════════════════════════

with st.sidebar:

    # App branding
    st.markdown('<div class="sb-logo">Draft <span>AI</span></div>', unsafe_allow_html=True)
    st.markdown('<div class="sb-sub">by Rishi</div>', unsafe_allow_html=True)

    # Navigation tab switcher
    st.markdown('<div class="sb-label">Navigation</div>', unsafe_allow_html=True)
    if st.button("Analyze Drawing", use_container_width=True):
        st.session_state.active_tab = "analyze"
        st.rerun()
    if st.button("Drawing Library", use_container_width=True):
        st.session_state.active_tab = "library"
        st.rerun()

    # Chat history section
    st.markdown('<div class="sb-label">Chat History</div>', unsafe_allow_html=True)
    count = len(st.session_state.saved_chats)
    st.markdown(f'<div class="sb-quota"><span>{count}</span> / {MAX_CHATS} chats saved</div>', unsafe_allow_html=True)

    # New chat — clears current session
    if st.button("+ New Chat", use_container_width=True):
        st.session_state.chat_history          = []
        st.session_state.messages_display      = []
        st.session_state.current_drawing_name  = None
        st.session_state.title_block_data      = None
        st.session_state.current_drawing_image = None
        st.session_state.uploader_key         += 1
        st.rerun()

    st.markdown("<div style='height:4px'></div>", unsafe_allow_html=True)

    # List saved chats with load / delete buttons
    if not st.session_state.saved_chats:
        st.markdown(
            '<div style="font-size:11px;color:rgba(255,255,255,0.12);'
            'font-family:\'JetBrains Mono\',monospace;padding:4px 0;">No chats yet.</div>',
            unsafe_allow_html=True,
        )
    else:
        for name in reversed(list(st.session_state.saved_chats.keys())):
            cb, cd = st.columns([5, 1])
            with cb:
                if st.button(f"{name[:22]}", key=f"load_{name}"):
                    s = st.session_state.saved_chats[name]
                    st.session_state.messages_display      = s["messages_display"]
                    st.session_state.chat_history          = s["chat_history"]
                    st.session_state.current_drawing_name  = name
                    st.session_state.current_drawing_image = s.get("image")
                    st.session_state.active_tab            = "analyze"
                    st.rerun()
            with cd:
                if st.button("✕", key=f"del_{name}"):
                    del st.session_state.saved_chats[name]
                    save_chats(st.session_state.saved_chats)
                    st.rerun()


# ══════════════════════════════════════════════════════════════════
# TOP NAV — App title with spinning gear + white/orange color split
# ══════════════════════════════════════════════════════════════════

tab_label = "ANALYZE" if st.session_state.active_tab == "analyze" else "LIBRARY"

# Two-column nav row: hamburger button | title
nav_col1, nav_col2 = st.columns([0.1, 12])

with nav_col1:
    # Style only this column's button as an orange hamburger icon
    st.markdown("""<style>
    div[data-testid="column"]:first-child .stButton > button {
        background: rgba(249,115,22,0.15) !important;
        border: 1px solid rgba(249,115,22,0.4) !important;
        color: #f97316 !important;
        border-radius: 8px !important;
        font-size: 18px !important;
        padding: 6px 10px !important;
        width: auto !important;
        margin-top: 4px;
    }
    </style>""", unsafe_allow_html=True)

with nav_col2:
    # Spinning gear + "Draft" in white, "AI" in orange
    st.markdown("""
<div style="display:flex; align-items:center; gap:10px; margin-left:0px; margin-top:4px;">
    <span class="gear-spin" style="font-size:28px; line-height:1;">⚙️</span>
    <span style="font-family:'Helvetica Neue',Helvetica,Arial,sans-serif; font-size:30px; font-weight:700; color:#fff; letter-spacing:-0.04em;">Draft</span><span style="font-family:'Helvetica Neue',Helvetica,Arial,sans-serif; font-size:30px; font-weight:700; color:#f97316; letter-spacing:-0.04em;"> AI</span>
</div>
""", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════
# TAB: DRAWING LIBRARY
# ══════════════════════════════════════════════════════════════════

if st.session_state.active_tab == "library":
    lib = load_library()

    # ── Add new drawing to library ──
    st.markdown('<div class="section-label" style="margin-top:12px;">Add to Library</div>', unsafe_allow_html=True)
    add_file = st.file_uploader(
        "Add drawing", type=["png","jpg","jpeg","webp"],
        label_visibility="collapsed", key="lib_upload",
    )

    if add_file:
        size_mb  = check_file_size(add_file)
        is_valid, _ = validate_file(add_file)

        if size_mb > MAX_FILE_SIZE_MB:
            st.error(f"File too large ({size_mb:.1f} MB). Max is {MAX_FILE_SIZE_MB} MB.")
        elif not is_valid:
            st.error("Invalid file type. Only real PNG/JPEG/WEBP images accepted.")
        else:
            col_tag, col_note = st.columns([1, 1])
            with col_tag:
                tags = st.text_input("Tags (comma separated)", placeholder="shaft, tolerance, Rev-A", key="lib_tags")
            with col_note:
                notes = st.text_input("Notes (optional)", placeholder="Customer drawing, pending review", key="lib_notes")
            if st.button("Save to Library", type="primary", use_container_width=True):
                uid = add_to_library(add_file, tags, notes)
                st.success(f"Saved: {add_file.name}")
                st.rerun()

    st.markdown("<div style='height:1px;background:rgba(255,255,255,0.05);margin:14px 0'></div>", unsafe_allow_html=True)

    # ── Browse and search library ──
    st.markdown('<div class="section-label">Library</div>', unsafe_allow_html=True)
    search = st.text_input(
        "Search", placeholder="Search by name or tag...",
        label_visibility="collapsed", key="lib_search",
    )

    lib = load_library()  # Reload after possible new addition
    if not lib:
        st.markdown(
            '<div class="chat-empty">'
            '<div style="font-size:30px;opacity:0.15;margin-bottom:8px;">📚</div>'
            '<div>No drawings saved yet</div></div>',
            unsafe_allow_html=True,
        )
    else:
        # Filter by name or tag
        filtered = {
            k: v for k, v in lib.items()
            if not search
            or search.lower() in v["name"].lower()
            or any(search.lower() in t.lower() for t in v.get("tags", []))
        }

        st.markdown(
            f'<div style="font-size:11px;color:rgba(255,255,255,0.25);'
            f'font-family:JetBrains Mono,monospace;margin-bottom:10px;">'
            f'{len(filtered)} drawing{"s" if len(filtered) != 1 else ""} found</div>',
            unsafe_allow_html=True,
        )

        for uid, meta in reversed(list(filtered.items())):
            with st.container():
                tags_html = "".join(f'<span class="lib-tag">{t}</span>' for t in meta.get("tags", []))
                notes_txt = (
                    f'<div style="font-size:11px;color:rgba(255,255,255,0.25);margin-top:4px;">{meta["notes"]}</div>'
                    if meta.get("notes") else ""
                )
                st.markdown(f'''<div class="lib-card">
                    <div class="lib-name">📄 {meta["name"]}</div>
                    <div class="lib-meta">{meta["added"]}  ·  {meta["size_mb"]} MB</div>
                    {tags_html}{notes_txt}
                </div>''', unsafe_allow_html=True)

                c1, c2, c3 = st.columns([2, 2, 1])

                with c1:
                    # Open drawing in Analyze tab
                    if st.button("Open & Analyze", key=f"open_{uid}", use_container_width=True):
                        try:
                            with open(meta["path"], "rb") as f:
                                img_bytes = f.read()
                            import io
                            fake_file      = io.BytesIO(img_bytes)
                            fake_file.name = meta["name"]
                            st.session_state["_lib_open_file"]     = img_bytes
                            st.session_state["_lib_open_name"]     = meta["name"]
                            st.session_state.current_drawing_name  = meta["name"]
                            st.session_state.chat_history          = []
                            st.session_state.messages_display      = []
                            st.session_state.active_tab            = "analyze"
                            st.info("Drawing loaded — switch to Analyze tab and upload the file to start chatting.")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Could not open file: {e}")

                with c2:
                    # Download original file
                    try:
                        with open(meta["path"], "rb") as f:
                            file_bytes = f.read()
                        st.download_button(
                            "Download", data=file_bytes,
                            file_name=meta["name"],
                            use_container_width=True, key=f"dl_{uid}",
                        )
                    except:
                        st.button("Download", disabled=True, use_container_width=True, key=f"dl_{uid}")

                with c3:
                    # Delete from library
                    if st.button("Clear", key=f"libdel_{uid}", use_container_width=True, help="Remove from library"):
                        delete_from_library(uid)
                        st.rerun()

                st.markdown("<div style='height:4px'></div>", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════
# TAB: ANALYZE
# ══════════════════════════════════════════════════════════════════

else:

    # ── File uploader ──
    uploaded_file = st.file_uploader(
        "upload", type=["png","jpg","jpeg","webp"],
        label_visibility="collapsed",
        key=f"uploader_{st.session_state.uploader_key}",
    )

    # ── Show cached image only when no file is currently uploaded ──
    if not uploaded_file and st.session_state.get("current_drawing_image"):
        img = base64.b64decode(st.session_state.current_drawing_image)
        st.image(img, width=180)

    file_ok = False

    if uploaded_file:
        size_mb = check_file_size(uploaded_file)
        if size_mb > MAX_FILE_SIZE_MB:
            st.error(f"File too large: {size_mb:.1f} MB. Maximum is {MAX_FILE_SIZE_MB} MB.")
        else:
            is_valid, _ = validate_file(uploaded_file)
            if not is_valid:
                st.error("Invalid file. Only real PNG, JPEG, and WEBP images accepted.")
            else:
                file_ok = True
            st.image(uploaded_file, width=180)
            st.session_state.current_drawing_name = uploaded_file.name

            # Cache image as base64 for session persistence across reruns
            import base64
            uploaded_file.seek(0)
            img_bytes = uploaded_file.read()
            st.session_state.current_drawing_image = base64.b64encode(img_bytes).decode("utf-8")
            uploaded_file.seek(0)

    # ── Quick action buttons — Row 1: original 8 features ──
    st.markdown('<div class="section-label" style="margin-top:10px;">Quick Actions</div>', unsafe_allow_html=True)
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        q1 = st.button("Dimensions",      use_container_width=True)
        q5 = st.button("Summarize",       use_container_width=True)
    with c2:
        q2 = st.button("GD&T Analysis",   use_container_width=True)
        q6 = st.button("Design Concerns", use_container_width=True)
    with c3:
        q3 = st.button("Material Rec.",   use_container_width=True)
        q7 = st.button("Manufacturing",   use_container_width=True)
    with c4:
        q4 = st.button("Title Block",     use_container_width=True)
        q8 = st.button("View Type",       use_container_width=True)

    # ── Advanced Features — Row 2: 5 new features ──
    st.markdown('<div class="section-label" style="margin-top:20px;">Advanced Analysis</div>', unsafe_allow_html=True)
    a1, a2, a3, a4, a5 = st.columns(5)
    with a1:
        qa1 = st.button("Tolerance Analysis",     use_container_width=True, help="Analyse dimensional chains and worst-case fits")
    with a2:
        qa2 = st.button("DFM Analysis",            use_container_width=True, help="Score manufacturability 0-100 with breakdown")
    with a3:
        qa3 = st.button("Cost Breakdown",          use_container_width=True, help="Rough per-unit cost estimate across volumes")
    with a4:
        qa4 = st.button("Dimensional Check",     use_container_width=True, help="Find missing dimensions, tolerances & annotations")
    with a5:
        qa5 = st.button("Revision Diff",      use_container_width=True, help="Upload a second drawing to compare revisions")

    # ── Revision comparison panel (shown only when Compare Revisions is active) ──
    rev_file_b = None
    if qa5:
        st.session_state.show_revision_panel = not st.session_state.show_revision_panel

    if st.session_state.show_revision_panel:
        st.markdown(
            '<div style="background:rgba(249,115,22,0.05);border:1px solid rgba(249,115,22,0.2);'
            'border-radius:10px;padding:12px 16px;margin:8px 0;">'
            '<div style="font-size:11px;color:#f97316;font-family:JetBrains Mono,monospace;'
            'letter-spacing:1px;margin-bottom:8px;">REVISION COMPARISON — upload Rev B below</div>',
            unsafe_allow_html=True,
        )
        rev_file_b = st.file_uploader(
            "Upload Revision B",
            type=["png", "jpg", "jpeg", "webp"],
            label_visibility="collapsed",
            key="rev_b_uploader",
        )
        st.markdown('</div>', unsafe_allow_html=True)

    st.markdown("<div style='height:1px;background:rgba(255,255,255,0.05);margin:12px 0'></div>", unsafe_allow_html=True)

    # ── Chat message display ──
    if not st.session_state.messages_display:
        # Empty state
        st.markdown("""<div class="chat-empty">
            <div style="font-size:34px;opacity:1;margin-bottom:8px;">⚙️</div>
            <div style="color:#ffffff;">Upload a drawing and start asking</div>
        </div>""", unsafe_allow_html=True)
    else:
        for msg in st.session_state.messages_display:
            if msg["role"] == "user":
                # User message (right-aligned orange bubble)
                st.markdown(
                    f'<div class="msg-row user"><div class="bubble-user">{msg["content"]}</div></div>',
                    unsafe_allow_html=True,
                )
            else:
                content = msg["content"]
                # Title block — special table rendering
                if content.startswith("__TB__"):
                    bubble = render_title_block(content[6:])
                    st.markdown(
                        f'<div class="msg-row ai"><div class="ai-avatar">⚙️</div>'
                        f'<div class="bubble-ai" style="max-width:90%;">{bubble}</div></div>',
                        unsafe_allow_html=True,
                    )
                # Dimension table — special table rendering
                elif content.startswith("__DIM__"):
                    bubble = render_dim_table(content[7:])
                    st.markdown(
                        f'<div class="msg-row ai"><div class="ai-avatar">⚙️</div>'
                        f'<div class="bubble-ai" style="max-width:95%;">{bubble}</div></div>',
                        unsafe_allow_html=True,
                    )
                # Standard AI text response
                else:
                    st.markdown(
                        f'<div class="msg-row ai"><div class="ai-avatar">⚙️</div>'
                        f'<div class="bubble-ai">{fmt(content)}</div></div>',
                        unsafe_allow_html=True,
                    )

    # Footer credit line
    st.markdown(
        '<div class="footer-txt" style="margin-bottom:8px;color:#ffffff;">Draft AI &mdash;Made With ♥️ by Rishi</div>',
        unsafe_allow_html=True,
    )

    # ── Sticky bottom input bar ──
    st.markdown('<div class="sticky-wrap"><div class="sticky-inner">', unsafe_allow_html=True)

    custom_q = st.text_area(
        "msg", placeholder="Ask anything about the drawing...",
        label_visibility="collapsed", height=52,
    )
    col_ask, col_clear, col_pdf = st.columns([4, 0.9, 1], gap="small")

    with col_ask:
        ask_btn = st.button("Analyze", type="primary", use_container_width=True)

    with col_clear:
        if st.button("🗑️Clear", use_container_width=True, help="Clear chat"):
            st.session_state.chat_history     = []
            st.session_state.messages_display = []
            st.rerun()

    with col_pdf:
        if st.session_state.messages_display:
            pdf_buf = generate_pdf(
                st.session_state.messages_display,
                drawing_name=st.session_state.current_drawing_name or "drawing",
                title_block_data=st.session_state.title_block_data,
            )
            st.download_button(
                "📄Export PDF", data=pdf_buf,
                file_name="drawing_analysis.pdf",
                mime="application/pdf",
                use_container_width=True,
            )
        else:
            st.button("📄Export PDF", disabled=True, use_container_width=True)

    st.markdown('</div></div>', unsafe_allow_html=True)


    # ══════════════════════════════════════════
    # PROCESS — Determine which action to run
    # ══════════════════════════════════════════

    question       = None
    special_action = None

    if   q1:  special_action = "dimensions"
    elif q2:  special_action = "gdt"
    elif q3:  special_action = "material"
    elif q4:  special_action = "titleblock"
    elif q5:  question = "Give a comprehensive summary: drawing type, component description, key dimensions, materials, and special requirements."
    elif q6:  special_action = "design"
    elif q7:  special_action = "manufacturing"
    elif q8:  question = "Identify all views shown (front, side, top, isometric, section etc.) and explain what each view reveals about the component."
    elif qa1: special_action = "tolerance_stackup"
    elif qa2: special_action = "mfg_score"
    elif qa3: special_action = "cost_estimate"
    elif qa4: special_action = "missing_dims"
    elif ask_btn and custom_q:     question = custom_q
    elif ask_btn and not custom_q: st.warning("Please type a question first.")

    # Spinner messages and user-facing labels per action
    ACTION_MAP = {
        "dimensions":       ("Detecting dimensions...",            "Dimension Detection"),
        "gdt":              ("Analyzing GD&T...",          "GD&T Analysis"),
        "design":           ("Reviewing design concerns...",       "Design Concern Review"),
        "material":         ("Generating material analysis...",    "Material Recommendation"),
        "manufacturing":    ("Analyzing manufacturing methods...", "Manufacturing Suggestions"),
        "titleblock":       ("Reading title block...",             "Title Block"),
        "tolerance_stackup":("Calculating tolerance stack-up...",  "Tolerance Stack-Up Analysis"),
        "mfg_score":        ("Scoring manufacturability...",       "Manufacturability Score"),
        "cost_estimate":    ("Estimating part cost...",            "Cost Estimation"),
        "missing_dims":     ("Checking for missing dimensions...", "Missing Dimension Detection"),
    }

    # ── Special action handler ──
    if special_action:
        if not uploaded_file or not file_ok:
            st.warning("Please upload a valid engineering drawing first.")
        else:
            ip = get_client_ip()
            allowed, _ = check_rate_limit(ip)
            if not allowed:
                st.error("Rate limit reached: 2 requests/hour. Please try again later.")
            else:
                spinner_msg, user_label = ACTION_MAP[special_action]
                with st.spinner(spinner_msg):
                    uploaded_file.seek(0)
                    if   special_action == "dimensions":        result = detect_dimensions(uploaded_file)
                    elif special_action == "gdt":               result = analyze_gdt(uploaded_file)
                    elif special_action == "design":            result = analyze_design_concerns(uploaded_file)
                    elif special_action == "material":          result = analyze_material(uploaded_file)
                    elif special_action == "manufacturing":     result = analyze_manufacturing(uploaded_file)
                    elif special_action == "tolerance_stackup": result = analyze_tolerance_stackup(uploaded_file)
                    elif special_action == "mfg_score":         result = analyze_manufacturability_score(uploaded_file)
                    elif special_action == "cost_estimate":     result = estimate_cost(uploaded_file)
                    elif special_action == "missing_dims":      result = detect_missing_dimensions(uploaded_file)
                    elif special_action == "titleblock":
                        result = extract_title_block(uploaded_file)
                        st.session_state.title_block_data = result

                increment_rate_limit(ip)

                # Add special prefix so the renderer knows which template to use
                prefix     = {"dimensions": "__DIM__", "titleblock": "__TB__"}.get(special_action, "")
                ai_content = f"{prefix}{result}"

                st.session_state.messages_display.append({"role": "user",      "content": user_label})
                st.session_state.messages_display.append({"role": "ai",        "content": ai_content})
                st.session_state.chat_history.append(    {"role": "user",      "content": user_label})
                st.session_state.chat_history.append(    {"role": "assistant", "content": result})
                persist_chat()
                st.rerun()

    # ── Revision comparison handler (needs two files) ──
    if st.session_state.show_revision_panel and rev_file_b:
        if not uploaded_file or not file_ok:
            st.warning("Please upload the primary drawing (Rev A) using the upload box above first.")
        else:
            rev_size = check_file_size(rev_file_b)
            rev_valid, _ = validate_file(rev_file_b)
            if rev_size > MAX_FILE_SIZE_MB:
                st.error(f"Rev B file too large: {rev_size:.1f} MB.")
            elif not rev_valid:
                st.error("❌ Invalid Rev B file. Only PNG, JPEG, WEBP accepted.")
            else:
                ip = get_client_ip()
                allowed, _ = check_rate_limit(ip)
                if not allowed:
                    st.error("Rate limit reached: 2 requests/hour. Please try again later.")
                else:
                    with st.spinner("Comparing revisions..."):
                        uploaded_file.seek(0)
                        rev_file_b.seek(0)
                        result = compare_revisions(uploaded_file, rev_file_b)
                    increment_rate_limit(ip)

                    st.session_state.messages_display.append({"role": "user", "content": f"🔄 Compare Revisions: {uploaded_file.name} vs {rev_file_b.name}"})
                    st.session_state.messages_display.append({"role": "ai",   "content": result})
                    st.session_state.chat_history.append(    {"role": "user",      "content": "Compare drawing revisions"})
                    st.session_state.chat_history.append(    {"role": "assistant", "content": result})
                    st.session_state.show_revision_panel = False
                    persist_chat()
                    st.rerun()
    # ── Free-text question handler ──
    if question:
        if not uploaded_file or not file_ok:
            st.warning("Please upload a valid engineering drawing first.")
        else:
            ip      = get_client_ip()
            allowed = True  # Rate limiting bypassed for general questions
            if not allowed:
                pass
            else:
                with st.spinner("Analyzing..."):
                    uploaded_file.seek(0)
                    answer = analyze_drawing(uploaded_file, question, st.session_state.chat_history)
                increment_rate_limit(ip)
                st.session_state.messages_display.append({"role": "user",      "content": question})
                st.session_state.messages_display.append({"role": "ai",        "content": answer})
                st.session_state.chat_history.append(    {"role": "user",      "content": question})
                st.session_state.chat_history.append(    {"role": "assistant", "content": answer})
                persist_chat()
                st.rerun()