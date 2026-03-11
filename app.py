# +------------------------------------------------------------------+
# �                        Draft AI � app.py                        �
# �         AI-powered engineering drawing analysis tool            �
# |                            2025                                 |
# +------------------------------------------------------------------+

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
    # -- 5 new features --
    analyze_tolerance_stackup,
    analyze_manufacturability_score,
    estimate_cost,
    detect_missing_dimensions,
    compare_revisions,
    # -- batch analysis --
    batch_analyze_drawing,
    generate_batch_excel,
    generate_batch_pdf,
    # -- pdf support --
    pdf_to_image_bytes,
    PDF2IMAGE_AVAILABLE,
    # -- BOM Generator --
    generate_bom_pdf,
    generate_bom,
    generate_bom_excel,
)
import json, os, re, time, base64, shutil
from datetime import datetime
from pathlib import Path


# ------------------------------------------------------------------
# CONSTANTS
# ------------------------------------------------------------------

CHATS_FILE          = "saved_chats.json"     # Persisted chat sessions
LIBRARY_FILE        = "drawing_library.json" # Drawing library metadata
LIBRARY_DIR         = "drawing_library"      # Folder for saved drawings

MAX_CHATS           = 20   # Max saved chats before oldest is dropped
MAX_FILE_SIZE_MB    = 10   # Max upload size in megabytes

# Ensure drawing library folder exists on startup
Path(LIBRARY_DIR).mkdir(exist_ok=True)


# ------------------------------------------------------------------
# SECURITY � File validation & rate limiting
# ------------------------------------------------------------------

def validate_file(f):
    """
    Validate uploaded file using magic bytes (not just file extension).
    Supports PNG, JPEG, WEBP, and PDF formats.
    Returns (is_valid: bool, file_type: str | None)
    """
    h = f.read(12)
    f.seek(0)
    if h[:8] == b'\x89PNG\r\n\x1a\n':              return True, "png"
    if h[:3] == b'\xff\xd8\xff':                    return True, "jpeg"
    if h[:4] == b'RIFF' and h[8:12] == b'WEBP':    return True, "webp"
    if h[:4] == b'%PDF':                            return True, "pdf"
    return False, None


def check_file_size(f):
    """Return file size in megabytes without consuming the stream."""
    f.seek(0, 2)
    size = f.tell()
    f.seek(0)
    return size / (1024 * 1024)




# ------------------------------------------------------------------
# DRAWING LIBRARY � Save, load, search, delete drawings
# ------------------------------------------------------------------

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


# ------------------------------------------------------------------
# CHAT PERSISTENCE � Save and restore chat sessions
# ------------------------------------------------------------------

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


# ------------------------------------------------------------------
# MESSAGE FORMATTER � Convert AI text to styled HTML bubbles
# ------------------------------------------------------------------

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

        # Unordered list (- or �)
        elif s.startswith("- ") or s.startswith("� ") or re.match(r'^[⚙️]\s', s):
            if in_list != "ul":
                if in_list: html += f'</{in_list}>'
                html   += '<ul style="margin:4px 0 4px 20px;padding:0;color:#fff;">'
                in_list = "ul"
            item  = re.sub(r'^[-⚙️]\s*', '', s)
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
            label    = str(d.get("label",     "�"))
            value    = str(d.get("value",     "�"))
            unit     = str(d.get("unit",      "�"))
            tol      = str(d.get("tolerance", "�"))
            location = str(d.get("location",  "�"))
            dtype    = str(d.get("type",      "�"))
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
            <div style="padding:8px 14px;font-size:10px;font-family:DM Mono,monospace;color:#f97316;letter-spacing:2px;text-transform:uppercase;border-bottom:1px solid rgba(249,115,22,0.12);">
                📐 DIMENSIONS DETECTED � {len(dims)} found
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
            v     = parts[1].strip() if len(parts) > 1 else "�"
            if v and v.lower() != "not specified":
                rows += (
                    f'<tr>'
                    f'<td style="padding:7px 14px;color:rgba(255,255,255,0.45);font-size:12px;'
                    f'font-family:DM Mono,monospace;white-space:nowrap;'
                    f'border-bottom:1px solid rgba(255,255,255,0.04);">{k}</td>'
                    f'<td style="padding:7px 14px;color:#fff;font-size:13px;'
                    f'border-bottom:1px solid rgba(255,255,255,0.04);">{v}</td>'
                    f'</tr>'
                )
    return f'''<div style="background:rgba(249,115,22,0.05);border:1px solid rgba(249,115,22,0.18);border-radius:10px;overflow:hidden;">
        <div style="padding:8px 14px;font-size:10px;font-family:DM Mono,monospace;color:#f97316;
                    letter-spacing:2px;text-transform:uppercase;border-bottom:1px solid rgba(249,115,22,0.12);">
            🏷 TITLE BLOCK
        </div>
        <table style="width:100%;border-collapse:collapse;">{rows}</table>
    </div>'''


# ------------------------------------------------------------------
@st.dialog("Drawing Preview", width="large")
def open_drawing_preview(image_bytes):
    encoded_image = base64.b64encode(image_bytes).decode("utf-8")
    st.markdown(
        f"""
        <div style="display:flex;align-items:center;justify-content:center;min-height:78vh;">
            <img
                src="data:image/png;base64,{encoded_image}"
                alt="Drawing preview"
                style="
                    max-width:min(92vw, 1400px);
                    max-height:78vh;
                    width:auto;
                    height:auto;
                    object-fit:contain;
                    display:block;
                    margin:0 auto;
                    border-radius:8px;
                    border:1px solid rgba(255,255,255,0.06);
                "
            />
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_drawing_preview(image_bytes, key_suffix):
    preview_col, action_col = st.columns([3, 1])
    with preview_col:
        st.image(image_bytes, width=180)
    with action_col:
        st.markdown("<div style='height:10px'></div>", unsafe_allow_html=True)
        if st.button("Enlarge", key=f"enlarge_{key_suffix}", use_container_width=True):
            open_drawing_preview(image_bytes)

# PAGE CONFIG
# ------------------------------------------------------------------

st.set_page_config(
    page_title="Draft AI",
    page_icon=":pencil:",
    layout="wide",
    initial_sidebar_state="expanded",
)


# ------------------------------------------------------------------
# GLOBAL CSS STYLES
# ------------------------------------------------------------------

st.markdown("""
<style>

/* ── FONTS ── */
@import url('https://fonts.googleapis.com/css2?family=DM+Serif+Display:ital@0;1&family=DM+Mono:wght@400;500&family=Syne:wght@400;500;600;700;800&display=swap');

*, *::before, *::after { box-sizing: border-box; }

html, body {
    background: #0b0b0b !important;
    font-family: 'Syne', sans-serif;
    letter-spacing: -0.01em;
    overflow-x: hidden !important;
    overflow-y: auto !important;
    min-height: 100vh !important;
}
[data-testid="stAppViewContainer"] {
    background: #0b0b0b !important;
    overflow-x: hidden !important;
    overflow-y: auto !important;
    min-height: 100vh !important;
}
[data-testid="stMain"] {
    background: #0b0b0b !important;
    overflow-x: hidden !important;
    overflow-y: auto !important;
    min-height: 100vh !important;
}
[data-testid="stHeader"] { background: transparent !important; height: 0 !important; }

/* Hide ALL scrollbars by default */
::-webkit-scrollbar { width: 0px !important; height: 0px !important; display: none !important; }
* { scrollbar-width: none !important; -ms-overflow-style: none !important; }

/* ── GLOW ── */
[data-testid="stAppViewContainer"]::before {
    content: '';
    position: fixed; top: 0; left: 0; width: 100%; height: 100%;
    background:
        radial-gradient(ellipse 70% 50% at 10% 5%,  rgba(249,115,22,0.05) 0%, transparent 60%),
        radial-gradient(ellipse 50% 40% at 90% 90%,  rgba(249,115,22,0.03) 0%, transparent 60%);
    pointer-events: none; z-index: 0;
}

/* ── LAYOUT ── */
.block-container {
    max-width: 980px !important;
    margin: 0 auto !important;
    padding: 0 16px 170px 16px !important;
    min-height: calc(100vh - 24px) !important;
    height: auto !important;
    max-height: unset !important;
    overflow: visible !important;
}
.stDeployButton, #MainMenu, footer { display: none !important; }

/* ── FIXED TOP BAR ── */
.top-bar {
    position: sticky; top: 0; z-index: 200;
    background: rgba(11,11,11,0.92);
    backdrop-filter: blur(16px);
    -webkit-backdrop-filter: blur(16px);
    border-bottom: 1px solid rgba(255,255,255,0.06);
    padding: 12px 4px;
    margin-bottom: 10px;
    display: flex; align-items: center; justify-content: space-between;
}
.top-bar-left  { display: flex; align-items: center; gap: 12px; }
.top-bar-logo  {
    font-family: 'Syne', sans-serif; font-size: 22px; font-weight: 800;
    letter-spacing: -0.05em; color: #fff; line-height: 1;
}
.top-bar-logo span { color: #f97316; }
.top-bar-badge {
    font-family: 'DM Mono', monospace; font-size: 9px; font-weight: 600;
    background: rgba(249,115,22,0.12); border: 1px solid rgba(249,115,22,0.25);
    color: #f97316; padding: 2px 8px; border-radius: 100px;
    letter-spacing: 0.08em; text-transform: uppercase;
}
.top-bar-file {
    font-family: 'DM Mono', monospace; font-size: 11px;
    color: rgba(255,255,255,0.35); background: rgba(255,255,255,0.04);
    border: 1px solid rgba(255,255,255,0.07); border-radius: 6px;
    padding: 4px 10px; max-width: 220px;
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.top-bar-file .dot { color: #22c55e; margin-right: 5px; }

/* ── SIDEBAR TOGGLE ── */
[data-testid="collapsedControl"] {
    position: fixed !important; top: 14px !important; left: 14px !important;
    z-index: 99999 !important; display: flex !important; visibility: visible !important; opacity: 1 !important;
    background: rgba(249,115,22,0.08) !important;
    border: 1px solid rgba(249,115,22,0.2) !important;
    border-radius: 6px !important; padding: 5px 9px !important; cursor: pointer !important;
    transition: all 0.15s !important;
}
[data-testid="collapsedControl"]:hover { background: rgba(249,115,22,0.15) !important; }
[data-testid="collapsedControl"] svg { color: #f97316 !important; fill: #f97316 !important; width: 15px !important; height: 15px !important; }

/* ── SIDEBAR ── */
[data-testid="stSidebar"] {
    background: #0d0d0d !important;
    border-right: 1px solid rgba(255,255,255,0.05) !important;
}
[data-testid="stSidebar"] > div:first-child { padding: 24px 14px !important; }

.sb-logo { font-family: 'Syne', sans-serif; font-size: 19px; font-weight: 800; letter-spacing: -0.04em; color: #fff; margin-top: -6px; margin-bottom: 1px; }
.sb-logo span { color: #f97316; }
.sb-sub  { font-size: 9px; color: rgba(255,255,255,0.15); font-family: 'DM Mono', monospace; letter-spacing: 0.1em; margin-bottom: 20px; text-transform: uppercase; }

.sb-label {
    font-family: 'DM Mono', monospace; font-size: 9px; letter-spacing: 0.14em;
    text-transform: uppercase; color: rgba(255,255,255,0.18);
    margin-bottom: 4px; margin-top: 20px; padding-left: 2px;
}
.sb-quota      { font-family: 'DM Mono', monospace; font-size: 10px; color: rgba(255,255,255,0.15); margin-bottom: 8px; padding-left: 2px; }
.sb-quota span { color: #f97316; font-weight: 600; }

/* Sidebar nav — ghost buttons with active-state left bar */
[data-testid="stSidebar"] .stButton > button {
    background: transparent !important;
    border: 1px solid transparent !important;
    color: rgba(255,255,255,0.4) !important;
    border-radius: 7px !important;
    font-family: 'Syne', sans-serif !important;
    font-size: 12px !important; font-weight: 500 !important;
    padding: 8px 12px !important; width: 100% !important;
    text-align: left !important; margin-bottom: 1px !important;
    transition: all 0.15s !important;
    height: auto !important; min-height: unset !important; max-height: unset !important;
    justify-content: flex-start !important;
}
[data-testid="stSidebar"] .stButton > button:hover {
    background: rgba(249,115,22,0.07) !important;
    border-color: rgba(249,115,22,0.12) !important;
    color: #f97316 !important;
}

/* ── GEAR SPIN ── */
@keyframes spinGear { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }
.gear-spin { display: inline-block; animation: spinGear 8s linear infinite; }

/* ── UPLOAD ZONE ── */
[data-testid="stFileUploader"] > div {
    border: 1.5px dashed rgba(249,115,22,0.18) !important;
    background: rgba(249,115,22,0.025) !important;
    border-radius: 10px !important; padding: 8px 14px !important;
    transition: all 0.2s !important;
    text-align: center !important;
}
[data-testid="stFileUploader"] > div:hover {
    border-color: rgba(249,115,22,0.45) !important;
    background: rgba(249,115,22,0.045) !important;
}
[data-testid="stFileUploader"] label { display: none !important; }
[data-testid="stFileUploader"] button {
    background: rgba(249,115,22,0.1) !important;
    border: 1px solid rgba(249,115,22,0.22) !important;
    color: #f97316 !important; border-radius: 6px !important;
    font-family: 'Syne', sans-serif !important; font-size: 11px !important; font-weight: 600 !important;
}
[data-testid="stFileUploaderDropzoneInstructions"] {
    font-size: 10px !important; color: rgba(255,255,255,0.18) !important;
    font-family: 'DM Mono', monospace !important;
}
[data-testid="stImage"] img { border-radius: 10px !important; border: 1px solid rgba(255,255,255,0.07) !important; object-fit: contain !important; }
[data-testid="stImage"] button { display: none !important; }

/* ── UPLOAD HINT ── */
.upload-hint {
    display: flex; align-items: center; justify-content: center;
    gap: 8px; padding: 2px 0 0px;
    font-family: 'DM Mono', monospace; font-size: 10px;
    color: rgba(255,255,255,0.15); letter-spacing: 0.05em;
}
.upload-hint span { color: rgba(249,115,22,0.5); }

/* ── SECTION LABELS ── */
.section-label {
    font-family: 'DM Mono', monospace; font-size: 9px; letter-spacing: 0.16em;
    text-transform: uppercase; color: rgba(255,255,255,0.28);
    margin-bottom: 6px; font-weight: 500;
    display: flex; align-items: center; gap: 8px;
}
.section-label::after {
    content: ''; flex: 1; height: 1px;
    background: rgba(255,255,255,0.05);
}

/* ── ACTION BUTTONS ── */
.stButton, .stButton > div,
[data-testid="stDownloadButton"], [data-testid="stDownloadButton"] > div,
.stDownloadButton, .stDownloadButton > div, .stDownloadButton > div > div { width: 100% !important; }

.stButton > button,
[data-testid="stDownloadButton"] button,
.stDownloadButton button {
    background: rgba(255,255,255,0.028) !important;
    border: 1px solid rgba(255,255,255,0.07) !important;
    color: rgba(255,255,255,0.55) !important;
    border-radius: 9px !important;
    font-family: 'Syne', sans-serif !important;
    font-size: 11.5px !important; font-weight: 500 !important;
    padding: 8px !important; width: 100% !important;
    height: 44px !important; min-height: 44px !important; max-height: 44px !important;
    margin: 0 !important; transition: all 0.15s ease !important;
    text-align: center !important; display: flex !important;
    align-items: center !important; justify-content: center !important;
    line-height: 1.3 !important; white-space: normal !important;
    gap: 4px !important;
}
.stButton > button:hover {
    background: rgba(249,115,22,0.09) !important;
    border-color: rgba(249,115,22,0.28) !important;
    color: #f97316 !important;
    transform: translateY(-1px) !important;
    box-shadow: 0 6px 18px rgba(249,115,22,0.1) !important;
}

/* Primary button */
.stButton > button[kind="primary"] {
    background: #f97316 !important; border: none !important;
    color: #000 !important; font-weight: 700 !important;
    font-size: 13px !important; border-radius: 9px !important;
    height: 44px !important; min-height: 44px !important; max-height: 44px !important;
    box-shadow: 0 0 24px rgba(249,115,22,0.25) !important;
    letter-spacing: 0.01em !important;
}
.stButton > button[kind="primary"]:hover {
    background: #fb923c !important;
    box-shadow: 0 0 36px rgba(249,115,22,0.35) !important;
    transform: translateY(-1px) !important;
}

/* ── CHAT AREA ── */
.chat-section-header {
    display: flex; align-items: center; gap: 10px;
    padding: 6px 0 4px;
    font-family: 'DM Mono', monospace; font-size: 9px;
    color: rgba(255,255,255,0.2); letter-spacing: 0.14em; text-transform: uppercase;
    border-top: 1px solid rgba(255,255,255,0.05);
    margin-top: 4px; margin-bottom: 6px;
}
.chat-section-header::after { content: ''; flex: 1; height: 1px; background: rgba(255,255,255,0.04); }

.msg-row      { display: flex; margin-bottom: 16px; }
.msg-row.user { justify-content: flex-end; }
.msg-row.ai   { justify-content: flex-start; gap: 10px; align-items: flex-start; }

.bubble-user {
    background: rgba(249,115,22,0.09);
    border: 1px solid rgba(249,115,22,0.18);
    border-radius: 14px 14px 3px 14px;
    padding: 10px 15px; max-width: 68%;
    font-size: 13px; font-family: 'Syne', sans-serif;
    color: rgba(255,255,255,0.9); line-height: 1.65;
}

.ai-avatar {
    width: 26px; height: 26px; flex-shrink: 0;
    background: linear-gradient(135deg, rgba(249,115,22,0.2), rgba(249,115,22,0.05));
    border: 1px solid rgba(249,115,22,0.22);
    border-radius: 8px; display: flex; align-items: center; justify-content: center;
    font-size: 13px; margin-top: 1px;
}

.bubble-ai {
    max-width: 90%; font-size: 13px;
    color: rgba(255,255,255,0.82); line-height: 1.75;
    font-family: 'Syne', sans-serif;
}

/* ── EMPTY STATE ── */
.chat-empty {
    text-align: center; padding: 16px 20px 8px;
}
.chat-empty-icon {
    font-size: 28px; margin-bottom: 8px; opacity: 0.6;
    animation: floatIcon 3s ease-in-out infinite;
}
@keyframes floatIcon {
    0%, 100% { transform: translateY(0); }
    50%       { transform: translateY(-6px); }
}
.chat-empty-title {
    font-family: 'Syne', sans-serif; font-size: 13px; font-weight: 600;
    color: rgba(255,255,255,0.4); margin-bottom: 4px;
}
.chat-empty-sub {
    font-family: 'DM Mono', monospace; font-size: 11px;
    color: rgba(255,255,255,0.2); letter-spacing: 0.04em; margin-bottom: 28px;
}
.suggestion-chips { display: flex; flex-wrap: wrap; justify-content: center; gap: 8px; margin-top: 4px; }
.chip {
    background: rgba(255,255,255,0.04); border: 1px solid rgba(255,255,255,0.08);
    border-radius: 100px; padding: 7px 14px;
    font-family: 'DM Mono', monospace; font-size: 11px;
    color: rgba(255,255,255,0.35); cursor: pointer;
    transition: all 0.15s;
}
.chip:hover { border-color: rgba(249,115,22,0.3); color: #f97316; background: rgba(249,115,22,0.06); }

/* Suggestion chip buttons — pill shaped */
div[data-testid="stHorizontalBlock"] div[data-testid="column"] > div > div > div > button[key^="chip"] {
    border-radius: 100px !important;
    height: 34px !important; min-height: 34px !important; max-height: 34px !important;
    font-family: 'DM Mono', monospace !important; font-size: 10px !important;
    font-weight: 400 !important; color: rgba(255,255,255,0.4) !important;
    background: rgba(255,255,255,0.03) !important;
    border: 1px solid rgba(255,255,255,0.08) !important;
    white-space: nowrap !important;
}

/* ── STICKY BAR ── */
.sticky-wrap {
    position: fixed; left: 0; right: 0;
    bottom: max(12px, env(safe-area-inset-bottom));
    background: transparent;
    padding-top: 0; z-index: 100;
    pointer-events: none;
}
.sticky-inner { max-width: 980px; margin: 0 auto; padding: 0 20px 0; pointer-events: auto; }

.stTextArea textarea {
    background: rgba(255,255,255,0.04) !important;
    border: 1px solid rgba(255,255,255,0.09) !important;
    border-radius: 12px !important; color: rgba(255,255,255,0.9) !important;
    font-family: 'Syne', sans-serif !important; font-size: 13px !important;
    padding: 13px 16px !important; resize: none !important; line-height: 1.6 !important;
    transition: border-color 0.2s, box-shadow 0.2s !important;
}
.stTextArea textarea:focus {
    border-color: rgba(249,115,22,0.4) !important;
    box-shadow: 0 0 0 3px rgba(249,115,22,0.06) !important; outline: none !important;
}
.stTextArea textarea::placeholder { color: rgba(255,255,255,0.18) !important; }
.stTextArea label { display: none !important; }
[data-testid="InputInstructions"] { display: none !important; }

.stDownloadButton button:hover {
    background: rgba(249,115,22,0.07) !important;
    border-color: rgba(249,115,22,0.22) !important;
    color: #f97316 !important;
}

/* ── TEXT INPUT ── */
.stTextInput input {
    background: rgba(255,255,255,0.04) !important;
    border: 1px solid rgba(255,255,255,0.07) !important;
    border-radius: 8px !important; color: rgba(255,255,255,0.85) !important;
    font-family: 'Syne', sans-serif !important; font-size: 13px !important; padding: 8px 12px !important;
}
.stTextInput input:focus { border-color: rgba(249,115,22,0.35) !important; outline: none !important; }
.stTextInput label { color: rgba(255,255,255,0.3) !important; font-size: 10px !important; font-family: 'DM Mono', monospace !important; letter-spacing: 0.08em !important; text-transform: uppercase !important; }

/* ── LIBRARY CARDS ── */
.lib-card {
    background: rgba(255,255,255,0.02); border: 1px solid rgba(255,255,255,0.06);
    border-radius: 10px; padding: 14px 16px; margin-bottom: 10px;
    transition: border-color 0.15s, background 0.15s;
}
.lib-card:hover { border-color: rgba(249,115,22,0.2); background: rgba(249,115,22,0.02); }
.lib-name { font-family: 'Syne', sans-serif; font-size: 13px; font-weight: 700; color: #fff; margin-bottom: 4px; }
.lib-meta { font-family: 'DM Mono', monospace; font-size: 10px; color: rgba(255,255,255,0.22); }
.lib-tag  {
    display: inline-block; background: rgba(249,115,22,0.07); border: 1px solid rgba(249,115,22,0.16);
    color: rgba(249,115,22,0.8); font-size: 9px; padding: 2px 7px; border-radius: 3px;
    margin: 3px 3px 0 0; font-family: 'DM Mono', monospace; font-weight: 500; letter-spacing: 0.04em;
}

/* ── ALERTS & SPINNER ── */
[data-testid="stAlert"] {
    background: rgba(249,115,22,0.05) !important; border: 1px solid rgba(249,115,22,0.12) !important;
    border-radius: 8px !important; font-size: 12px !important; font-family: 'Syne', sans-serif !important;
}
[data-testid="stSpinner"] p { color: rgba(255,255,255,0.25) !important; font-size: 11px !important; font-family: 'DM Mono', monospace !important; }
[data-testid="stCheckbox"] label { font-family: 'Syne', sans-serif !important; font-size: 12px !important; color: rgba(255,255,255,0.55) !important; }
[data-testid="stProgressBar"] > div > div { background: #f97316 !important; }

/* ── FOOTER ── */
.footer-txt { font-family: 'DM Mono', monospace; font-size: 9px; color: rgba(255,255,255,0.08); text-align: center; padding: 4px 0 2px; letter-spacing: 0.08em; text-transform: uppercase; }
.footer-txt span { color: rgba(249,115,22,0.4); }

/* ── SPLASH ── */
#draft-ai-splash {
    position: fixed; inset: 0; background: #0b0b0b;
    display: flex; flex-direction: column; align-items: center; justify-content: center;
    z-index: 999999; animation: splashFade 0.5s ease 2.8s forwards;
}
@keyframes splashFade { from { opacity: 1; pointer-events: all; } to { opacity: 0; pointer-events: none; } }
.splash-title { font-family: 'Syne', sans-serif; font-size: 56px; font-weight: 800; letter-spacing: -0.05em; color: #fff; margin-bottom: 6px; }
.splash-title span { color: #f97316; }
.splash-sub  { font-family: 'DM Mono', monospace; font-size: 11px; color: rgba(255,255,255,0.2); letter-spacing: 0.14em; text-transform: uppercase; animation: splashSubFade 0.6s ease 0.4s both; }
@keyframes splashSubFade { from { opacity: 0; transform: translateY(8px); } to { opacity: 1; transform: translateY(0); } }
.splash-bar-wrap { margin-top: 48px; width: 120px; height: 1px; background: rgba(255,255,255,0.08); overflow: hidden; }
.splash-bar { height: 100%; background: #f97316; animation: splashBarFill 2.6s ease forwards; box-shadow: 0 0 12px rgba(249,115,22,0.6); }
@keyframes splashBarFill { from { width: 0%; } to { width: 100%; } }

/* ── SCROLLBAR — hidden everywhere ── */
::-webkit-scrollbar { display: none !important; width: 0 !important; }
* { scrollbar-width: none !important; }


/* FINAL READABILITY PASS */
.top-bar-file,
.sb-sub,
.sb-label,
.sb-quota,
.section-label,
.chat-section-header,
.chat-empty-title,
.chat-empty-sub,
.chip,
div[data-testid="stHorizontalBlock"] div[data-testid="column"] > div > div > div > button[key^="chip"],
.stButton > button,
[data-testid="stDownloadButton"] button,
.stDownloadButton button,
.stTextArea textarea::placeholder,
.stTextInput label,
.lib-meta,
.footer-txt,
[data-testid="stSpinner"] p,
[data-testid="stCheckbox"] label,
[data-testid="stFileUploaderDropzoneInstructions"],
.upload-hint,
.upload-hint span {
    color: rgba(255,255,255,0.92) !important;
    opacity: 1 !important;
}
.section-label::after,
.chat-section-header::after {
    background: rgba(255,255,255,0.16) !important;
}

</style>
""", unsafe_allow_html=True)


# ------------------------------------------------------------------
# SPLASH SCREEN � shown for 3 seconds on first load
# ------------------------------------------------------------------

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
    ("uploader_key",         0),
    ("batch_results",        []),
    ("batch_running",        False),
]:
    if k not in st.session_state:
        st.session_state[k] = v

if "saved_chats" not in st.session_state:
    st.session_state.saved_chats = load_chats()


# ------------------------------------------------------------------
# SIDEBAR
# ------------------------------------------------------------------

with st.sidebar:

    # App branding
    st.markdown('<div class="sb-logo">Draft <span>AI</span></div>', unsafe_allow_html=True)

    # Navigation tab switcher
    st.markdown('<div class="sb-label">Navigation</div>', unsafe_allow_html=True)
    if st.button("Analyze Drawing", use_container_width=True):
        st.session_state.active_tab = "analyze"
        st.rerun()
    if st.button("Batch Analysis", use_container_width=True):
        st.session_state.active_tab = "batch"
        st.rerun()
    if st.button("Drawing Library", use_container_width=True):
        st.session_state.active_tab = "library"
        st.rerun()
    if st.button("BOM Generator", use_container_width=True):
        st.session_state.active_tab = "bom"
        st.rerun()

    # Chat history section
    st.markdown('<div class="sb-label">Chat History</div>', unsafe_allow_html=True)
    count = len(st.session_state.saved_chats)
    st.markdown(f'<div class="sb-quota"><span>{count}</span> / {MAX_CHATS} chats saved</div>', unsafe_allow_html=True)

    # New chat � clears current session
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
                if st.button("X", key=f"del_{name}"):
                    del st.session_state.saved_chats[name]
                    save_chats(st.session_state.saved_chats)
                    st.rerun()


# ------------------------------------------------------------------
# TOP NAV � App title with spinning gear + white/orange color split
# ------------------------------------------------------------------

# ── TOP BAR ──
_fname = st.session_state.get("current_drawing_name")
_file_pill = (
    f'''<div class="top-bar-file"><span class="dot">●</span>{_fname}</div>'''
    if _fname else ""
)
st.markdown(f"""
<div class="top-bar">
  <div class="top-bar-left">
    <div class="top-bar-logo">Draft<span> AI</span></div>
    <div class="top-bar-badge">Beta</div>
    {_file_pill}
  </div>
  <div style="font-family:DM Mono,monospace;font-size:10px;color:rgba(255,255,255,0.15);letter-spacing:0.06em;">
    <span class="gear-spin" style="display:inline-block;margin-right:6px;">⚙</span>GPT-4o Vision
  </div>
</div>
""", unsafe_allow_html=True)


# ------------------------------------------------------------------
# TAB: BATCH ANALYSIS
# ------------------------------------------------------------------

if st.session_state.active_tab == "batch":

    st.markdown('<div class="section-label" style="margin-top:12px;">Batch Analysis</div>', unsafe_allow_html=True)
    st.markdown("""
<div style="background:rgba(249,115,22,0.05);border:1px solid rgba(249,115,22,0.15);border-radius:8px;padding:12px 16px;margin-bottom:14px;">
    <div style="font-size:13px;color:rgba(255,255,255,0.85);font-family:Syne,sans-serif;">
        Upload up to <b style="color:#f97316;">20 drawings</b> at once. Draft AI will analyze each one and generate a
        comparison report — exportable as <b style="color:#f97316;">Excel</b> or <b style="color:#f97316;">PDF</b>.
    </div>
</div>
""", unsafe_allow_html=True)

    batch_files = st.file_uploader(
        "Upload drawings for batch analysis",
        type=["png", "jpg", "jpeg", "webp", "pdf"],
        accept_multiple_files=True,
        label_visibility="collapsed",
        key="batch_uploader",
    )

    # Analysis options
    st.markdown('<div class="section-label" style="margin-top:10px;">Analysis Options</div>', unsafe_allow_html=True)
    opt1, opt2, opt3 = st.columns(3)
    with opt1:
        opt_status    = st.checkbox("Production Status",      value=True)
    with opt2:
        opt_score     = st.checkbox("Manufacturability Score", value=True)
    with opt3:
        opt_cost      = st.checkbox("Cost Estimate",           value=True)

    # File list preview
    if batch_files:
        st.markdown(f'<div class="section-label" style="margin-top:10px;">{len(batch_files)} drawings selected</div>', unsafe_allow_html=True)
        if len(batch_files) > 20:
            st.error("Maximum 20 drawings per batch. Please remove some files.")
            batch_files = batch_files[:20]

        # Show thumbnails grid
        cols = st.columns(5)
        for i, f in enumerate(batch_files):
            with cols[i % 5]:
                f.seek(0)
                st.image(f.read(), caption=f.name[:18], use_container_width=True)
                f.seek(0)

        st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)

        run_col, clear_col = st.columns([3, 1])
        with run_col:
            run_batch = st.button("Run Batch Analysis", type="primary", use_container_width=True)
        with clear_col:
            if st.button("Clear", use_container_width=True):
                st.session_state.batch_results = []
                st.rerun()

        if run_batch:
            st.session_state.batch_results = []
            progress_bar  = st.progress(0, text="Starting batch analysis...")
            status_text   = st.empty()
            results_so_far = []

            for idx, f in enumerate(batch_files):
                pct  = int((idx / len(batch_files)) * 100)
                progress_bar.progress(pct, text=f"Analyzing {idx+1}/{len(batch_files)}: {f.name[:30]}...")
                status_text.markdown(
                    f'<div style="font-size:11px;color:rgba(255,255,255,0.4);font-family:\'Syne\',Helvetica,Arial,sans-serif;">'
                    f'Processing: {f.name}</div>',
                    unsafe_allow_html=True
                )
                f.seek(0)
                result = batch_analyze_drawing(f, filename=f.name)
                results_so_far.append(result)

            progress_bar.progress(100, text="Analysis complete.")
            status_text.empty()
            st.session_state.batch_results = results_so_far
            st.rerun()

    # ── Results display ──
    if st.session_state.batch_results:
        results = st.session_state.batch_results
        total   = len(results)
        ready   = sum(1 for r in results if "Ready" in r.get("status",""))
        needs   = sum(1 for r in results if "Revision" in r.get("status",""))
        rework  = sum(1 for r in results if "Major" in r.get("status","") or "Failed" in r.get("status",""))
        scores  = [r.get("manufacturability_score",0) for r in results if isinstance(r.get("manufacturability_score"),(int,float))]
        avg_sc  = round(sum(scores)/len(scores)) if scores else "—"

        # Stats row
        st.markdown("<div style='height:6px'></div>", unsafe_allow_html=True)
        m1, m2, m3, m4, m5 = st.columns(5)
        for col, label, val, color in [
            (m1, "Total",           total,   "#ffffff"),
            (m2, "Production Ready", ready,  "#16a34a"),
            (m3, "Needs Revision",  needs,   "#d97706"),
            (m4, "Major Rework",    rework,  "#dc2626"),
            (m5, "Avg Mfg. Score",  f"{avg_sc}/100", "#f97316"),
        ]:
            with col:
                st.markdown(f"""
<div style="background:rgba(255,255,255,0.03);border:1px solid rgba(255,255,255,0.07);
border-radius:8px;padding:12px 14px;text-align:center;">
    <div style="font-size:22px;font-weight:700;color:{color};font-family:Syne,sans-serif;">{val}</div>
    <div style="font-size:10px;color:rgba(255,255,255,0.3);margin-top:2px;font-family:Syne,sans-serif;text-transform:uppercase;letter-spacing:0.08em;">{label}</div>
</div>""", unsafe_allow_html=True)

        st.markdown("<div style='height:14px'></div>", unsafe_allow_html=True)

        # Drawing cards
        st.markdown('<div class="section-label">Results</div>', unsafe_allow_html=True)
        for i, r in enumerate(results, 1):
            status = r.get("status","—")
            score  = r.get("manufacturability_score","—")
            if "Ready" in status:
                status_color = "#16a34a"; status_bg = "rgba(22,163,74,0.08)"; border_c = "rgba(22,163,74,0.2)"
            elif "Revision" in status:
                status_color = "#d97706"; status_bg = "rgba(217,119,6,0.08)";  border_c = "rgba(217,119,6,0.2)"
            else:
                status_color = "#dc2626"; status_bg = "rgba(220,38,38,0.08)";  border_c = "rgba(220,38,38,0.2)"

            issues_html = ""
            for iss in r.get("critical_issues",[]):
                issues_html += f'<div style="font-size:11px;color:#dc2626;margin-top:3px;">Critical: {iss}</div>'
            for w in r.get("warnings",[]):
                issues_html += f'<div style="font-size:11px;color:#d97706;margin-top:3px;">Warning: {w}</div>'

            st.markdown(f"""
<div style="background:{status_bg};border:1px solid {border_c};border-radius:8px;padding:12px 16px;margin-bottom:8px;">
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;">
        <div style="font-size:13px;font-weight:600;color:#fff;font-family:Syne,sans-serif;">
            {i}. {r.get("drawing_name","—")}
            <span style="font-size:10px;color:rgba(255,255,255,0.35);font-weight:400;margin-left:8px;">{r.get("part_number","")}</span>
        </div>
        <div style="display:flex;gap:8px;align-items:center;">
            <span style="font-size:10px;color:#f97316;font-family:Syne,sans-serif;">Score: <b>{score}/100</b></span>
            <span style="font-size:10px;background:{status_bg};color:{status_color};border:1px solid {border_c};padding:2px 8px;border-radius:4px;font-family:Syne,sans-serif;">{status}</span>
        </div>
    </div>
    <div style="font-size:11px;color:rgba(255,255,255,0.5);font-family:Syne,sans-serif;margin-bottom:4px;">
        {r.get("drawing_type","—")} &nbsp;·&nbsp; {r.get("complexity","—")} complexity &nbsp;·&nbsp;
        Est. cost: <b style="color:rgba(255,255,255,0.7);">${r.get("estimated_cost_usd","—")}</b> &nbsp;·&nbsp;
        Process: {r.get("recommended_process","—")} &nbsp;·&nbsp;
        Tolerance risk: {r.get("tolerance_risk","—")}
    </div>
    <div style="font-size:11px;color:rgba(255,255,255,0.4);font-family:Syne,sans-serif;">{r.get("summary","—")}</div>
    {issues_html}
</div>""", unsafe_allow_html=True)

        # Export buttons
        st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)
        st.markdown('<div class="section-label">Export Report</div>', unsafe_allow_html=True)
        ex1, ex2, ex3 = st.columns(3)

        with ex1:
            excel_buf = generate_batch_excel(results)
            if excel_buf:
                st.download_button(
                    "Download Excel Report",
                    data=excel_buf,
                    file_name=f"draft_ai_batch_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True,
                )
        with ex2:
            pdf_buf = generate_batch_pdf(results)
            if pdf_buf:
                st.download_button(
                    "Download PDF Report",
                    data=pdf_buf,
                    file_name=f"draft_ai_batch_{datetime.now().strftime('%Y%m%d_%H%M')}.pdf",
                    mime="application/pdf",
                    use_container_width=True,
                )
        with ex3:
            if st.button("Clear Results", use_container_width=True):
                st.session_state.batch_results = []
                st.rerun()

    # ── Quick question bar for batch tab ──
    st.markdown('<div class="footer-txt" style="margin-top:20px;">Draft <span>AI</span> &nbsp;|&nbsp; Made with ♥ by Rishi</div>', unsafe_allow_html=True)
    st.markdown('<div class="sticky-wrap"><div class="sticky-inner">', unsafe_allow_html=True)
    batch_q = st.text_area("batchq", placeholder="Ask anything about the drawing...", label_visibility="collapsed", height=52, key="batch_chat_input")
    bq_col1, bq_col2 = st.columns([5, 1], gap="small")
    with bq_col1:
        bq_btn = st.button("Analyze", type="primary", use_container_width=True, key="batch_ask_btn")
    with bq_col2:
        if st.button("🗑️ Clear", use_container_width=True, key="batch_clear_btn", help="Clear chat"):
            st.session_state.chat_history     = []
            st.session_state.messages_display = []
            st.rerun()
    st.markdown('</div></div>', unsafe_allow_html=True)
    if bq_btn and batch_q:
        st.session_state.active_tab = "analyze"
        st.session_state["_pending_question"] = batch_q
        st.rerun()
    elif bq_btn and not batch_q:
        st.warning("Please type a question first.")


# ------------------------------------------------------------------
# TAB: BOM GENERATOR
# ------------------------------------------------------------------

elif st.session_state.active_tab == "bom":

    st.markdown('<div class="section-label" style="margin-top:12px;">BOM Generator</div>', unsafe_allow_html=True)

    # Hero banner
    st.markdown("""
<div style="background:linear-gradient(135deg,rgba(249,115,22,0.12) 0%,rgba(249,115,22,0.04) 100%);
            border:1px solid rgba(249,115,22,0.25);border-radius:12px;padding:18px 22px;margin-bottom:18px;">
    <div style="font-size:15px;font-weight:700;color:#fff;font-family:Syne,sans-serif;margin-bottom:6px;">
        Auto-extract a Bill of Materials in seconds
    </div>
    <div style="font-size:13px;color:rgba(255,255,255,0.6);line-height:1.6;">
        Upload any <b style="color:#f97316;">assembly drawing</b> — Draft AI reads every part balloon, title block,
        and annotation to produce a structured BOM. Export to <b style="color:#f97316;">Excel</b> when done.
    </div>
</div>
""", unsafe_allow_html=True)

    # Upload zone
    bom_file = st.file_uploader(
        "Upload assembly drawing",
        type=["png", "jpg", "jpeg", "webp", "pdf"],
        label_visibility="collapsed",
        key="bom_uploader",
    )

    if bom_file:
        size_mb = check_file_size(bom_file)
        is_valid, ftype = validate_file(bom_file)
        if size_mb > MAX_FILE_SIZE_MB:
            st.error(f"File too large: {size_mb:.1f} MB. Max {MAX_FILE_SIZE_MB} MB.")
        elif not is_valid:
            st.error("Invalid file type. PNG, JPEG, WEBP, or PDF only.")
        else:
            # PDF conversion
            img_bytes = None
            if ftype == "pdf":
                if PDF2IMAGE_AVAILABLE:
                    ok, result = pdf_to_image_bytes(bom_file)
                    if ok:
                        import io
                        img_bytes = result
                        bom_file  = io.BytesIO(result)
                        bom_file.name = "drawing.png"
                    else:
                        st.error(f"PDF conversion failed: {result}")
                else:
                    st.warning("pdf2image not installed — PDF preview unavailable.")

            # Preview + action
            st.markdown("<div style='height:4px'></div>", unsafe_allow_html=True)
            prev_col, info_col = st.columns([3, 2])
            with prev_col:
                bom_file.seek(0)
                st.image(bom_file.read() if img_bytes is None else img_bytes, use_container_width=True)
                bom_file.seek(0)
            with info_col:
                st.markdown(f"""
<div style="background:rgba(255,255,255,0.03);border:1px solid rgba(255,255,255,0.08);border-radius:10px;padding:16px 18px;margin-bottom:12px;">
    <div style="font-size:10px;color:rgba(255,255,255,0.3);font-family:DM Mono,monospace;letter-spacing:.12em;text-transform:uppercase;margin-bottom:10px;">File Info</div>
    <div style="display:flex;flex-direction:column;gap:8px;">
        <div><span style="font-size:11px;color:rgba(255,255,255,0.4);">Name</span><br>
             <span style="font-size:13px;color:#fff;font-weight:500;">{bom_file.name}</span></div>
        <div><span style="font-size:11px;color:rgba(255,255,255,0.4);">Size</span><br>
             <span style="font-size:13px;color:#f97316;font-weight:600;">{size_mb:.2f} MB</span></div>
        <div><span style="font-size:11px;color:rgba(255,255,255,0.4);">Type</span><br>
             <span style="font-size:13px;color:#fff;">{(ftype or 'image').upper()}</span></div>
    </div>
</div>
""", unsafe_allow_html=True)
                run_bom = st.button("Generate BOM", type="primary", use_container_width=True)
                st.markdown("""
<div style="font-size:11px;color:rgba(255,255,255,0.25);margin-top:8px;line-height:1.5;">
    AI will scan all part balloons, title block fields, and annotations to build the BOM.
</div>
""", unsafe_allow_html=True)

            if run_bom:
                with st.spinner("🔍 Scanning drawing and extracting BOM..."):
                    bom_file.seek(0)
                    try:
                        bom_data = generate_bom(bom_file)
                        st.session_state["bom_result"] = bom_data
                        st.rerun()
                    except Exception as e:
                        st.error(f"BOM extraction failed: {e}")

    # ── Results ──────────────────────────────────────────────────────
    if "bom_result" in st.session_state and st.session_state["bom_result"]:
        bom   = st.session_state["bom_result"]
        items = bom.get("items", [])

        st.markdown("<div style='height:6px'></div>", unsafe_allow_html=True)

        # ── Stat cards row ────────────────────────────────────────────
        total_qty = sum(int(it.get("quantity", 1)) for it in items)
        materials = len(set(it.get("material", "—") for it in items if it.get("material") and it.get("material") != "—"))

        s1, s2, s3, s4 = st.columns(4)
        for col, label, value, sub in [
            (s1, "ASSEMBLY",      bom.get("assembly_name", "—"),    None),
            (s2, "DRAWING NO.",   bom.get("drawing_number", "—"),   None),
            (s3, "UNIQUE PARTS",  str(len(items)),                  f"{total_qty} total qty"),
            (s4, "REVISION",      bom.get("revision", "—"),         f"{materials} materials"),
        ]:
            with col:
                st.markdown(f"""
<div style="background:rgba(249,115,22,0.06);border:1px solid rgba(249,115,22,0.18);
            border-radius:10px;padding:14px 16px;text-align:center;">
    <div style="font-size:9px;color:rgba(255,255,255,0.35);font-family:DM Mono,monospace;
                letter-spacing:.12em;text-transform:uppercase;margin-bottom:6px;">{label}</div>
    <div style="font-size:16px;font-weight:700;color:#f97316;font-family:Syne,sans-serif;
                white-space:nowrap;overflow:hidden;text-overflow:ellipsis;" title="{value}">{value}</div>
    {f'<div style="font-size:10px;color:rgba(255,255,255,0.3);margin-top:4px;">{sub}</div>' if sub else ''}
</div>""", unsafe_allow_html=True)

        st.markdown("<div style='height:14px'></div>", unsafe_allow_html=True)

        # ── BOM table ─────────────────────────────────────────────────
        rows_html = ""
        for i, item in enumerate(items):
            bg = "rgba(255,255,255,0.015)" if i % 2 == 0 else "rgba(255,255,255,0.035)"
            qty_val = item.get('quantity', 1)
            rows_html += f"""<tr style="background:{bg};">
                <td style="padding:10px 14px;color:#f97316;font-weight:700;font-size:14px;text-align:center;width:48px;">{item.get('item_no', i+1)}</td>
                <td style="padding:10px 14px;color:rgba(255,255,255,0.45);font-size:11px;font-family:'DM Mono',monospace;white-space:nowrap;">{item.get('part_number','—')}</td>
                <td style="padding:10px 14px;color:#fff;font-size:13px;font-weight:500;">{item.get('description','—')}</td>
                <td style="padding:10px 14px;color:#f97316;font-weight:700;font-size:15px;text-align:center;width:52px;">{qty_val}</td>
                <td style="padding:10px 14px;color:rgba(255,255,255,0.6);font-size:12px;">{item.get('material','—')}</td>
                <td style="padding:10px 14px;color:rgba(255,255,255,0.4);font-size:11px;">{item.get('standard','—')}</td>
                <td style="padding:10px 14px;color:rgba(255,255,255,0.35);font-size:11px;">{item.get('finish','—')}</td>
                <td style="padding:10px 14px;color:rgba(255,255,255,0.25);font-size:11px;font-style:italic;">{item.get('notes','')}</td>
            </tr>"""

        st.markdown(f"""
<div style="background:rgba(15,15,15,0.6);border:1px solid rgba(249,115,22,0.2);
            border-radius:12px;overflow:hidden;box-shadow:0 4px 24px rgba(0,0,0,0.3);">
    <div style="padding:10px 16px;background:rgba(249,115,22,0.08);border-bottom:1px solid rgba(249,115,22,0.15);
                display:flex;align-items:center;justify-content:space-between;">
        <span style="font-size:11px;font-family:'DM Mono',monospace;color:#f97316;
                     letter-spacing:.15em;text-transform:uppercase;font-weight:600;">📋 Bill of Materials</span>
        <span style="font-size:11px;color:rgba(255,255,255,0.3);font-family:'DM Mono',monospace;">
            {len(items)} parts · {total_qty} total qty
        </span>
    </div>
    <div style="overflow-x:auto;">
    <table style="width:100%;border-collapse:collapse;min-width:720px;">
        <thead>
        <tr style="border-bottom:1px solid rgba(255,255,255,0.06);">
            <th style="padding:8px 14px;text-align:center;font-size:9px;color:rgba(255,255,255,0.2);font-weight:600;letter-spacing:.1em;">ITEM</th>
            <th style="padding:8px 14px;text-align:left;font-size:9px;color:rgba(255,255,255,0.2);font-weight:600;letter-spacing:.1em;">PART NO.</th>
            <th style="padding:8px 14px;text-align:left;font-size:9px;color:rgba(255,255,255,0.2);font-weight:600;letter-spacing:.1em;">DESCRIPTION</th>
            <th style="padding:8px 14px;text-align:center;font-size:9px;color:rgba(255,255,255,0.2);font-weight:600;letter-spacing:.1em;">QTY</th>
            <th style="padding:8px 14px;text-align:left;font-size:9px;color:rgba(255,255,255,0.2);font-weight:600;letter-spacing:.1em;">MATERIAL</th>
            <th style="padding:8px 14px;text-align:left;font-size:9px;color:rgba(255,255,255,0.2);font-weight:600;letter-spacing:.1em;">STANDARD</th>
            <th style="padding:8px 14px;text-align:left;font-size:9px;color:rgba(255,255,255,0.2);font-weight:600;letter-spacing:.1em;">FINISH</th>
            <th style="padding:8px 14px;text-align:left;font-size:9px;color:rgba(255,255,255,0.2);font-weight:600;letter-spacing:.1em;">NOTES</th>
        </tr>
        </thead>
        <tbody>{rows_html}</tbody>
    </table>
    </div>
    <div style="padding:10px 16px;font-size:12px;color:rgba(255,255,255,0.3);
                border-top:1px solid rgba(255,255,255,0.05);font-style:italic;">
        {bom.get('summary', '')}
    </div>
</div>""", unsafe_allow_html=True)

        st.markdown("<div style='height:16px'></div>", unsafe_allow_html=True)

        # ── Export + actions row ──────────────────────────────────────
        excel_buf = generate_bom_excel(bom)
        pdf_buf   = generate_bom_pdf(bom)
        dl_col, pdf_col, clear_col = st.columns([3, 3, 1])
        with dl_col:
            if excel_buf:
                st.download_button(
                    "⬇  Download BOM as Excel",
                    data=excel_buf,
                    file_name=f"BOM_{bom.get('assembly_name','drawing').replace(' ','_')}_{datetime.now().strftime('%Y%m%d')}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True,
                    type="primary",
                )
        with pdf_col:
            if pdf_buf:
                st.download_button(
                    "📄  Download BOM as PDF",
                    data=pdf_buf,
                    file_name=f"BOM_{bom.get('assembly_name','drawing').replace(' ','_')}_{datetime.now().strftime('%Y%m%d')}.pdf",
                    mime="application/pdf",
                    use_container_width=True,
                )
        with clear_col:
            if st.button("🗑 Clear", use_container_width=True, help="Remove current BOM result"):
                del st.session_state["bom_result"]
                st.rerun()

    # ── Quick question bar for BOM tab ──
    st.markdown('<div class="footer-txt" style="margin-top:20px;">Draft <span>AI</span> &nbsp;|&nbsp; Made with ♥ by Rishi</div>', unsafe_allow_html=True)
    st.markdown('<div class="sticky-wrap"><div class="sticky-inner">', unsafe_allow_html=True)
    bom_q = st.text_area("bomq", placeholder="Ask anything about the drawing...", label_visibility="collapsed", height=52, key="bom_chat_input")
    bomq_col1, bomq_col2 = st.columns([5, 1], gap="small")
    with bomq_col1:
        bomq_btn = st.button("Analyze", type="primary", use_container_width=True, key="bom_ask_btn")
    with bomq_col2:
        if st.button("🗑️ Clear", use_container_width=True, key="bom_clear_btn", help="Clear chat"):
            st.session_state.chat_history     = []
            st.session_state.messages_display = []
            st.rerun()
    st.markdown('</div></div>', unsafe_allow_html=True)
    if bomq_btn and bom_q:
        st.session_state.active_tab = "analyze"
        st.session_state["_pending_question"] = bom_q
        st.rerun()
    elif bomq_btn and not bom_q:
        st.warning("Please type a question first.")

# ------------------------------------------------------------------
# TAB: DRAWING LIBRARY
# ------------------------------------------------------------------

elif st.session_state.active_tab == "library":
    lib = load_library()

    # -- Add new drawing to library --
    st.markdown('<div class="section-label" style="margin-top:12px;">Add to Library</div>', unsafe_allow_html=True)
    add_file = st.file_uploader(
        "Add drawing", type=["png","jpg","jpeg","webp","pdf"],
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

    # -- Browse and search library --
    st.markdown('<div class="section-label">Library</div>', unsafe_allow_html=True)
    search = st.text_input(
        "Search", placeholder="Search by name or tag...",
        label_visibility="collapsed", key="lib_search",
    )

    lib = load_library()  # Reload after possible new addition
    if not lib:
        st.markdown(
            '<div class="chat-empty">'
            '<div style="font-size:30px;opacity:0.15;margin-bottom:8px;">⚙️</div>'
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
            f'font-family:DM Mono,monospace;margin-bottom:10px;">'
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
                    <div class="lib-meta">{meta["added"]}  �  {meta["size_mb"]} MB</div>
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
                            st.info("Drawing loaded � switch to Analyze tab and upload the file to start chatting.")
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


# ------------------------------------------------------------------
# TAB: ANALYZE
# ------------------------------------------------------------------

else:

    # -- File uploader --
    uploaded_file = st.file_uploader(
        "upload", type=["png","jpg","jpeg","webp","pdf"],
        label_visibility="collapsed",
        key=f"uploader_{st.session_state.uploader_key}",
    )

    # -- If file is removed, clear cache immediately so stale image never shows --
    if not uploaded_file:
        st.session_state.current_drawing_image = None
        st.session_state.current_drawing_name  = None
        st.markdown('''<div class="upload-hint"><span>⬆</span> Drop your engineering drawing to begin &nbsp;·&nbsp; PNG · JPEG · WEBP · max 10 MB</div>''', unsafe_allow_html=True)

    file_ok = False

    if uploaded_file:
        size_mb = check_file_size(uploaded_file)
        if size_mb > MAX_FILE_SIZE_MB:
            st.error(f"File too large: {size_mb:.1f} MB. Maximum is {MAX_FILE_SIZE_MB} MB.")
        else:
            is_valid, file_type = validate_file(uploaded_file)
            if not is_valid:
                st.error("Invalid file. Only PNG, JPEG, WEBP, and PDF files accepted.")
            elif file_type == "pdf":
                with st.spinner("Converting PDF drawing to image..."):
                    ok, result = pdf_to_image_bytes(uploaded_file)
                if not ok:
                    st.error(f"Could not convert PDF: {result}")
                else:
                    import io as _io
                    png_buf = _io.BytesIO(result)
                    png_buf.name = uploaded_file.name.rsplit(".", 1)[0] + ".png"
                    uploaded_file = png_buf
                    file_ok = True
                    st.success("PDF converted — analyzing first page.")
                    uploaded_file.seek(0)
                    img_bytes = uploaded_file.read()
                    uploaded_file.seek(0)
                    render_drawing_preview(img_bytes, uploaded_file.name)
                    st.session_state.current_drawing_name = uploaded_file.name
                    st.session_state.current_drawing_image = base64.b64encode(img_bytes).decode("utf-8")
            else:
                file_ok = True
                uploaded_file.seek(0)
                img_bytes = uploaded_file.read()
                uploaded_file.seek(0)
                render_drawing_preview(img_bytes, uploaded_file.name)
                st.session_state.current_drawing_name = uploaded_file.name
                st.session_state.current_drawing_image = base64.b64encode(img_bytes).decode("utf-8")

    # -- Quick action buttons --
    st.markdown('<div class="section-label" style="margin-top:8px;">Quick Analysis</div>', unsafe_allow_html=True)
    c1, c2, c3, c4 = st.columns(4, gap="small")
    with c1:
        q1 = st.button("📐  Dimensions",       use_container_width=True)
        q5 = st.button("📝  Summarize",        use_container_width=True)
    with c2:
        q2 = st.button("🎯  GD&T Analysis",    use_container_width=True)
        q6 = st.button("⚠️  Design Concerns",  use_container_width=True)
    with c3:
        q3 = st.button("🧱  Material Rec.",    use_container_width=True)
        q7 = st.button("🏭  Manufacturing",    use_container_width=True)
    with c4:
        q4 = st.button("🏷️  Title Block",      use_container_width=True)
        q8 = st.button("👁️  View Type",        use_container_width=True)

    # -- Advanced Features --
    st.markdown('<div class="section-label" style="margin-top:10px;">Advanced Analysis</div>', unsafe_allow_html=True)
    a1, a2, a3, a4, a5 = st.columns(5, gap="small")
    with a1:
        qa1 = st.button("⚖️  Tolerance",       use_container_width=True, help="Analyse dimensional chains and worst-case fits")
    with a2:
        qa2 = st.button("🔬  DFM Score",       use_container_width=True, help="Score manufacturability 0-100 with breakdown")
    with a3:
        qa3 = st.button("💰  Cost Est.",       use_container_width=True, help="Rough per-unit cost estimate across volumes")
    with a4:
        qa4 = st.button("🔍  Dim. Check",      use_container_width=True, help="Find missing dimensions, tolerances & annotations")
    with a5:
        qa5 = st.button("🔄  Rev. Diff",       use_container_width=True, help="Upload a second drawing to compare revisions")

    # -- Revision comparison panel (shown only when Compare Revisions is active) --
    rev_file_b = None
    if qa5:
        st.session_state.show_revision_panel = not st.session_state.show_revision_panel

    if st.session_state.show_revision_panel:
        st.markdown(
            '<div style="background:rgba(249,115,22,0.05);border:1px solid rgba(249,115,22,0.2);'
            'border-radius:10px;padding:12px 16px;margin:8px 0;">'
            '<div style="font-size:11px;color:#f97316;font-family:DM Mono,monospace;'
            'letter-spacing:1px;margin-bottom:8px;">REVISION COMPARISON � upload Rev B below</div>',
            unsafe_allow_html=True,
        )
        rev_file_b = st.file_uploader(
            "Upload Revision B",
            type=["png", "jpg", "jpeg", "webp", "pdf"],
            label_visibility="collapsed",
            key="rev_b_uploader",
        )
        st.markdown('</div>', unsafe_allow_html=True)

    # -- Chat section --
    st.markdown('''<div class="chat-section-header">Conversation</div>''', unsafe_allow_html=True)

    # Enable scroll only when chat has messages — no visible scrollbar
    if st.session_state.messages_display:
        st.markdown("""<style>
[data-testid="stMain"] {
    overflow-y: scroll !important;
    height: 100vh !important;
    max-height: 100vh !important;
    scrollbar-width: none !important;
    -ms-overflow-style: none !important;
}
[data-testid="stMain"]::-webkit-scrollbar { display: none !important; width: 0 !important; }
.block-container {
    height: auto !important;
    max-height: unset !important;
    overflow: visible !important;
    padding-bottom: 220px !important;
}
</style>""", unsafe_allow_html=True)

    # suggestion chip state
    chip_question = None

    # -- Chat message display --
    if not st.session_state.messages_display:
        st.markdown("""
<div class="chat-empty">
  <div class="chat-empty-icon">⚙️</div>
  <div class="chat-empty-title">No analysis yet</div>
  <div class="chat-empty-sub">Upload a drawing above, then tap a suggestion or ask anything</div>
</div>""", unsafe_allow_html=True)
        # Real clickable suggestion buttons
        sc1, sc2, sc3, sc4 = st.columns(4, gap="small")
        with sc1:
            if st.button("Critical tolerances?", use_container_width=True, key="chip1"):
                chip_question = "What are the critical tolerances in this drawing?"
        with sc2:
            if st.button("GD&T issues?", use_container_width=True, key="chip2"):
                chip_question = "Find and explain all GD&T symbols and flag any issues."
        with sc3:
            if st.button("Production ready?", use_container_width=True, key="chip3"):
                chip_question = "Is this drawing production ready? List any blockers."
        with sc4:
            if st.button("Suggest material", use_container_width=True, key="chip4"):
                chip_question = "Suggest the best material for this part and explain why."
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
                # Title block � special table rendering
                if content.startswith("__TB__"):
                    bubble = render_title_block(content[6:])
                    st.markdown(
                        f'<div class="msg-row ai"><div class="ai-avatar">⚙️</div>'
                        f'<div class="bubble-ai" style="max-width:90%;">{bubble}</div></div>',
                        unsafe_allow_html=True,
                    )
                # Dimension table � special table rendering
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

    st.markdown('<div class="footer-txt" style="margin-top:20px;">Draft <span>AI</span> &nbsp;|&nbsp; Made with ♥ by Rishi</div>', unsafe_allow_html=True)

    # -- Bottom input bar --
    st.markdown("""
<div class="sticky-wrap"><div class="sticky-inner">
<script>
(function() {
    // Move sticky-wrap to body so position:fixed works correctly
    var el = document.querySelector('.sticky-wrap');
    if (el && el.parentElement !== document.body) {
        document.body.appendChild(el);
    }
})();
</script>
""", unsafe_allow_html=True)

    custom_q = st.text_area(
        "msg", placeholder="Ask anything about the drawing...",
        label_visibility="collapsed", height=52,
    )
    col_ask, col_clear, col_pdf = st.columns([4, 1, 1], gap="small")

    with col_ask:
        ask_btn = st.button("Analyze", type="primary", use_container_width=True)

    with col_clear:
        if st.button("\U0001F5D1\uFE0F Clear", use_container_width=True, help="Clear chat"):
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
                "\U0001F4C4 Export PDF", data=pdf_buf,
                file_name="drawing_analysis.pdf",
                mime="application/pdf",
                use_container_width=True,
            )
        else:
            st.button("\U0001F4C4 Export PDF", disabled=True, use_container_width=True)

    st.markdown('</div></div>', unsafe_allow_html=True)


    # ------------------------------------------
    # PROCESS � Determine which action to run
    # ------------------------------------------

    question       = None
    special_action = None
    if 'chip_question' not in dir(): chip_question = None
    # Pick up questions forwarded from batch/BOM tabs
    if st.session_state.get('_pending_question'):
        question = st.session_state.pop('_pending_question')

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
    elif chip_question:            question = chip_question
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

    # -- Special action handler --
    if special_action:
        if not uploaded_file or not file_ok:
            st.warning("Please upload a valid engineering drawing first.")
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

                # Add special prefix so the renderer knows which template to use
                prefix     = {"dimensions": "__DIM__", "titleblock": "__TB__"}.get(special_action, "")
                ai_content = f"{prefix}{result}"

                st.session_state.messages_display.append({"role": "user",      "content": user_label})
                st.session_state.messages_display.append({"role": "ai",        "content": ai_content})
                st.session_state.chat_history.append(    {"role": "user",      "content": user_label})
                st.session_state.chat_history.append(    {"role": "assistant", "content": result})
                persist_chat()
                st.rerun()

    # -- Revision comparison handler (needs two files) --
    if st.session_state.show_revision_panel and rev_file_b:
        if not uploaded_file or not file_ok:
            st.warning("Please upload the primary drawing (Rev A) using the upload box above first.")
        else:
            rev_size = check_file_size(rev_file_b)
            rev_valid, _ = validate_file(rev_file_b)
            if rev_size > MAX_FILE_SIZE_MB:
                st.error(f"Rev B file too large: {rev_size:.1f} MB.")
            elif not rev_valid:
                st.error("? Invalid Rev B file. Only PNG, JPEG, WEBP accepted.")
            else:
                with st.spinner("Comparing revisions..."):
                    uploaded_file.seek(0)
                    rev_file_b.seek(0)
                    result = compare_revisions(uploaded_file, rev_file_b)

                st.session_state.messages_display.append({"role": "user", "content": f"🔄 Compare Revisions: {uploaded_file.name} vs {rev_file_b.name}"})
                st.session_state.messages_display.append({"role": "ai",   "content": result})
                st.session_state.chat_history.append(    {"role": "user",      "content": "Compare drawing revisions"})
                st.session_state.chat_history.append(    {"role": "assistant", "content": result})
                st.session_state.show_revision_panel = False
                persist_chat()
                st.rerun()
    # -- Free-text question handler --
    if question:
        if not uploaded_file or not file_ok:
            st.warning("Please upload a valid engineering drawing first.")
        else:
            with st.spinner("Analyzing..."):
                uploaded_file.seek(0)
                answer = analyze_drawing(uploaded_file, question, st.session_state.chat_history)
            st.session_state.messages_display.append({"role": "user",      "content": question})
            st.session_state.messages_display.append({"role": "ai",        "content": answer})
            st.session_state.chat_history.append(    {"role": "user",      "content": question})
            st.session_state.chat_history.append(    {"role": "assistant", "content": answer})
            persist_chat()
            st.rerun()