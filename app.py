# +------------------------------------------------------------------+
# �                        Draft AI � app.py                        �
# �         AI-powered engineering drawing analysis tool            �
# |                            2025                                 |
# +------------------------------------------------------------------+

import streamlit as st
import streamlit.components.v1 as components
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
    # -- Standards Checker --
    check_drawing_standards,
)
import json
import os
import io
import re
import time
import base64
import hashlib
import hmac
from datetime import datetime
from pathlib import Path


def _normalize_pair_code(value):
    if value is None:
        return ""
    if isinstance(value, list):
        value = value[0] if value else ""
    return str(value).strip()


def _read_pair_code_from_query():
    try:
        return _normalize_pair_code(st.query_params.get("pair", ""))
    except Exception:
        return ""


def _read_auth_intent_from_query() -> bool:
    try:
        raw = st.query_params.get("auth", "")
    except Exception:
        return False
    if isinstance(raw, list):
        raw = raw[0] if raw else ""
    token = str(raw).strip().lower()
    return token in {"1", "true", "yes", "google", "signin", "login"}


def _sync_pair_code_to_query(pair_code: str):
    try:
        code = _normalize_pair_code(pair_code)
        if code:
            if _normalize_pair_code(st.query_params.get("pair", "")) != code:
                st.query_params["pair"] = code
        elif "pair" in st.query_params:
            del st.query_params["pair"]
    except Exception:
        pass


def _auto_connect_link() -> str:
    app_url = os.getenv("PUBLIC_APP_URL", "").strip().rstrip("/")
    if app_url:
        return f"{app_url}/?autopair=1"
    return "?autopair=1"


def _effective_pairing_code() -> str:
    """Return the active pairing code from session/query/auth-bound storage."""
    current = _normalize_pair_code(st.session_state.get("cloud_pairing_token", ""))
    if _is_valid_pairing_code(current):
        return current
    auth_key = _auth_identity_key()
    if auth_key:
        saved = _normalize_pair_code(get_user_pairing(auth_key))
        if _is_valid_pairing_code(saved):
            st.session_state["cloud_pairing_token"] = saved
            _sync_pair_code_to_query(saved)
            return saved
    return ""


def _render_browser_auto_pair_probe():
    """
    Browser-side auto pair:
    1) If URL has pair, cache it in localStorage.
    2) If URL has no pair, restore cached pair immediately.
    3) If still missing, try localhost /ping and inject addin_id_cloud.

    This keeps pairing nearly zero-touch after first install.
    """
    components.html(
        """
<script>
(async function() {
  const storeKey = "draftai_pair_code_v1";
  const probeKey = "draftai_pair_probe_ts_v1";
  const now = Date.now();

  const u = new URL(window.top.location.href);
  const force = ["1", "true", "yes"].includes(
    String(u.searchParams.get("autopair") || "").trim().toLowerCase()
  );
  const qp = (u.searchParams.get("pair") || "").trim();
  if (qp) {
    try { localStorage.setItem(storeKey, qp); } catch (_) {}
    if (force) {
      u.searchParams.delete("autopair");
      window.top.history.replaceState({}, "", u.toString());
    }
    return;
  }

  let cached = "";
  try { cached = (localStorage.getItem(storeKey) || "").trim(); } catch (_) {}
  if (cached && !force) {
    u.searchParams.set("pair", cached);
    window.top.location.replace(u.toString());
    return;
  }

  let lastProbe = 0;
  try { lastProbe = Number(localStorage.getItem(probeKey) || "0"); } catch (_) {}
  if (!force && now - lastProbe < 15000) return;
  try { localStorage.setItem(probeKey, String(now)); } catch (_) {}

  try {
    const resp = await fetch("http://localhost:7432/ping", { method: "GET" });
    if (!resp.ok) return;
    const data = await resp.json();
    const pair = String(data.addin_id_cloud || "").trim();
    if (!pair) return;
    try { localStorage.setItem(storeKey, pair); } catch (_) {}
    const next = new URL(window.top.location.href);
    next.searchParams.delete("autopair");
    next.searchParams.set("pair", pair);
    window.top.location.replace(next.toString());
  } catch (_) {
    if (force && cached) {
      const next = new URL(window.top.location.href);
      next.searchParams.delete("autopair");
      next.searchParams.set("pair", cached);
      window.top.location.replace(next.toString());
      return;
    }
    if (force) {
      const clean = new URL(window.top.location.href);
      clean.searchParams.delete("autopair");
      window.top.history.replaceState({}, "", clean.toString());
    }
  }
})();
</script>
""",
        height=0,
    )


def _render_pairing_controls(key_prefix: str) -> str:
    """
    Render machine pairing UX.
    - Auto uses saved/discovered pairing when available.
    - Manual pairing stays available as fallback only.
    Returns the effective pairing code.
    """
    pair_code = _effective_pairing_code()

    if pair_code:
        short = f"{pair_code[:26]}..." if len(pair_code) > 29 else pair_code
        st.markdown(
            f"""
<div style="background:rgba(34,197,94,0.07);border:1px solid rgba(34,197,94,0.22);
border-radius:9px;padding:8px 12px;margin:6px 0 10px;
font-family:DM Mono,monospace;font-size:10px;color:#86efac;letter-spacing:0.03em;">
✓ Machine paired automatically · <span style="color:#bbf7d0;">{short}</span>
</div>
""",
            unsafe_allow_html=True,
        )
        with st.expander("Switch machine (optional)", expanded=False):
            manual = st.text_input(
                "Pairing Code",
                value=pair_code,
                key=f"{key_prefix}_pairing_code",
                help="Use this only if you want to route to a different SolidWorks machine.",
                placeholder="Paste addin_id_cloud from /ping",
            )
            st.session_state["cloud_pairing_token"] = manual.strip()
            _sync_pair_code_to_query(st.session_state["cloud_pairing_token"])
            auth_key = _auth_identity_key()
            if auth_key and _is_valid_pairing_code(st.session_state["cloud_pairing_token"]):
                set_user_pairing(auth_key, st.session_state["cloud_pairing_token"])
            st.caption("Need a new machine? Open `http://localhost:7432/ping` and copy `addin_id_cloud`.")
            st.markdown(f"[⚡ Auto-connect this browser]({_auto_connect_link()})")
        return _effective_pairing_code()

    st.markdown(
        """
<div style="background:rgba(249,115,22,0.08);border:1px solid rgba(249,115,22,0.25);
border-radius:9px;padding:9px 12px;margin:6px 0 10px;
font-family:DM Mono,monospace;font-size:10px;color:#f97316;letter-spacing:0.03em;">
No paired machine found yet. Draft AI is trying to auto-detect your local add-in.
</div>
""",
        unsafe_allow_html=True,
    )
    manual = st.text_input(
        "Pairing Code",
        value="",
        key=f"{key_prefix}_pairing_code",
        help="Fallback only: paste addin_id_cloud if auto-detect is blocked by browser/network policy.",
        placeholder="Paste addin_id_cloud from /ping (fallback)",
    )
    st.session_state["cloud_pairing_token"] = manual.strip()
    _sync_pair_code_to_query(st.session_state["cloud_pairing_token"])
    auth_key = _auth_identity_key()
    if auth_key and _is_valid_pairing_code(st.session_state["cloud_pairing_token"]):
        set_user_pairing(auth_key, st.session_state["cloud_pairing_token"])
    st.caption("Fallback: open `http://localhost:7432/ping` and paste `addin_id_cloud` exactly.")
    st.markdown(f"[⚡ Auto-connect this browser]({_auto_connect_link()})")
    return _effective_pairing_code()

# ------------------------------------------------------------------
# PASSWORD PROTECTION - SELECTIVE (ONLY FOR 3D → 2D FEATURE)
# ------------------------------------------------------------------


def check_premium_access():
    """Check password ONLY for 3D → 2D feature. Returns `True` if authorized."""

    def password_entered():
        """Checks whether a password entered by the user is correct."""
        correct_password = os.getenv("PREMIUM_PASSWORD", "exclusive2025")
        if st.session_state["premium_password"] == correct_password:
            st.session_state["premium_authorized"] = True
            del st.session_state["premium_password"]  # Don't store password
        else:
            st.session_state["premium_authorized"] = False

    # If already authenticated for premium, return True
    if st.session_state.get("premium_authorized", False):
        return True

    # Show password input
    st.markdown(
        """
    <div style='text-align: center; padding: 40px 20px;'>
        <h2>🔐 Premium Feature - Beta Access</h2>
        <p style='font-size: 14px; color: #888;'>The 3D → 2D Converter is an exclusive beta feature.</p>
    </div>
    """,
        unsafe_allow_html=True,
    )

    st.text_input(
        "Enter access password:",
        type="password",
        on_change=password_entered,
        key="premium_password",
        placeholder="••••••••",
    )

    if (
        "premium_authorized" in st.session_state
        and not st.session_state["premium_authorized"]
    ):
        st.error("❌ Incorrect password.")

    return False


# ------------------------------------------------------------------
# CONSTANTS
# ------------------------------------------------------------------

CHATS_FILE = "saved_chats.json"  # Persisted chat sessions
LIBRARY_FILE = "drawing_library.json"  # Drawing library metadata
LIBRARY_DIR = "drawing_library"  # Folder for saved drawings

MAX_CHATS = 20  # Max saved chats before oldest is dropped
MAX_BATCH_FILES = 5  # Max drawings per batch analysis
MAX_FILE_SIZE_MB = 10  # Max upload size in megabytes
MAX_REQUESTS_PER_IP = 2  # Max AI requests per hour per IP
RATE_LIMIT_FILE = "rate_limits.json"
USERS_FILE = "users.json"
DEVICE_BINDINGS_FILE = "device_bindings.json"

# Ensure drawing library folder exists on startup
Path(LIBRARY_DIR).mkdir(exist_ok=True)


# ------------------------------------------------------------------
# AUTH & DEVICE BINDING
# ------------------------------------------------------------------


def _normalize_username(username: str) -> str:
    if not username:
        return ""
    return re.sub(r"[^a-z0-9_.-]", "", username.strip().lower())


def _is_valid_pairing_code(value: str) -> bool:
    if not value:
        return False
    if "_" not in value:
        return False
    return bool(re.fullmatch(r"[A-Za-z0-9_-]{8,180}", value))


def _hash_password(password: str, salt_hex: str = "") -> str:
    salt = bytes.fromhex(salt_hex) if salt_hex else os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 200_000)
    return f"{salt.hex()}${digest.hex()}"


def _verify_password(password: str, stored_hash: str) -> bool:
    try:
        salt_hex, expected_hex = stored_hash.split("$", 1)
        test_hash = _hash_password(password, salt_hex).split("$", 1)[1]
        return hmac.compare_digest(test_hash, expected_hex)
    except Exception:
        return False


def _load_json_file(path: str, default):
    if os.path.exists(path):
        try:
            with open(path) as f:
                return json.load(f)
        except Exception:
            pass
    return default


def _save_json_file(path: str, payload):
    with open(path, "w") as f:
        json.dump(payload, f, indent=2)


def load_users():
    data = _load_json_file(USERS_FILE, {"users": {}})
    if not isinstance(data, dict) or "users" not in data:
        return {"users": {}}
    return data


def save_users(data):
    _save_json_file(USERS_FILE, data)


def register_user(username: str, password: str):
    uname = _normalize_username(username)
    if len(uname) < 3:
        return False, "Username must be at least 3 characters (letters/numbers/._-)."
    if len(password) < 8:
        return False, "Password must be at least 8 characters."
    users = load_users()
    if uname in users["users"]:
        return False, "Username already exists."
    users["users"][uname] = {
        "password_hash": _hash_password(password),
        "created_at": datetime.now().isoformat(),
    }
    save_users(users)
    return True, uname


def authenticate_user(username: str, password: str):
    uname = _normalize_username(username)
    users = load_users()
    rec = users["users"].get(uname)
    if not rec:
        return False, "Account not found."
    if not _verify_password(password, rec.get("password_hash", "")):
        return False, "Incorrect password."
    return True, uname


def load_device_bindings():
    data = _load_json_file(DEVICE_BINDINGS_FILE, {"bindings": {}})
    if not isinstance(data, dict) or "bindings" not in data:
        return {"bindings": {}}
    return data


def save_device_bindings(data):
    _save_json_file(DEVICE_BINDINGS_FILE, data)


def get_user_pairing(username: str) -> str:
    if not username:
        return ""
    bindings = load_device_bindings()["bindings"]
    rec = bindings.get(username, {})
    pair = _normalize_pair_code(rec.get("pairing_code", ""))
    return pair if _is_valid_pairing_code(pair) else ""


def set_user_pairing(username: str, pairing_code: str):
    if not username:
        return
    pair = _normalize_pair_code(pairing_code)
    if not _is_valid_pairing_code(pair):
        return
    data = load_device_bindings()
    data["bindings"][username] = {
        "pairing_code": pair,
        "updated_at": datetime.now().isoformat(),
    }
    save_device_bindings(data)


def _streamlit_auth_available() -> bool:
    return all(hasattr(st, name) for name in ("login", "logout", "user"))


def _get_streamlit_user_field(field: str):
    try:
        user = st.user
    except Exception:
        return ""
    if user is None:
        return ""
    if isinstance(user, dict):
        return str(user.get(field, "") or "").strip()
    return str(getattr(user, field, "") or "").strip()


def _is_authenticated() -> bool:
    if _streamlit_auth_available():
        try:
            user = st.user
            is_logged = getattr(user, "is_logged_in", None)
            if is_logged is not None:
                return bool(is_logged)
            return bool(
                _get_streamlit_user_field("email")
                or _get_streamlit_user_field("sub")
                or _get_streamlit_user_field("name")
            )
        except Exception:
            pass
    return bool(st.session_state.get("auth_user"))


def _auth_identity_key() -> str:
    if _streamlit_auth_available() and _is_authenticated():
        email = _get_streamlit_user_field("email").lower()
        if email:
            return email
        sub = _get_streamlit_user_field("sub")
        if sub:
            return sub
        name = _normalize_username(_get_streamlit_user_field("name"))
        if name:
            return name
    return _normalize_username(st.session_state.get("auth_user", ""))


def _auth_display_name() -> str:
    if _streamlit_auth_available() and _is_authenticated():
        return (
            _get_streamlit_user_field("email")
            or _get_streamlit_user_field("name")
            or "Google User"
        )
    return st.session_state.get("auth_user", "")


def _do_sign_in():
    if _streamlit_auth_available():
        try:
            st.login()
            return
        except Exception as e:
            st.error(f"Google Sign-In is not configured yet: {e}")
            return
    st.error("Google Sign-In is not configured yet. Please set Streamlit OIDC.")


def _do_sign_out():
    st.session_state.auth_user = None
    st.session_state.cloud_pairing_token = ""
    _sync_pair_code_to_query("")
    if _streamlit_auth_available():
        try:
            st.logout()
            return
        except Exception:
            pass
    st.rerun()


def render_auth_panel():
    """Render compact account controls in sidebar."""
    st.markdown('<div class="sb-label">Account</div>', unsafe_allow_html=True)
    if _is_authenticated():
        who = _auth_display_name() or "Signed In User"
        st.markdown(
            f'<div class="sb-quota">Signed in as: <span>{who}</span></div>',
            unsafe_allow_html=True,
        )
        if st.button("Sign Out", key="auth_signout", use_container_width=True):
            _do_sign_out()
        return True

    st.markdown(
        '<div class="sb-quota">Sign in with Google to use Standards Checker and 3D → 2D.</div>',
        unsafe_allow_html=True,
    )
    if st.button("Sign In with Google", key="auth_signin_google", use_container_width=True, type="primary"):
        _do_sign_in()
    return False


def render_feature_auth_gate(feature_name: str, key_prefix: str):
    st.markdown(
        f"""
<div style="background:linear-gradient(135deg,rgba(249,115,22,0.09),rgba(249,115,22,0.03));
border:1px solid rgba(249,115,22,0.2);border-radius:12px;padding:18px 20px;margin:14px 0;">
  <div style="font-family:Syne,sans-serif;font-size:20px;font-weight:800;color:#fff;margin-bottom:6px;">
    Sign In Required
  </div>
  <div style="font-family:DM Mono,monospace;font-size:11px;color:rgba(255,255,255,0.62);line-height:1.8;">
    {feature_name} is protected. Sign in with Google to continue.
  </div>
</div>
""",
        unsafe_allow_html=True,
    )
    if st.button("Sign In with Google", key=f"{key_prefix}_signin_main", use_container_width=True, type="primary"):
        _do_sign_in()


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
    if h[:8] == b"\x89PNG\r\n\x1a\n":
        return True, "png"
    if h[:3] == b"\xff\xd8\xff":
        return True, "jpeg"
    if h[:4] == b"RIFF" and h[8:12] == b"WEBP":
        return True, "webp"
    if h[:4] == b"%PDF":
        return True, "pdf"
    return False, None


def check_file_size(f):
    """Return file size in megabytes without consuming the stream."""
    f.seek(0, 2)
    size = f.tell()
    f.seek(0)
    return size / (1024 * 1024)


def load_rate_limits():
    """Load rate limit records from disk."""
    if os.path.exists(RATE_LIMIT_FILE):
        try:
            with open(RATE_LIMIT_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def save_rate_limits(d):
    """Persist rate limit records to disk."""
    with open(RATE_LIMIT_FILE, "w") as f:
        json.dump(d, f)


def get_client_ip():
    """Get the client IP from request headers. Falls back to 'local'."""
    try:
        h = st.context.headers
        ip = h.get("x-forwarded-for", h.get("x-real-ip", "local"))
        return ip.split(",")[0].strip()
    except Exception:
        return "local"


def check_rate_limit(ip):
    """
    Check if this IP is allowed to make another request.
    Resets counter after 1 hour. Returns (allowed: bool, remaining: int).
    """
    lim = load_rate_limits()
    now = time.time()
    if ip not in lim:
        lim[ip] = {"count": 0, "window_start": now}
    e = lim[ip]
    if now - e["window_start"] > 3600:
        e["count"] = 0
        e["window_start"] = now
    if e["count"] >= MAX_REQUESTS_PER_IP:
        save_rate_limits(lim)
        mins_left = max(1, int((3600 - (now - e["window_start"])) / 60))
        return False, 0, mins_left
    return True, MAX_REQUESTS_PER_IP - e["count"], 0


def increment_rate_limit(ip):
    """Increment the request counter for this IP."""
    lim = load_rate_limits()
    now = time.time()
    if ip not in lim:
        lim[ip] = {"count": 0, "window_start": now}
    lim[ip]["count"] += 1
    save_rate_limits(lim)


# ------------------------------------------------------------------
# DRAWING LIBRARY � Save, load, search, delete drawings
# ------------------------------------------------------------------


def load_library():
    """Load drawing library metadata from disk."""
    if os.path.exists(LIBRARY_FILE):
        try:
            with open(LIBRARY_FILE) as f:
                return json.load(f)
        except Exception:
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
    lib = load_library()
    name = uploaded_file.name
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    uid = f"{ts}_{name}"
    dest = os.path.join(LIBRARY_DIR, uid)

    uploaded_file.seek(0)
    with open(dest, "wb") as f:
        f.write(uploaded_file.read())
    uploaded_file.seek(0)

    lib[uid] = {
        "name": name,
        "uid": uid,
        "path": dest,
        "tags": [t.strip() for t in tags.split(",") if t.strip()],
        "notes": notes,
        "added": datetime.now().strftime("%d %b %Y, %H:%M"),
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
        except Exception:
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
        except Exception:
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
        "chat_history": list(st.session_state.chat_history),
        "image": st.session_state.get("current_drawing_image"),
    }
    if len(st.session_state.saved_chats) > MAX_CHATS:
        del st.session_state.saved_chats[next(iter(st.session_state.saved_chats))]
    save_chats(st.session_state.saved_chats)


def render_navigation_panel(key_prefix="nav", include_saved_chats=True):
    """Render navigation and chat controls in either the sidebar or a popover."""
    st.markdown(
        '<div class="sb-logo">Draft <span>AI</span></div>', unsafe_allow_html=True
    )

    st.markdown('<div class="sb-label">Navigation</div>', unsafe_allow_html=True)
    is_signed_in = _is_authenticated()
    protected_tabs = {"standards", "cad3d"}
    nav_items = [
        ("Analyze Drawing", "analyze"),
        ("Batch Analysis", "batch"),
        ("Drawing Library", "library"),
        ("BOM Generator", "bom"),
        ("Standards Checker", "standards"),
        ("3D → 2D", "cad3d"),
    ]
    for label, tab in nav_items:
        button_label = (
            f"{label} · Sign In"
            if (tab in protected_tabs and not is_signed_in)
            else label
        )
        if st.button(button_label, key=f"{key_prefix}_{tab}", use_container_width=True):
            st.session_state.active_tab = tab
            st.rerun()

    st.markdown('<div class="sb-label">Chat History</div>', unsafe_allow_html=True)
    count = len(st.session_state.saved_chats)
    st.markdown(
        f'<div class="sb-quota"><span>{count}</span> / {MAX_CHATS} chats saved</div>',
        unsafe_allow_html=True,
    )
    _ip = get_client_ip()
    _, _rem, _ = check_rate_limit(_ip)
    st.markdown(
        f'<div class="sb-quota">Requests left: <span>{_rem}</span> / {MAX_REQUESTS_PER_IP} this hour</div>',
        unsafe_allow_html=True,
    )

    if st.button("+ New Chat", key=f"{key_prefix}_new_chat", use_container_width=True):
        st.session_state.chat_history = []
        st.session_state.messages_display = []
        st.session_state.current_drawing_name = None
        st.session_state.title_block_data = None
        st.session_state.current_drawing_image = None
        st.session_state.uploader_key += 1
        st.rerun()

    if not include_saved_chats:
        return

    st.markdown("<div style='height:4px'></div>", unsafe_allow_html=True)
    if not st.session_state.saved_chats:
        st.markdown(
            '<div style="font-size:11px;color:rgba(255,255,255,0.12);'
            "font-family:'JetBrains Mono',monospace;padding:4px 0;\">No chats yet.</div>",
            unsafe_allow_html=True,
        )
        return

    for name in reversed(list(st.session_state.saved_chats.keys())):
        cb, cd = st.columns([5, 1])
        with cb:
            if st.button(
                f"{name[:22]}",
                key=f"{key_prefix}_load_{name}",
                use_container_width=True,
            ):
                s = st.session_state.saved_chats[name]
                st.session_state.messages_display = s["messages_display"]
                st.session_state.chat_history = s["chat_history"]
                st.session_state.current_drawing_name = name
                st.session_state.current_drawing_image = s.get("image")
                st.session_state.active_tab = "analyze"
                st.rerun()
        with cd:
            if st.button("X", key=f"{key_prefix}_del_{name}", use_container_width=True):
                del st.session_state.saved_chats[name]
                save_chats(st.session_state.saved_chats)
                st.rerun()


# ------------------------------------------------------------------
# MESSAGE FORMATTER � Convert AI text to styled HTML bubbles
# ------------------------------------------------------------------


def fmt(text):
    """
    Convert plain AI response text to HTML for chat display.
    Handles: headings, ordered lists, unordered lists, bold, plain paragraphs.
    Escapes HTML special characters to prevent injection.
    """
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    lines = text.split("\n")
    html = ""
    in_list = False

    for line in lines:
        s = line.strip()
        if not s:
            continue

        # Headings (## or ###)
        if s.startswith("### ") or s.startswith("## "):
            if in_list:
                html += f"</{in_list}>"
                in_list = False
            h = re.sub(r"^#+\s*", "", s)
            h = re.sub(r"\*\*(.*?)\*\*", r"<strong>\1</strong>", h)
            html += f'<p style="margin:10px 0 4px;font-weight:600;color:#fff;font-size:14px;">{h}</p>'

        # Ordered list (1. item)
        elif re.match(r"^\d+\.", s):
            if in_list != "ol":
                if in_list:
                    html += f"</{in_list}>"
                html += '<ol style="margin:4px 0 4px 20px;padding:0;color:#fff;">'
                in_list = "ol"
            item = re.sub(r"^\d+\.\s*", "", s)
            item = re.sub(r"\*\*(.*?)\*\*", r"<strong>\1</strong>", item)
            html += f'<li style="margin-bottom:4px;line-height:1.7;font-size:14px;">{item}</li>'

        # Unordered list (- or �)
        elif s.startswith("- ") or s.startswith("� ") or re.match(r"^[⚙️]\s", s):
            if in_list != "ul":
                if in_list:
                    html += f"</{in_list}>"
                html += '<ul style="margin:4px 0 4px 20px;padding:0;color:#fff;">'
                in_list = "ul"
            item = re.sub(r"^[-⚙️]\s*", "", s)
            item = re.sub(r"\*\*(.*?)\*\*", r"<strong>\1</strong>", item)
            html += f'<li style="margin-bottom:4px;line-height:1.7;font-size:14px;">{item}</li>'

        # Plain paragraph
        else:
            if in_list:
                html += f"</{in_list}>"
                in_list = False
            lh = re.sub(r"\*\*(.*?)\*\*", r"<strong>\1</strong>", s)
            html += f'<p style="margin:4px 0;line-height:1.7;font-size:14px;color:#fff;">{lh}</p>'

    if in_list:
        html += f"</{in_list}>"
    return html


def render_dim_table(json_str):
    """
    Parse dimension detection JSON and render it as a styled HTML table.
    Falls back to plain text rendering if JSON parsing fails.
    """
    try:
        clean = json_str.strip()
        if "```" in clean:
            clean = re.sub(r"```[a-z]*", "", clean).replace("```", "").strip()
        data = json.loads(clean)
        dims = data.get("dimensions", data) if isinstance(data, dict) else data
        if not dims:
            return fmt(json_str)

        rows = ""
        for i, d in enumerate(dims):
            bg = "rgba(255,255,255,0.02)" if i % 2 == 0 else "rgba(255,255,255,0.04)"
            label = str(d.get("label", "�"))
            value = str(d.get("value", "�"))
            unit = str(d.get("unit", "�"))
            tol = str(d.get("tolerance", "�"))
            location = str(d.get("location", "�"))
            dtype = str(d.get("type", "�"))
            rows += f"""<tr style="background:{bg};">
                <td style="padding:7px 12px;color:rgba(255,255,255,0.5);font-size:12px;">{label}</td>
                <td style="padding:7px 12px;color:#f97316;font-weight:600;font-size:14px;">{value}</td>
                <td style="padding:7px 12px;color:rgba(255,255,255,0.6);font-size:12px;">{unit}</td>
                <td style="padding:7px 12px;color:rgba(255,255,255,0.5);font-size:12px;">{tol}</td>
                <td style="padding:7px 12px;color:rgba(255,255,255,0.4);font-size:11px;">{dtype}</td>
                <td style="padding:7px 12px;color:rgba(255,255,255,0.35);font-size:11px;">{location}</td>
            </tr>"""

        summary = data.get("summary", "") if isinstance(data, dict) else ""
        sum_row = (
            f'<div style="padding:8px 12px;font-size:11px;color:rgba(255,255,255,0.35);'
            f'border-top:1px solid rgba(255,255,255,0.06);">{summary}</div>'
            if summary
            else ""
        )

        return f"""<div style="background:rgba(249,115,22,0.04);border:1px solid rgba(249,115,22,0.15);border-radius:10px;overflow:hidden;">
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
        </div>"""
    except Exception:
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
            k = parts[0].strip()
            v = parts[1].strip() if len(parts) > 1 else "�"
            if v and v.lower() != "not specified":
                rows += (
                    f"<tr>"
                    f'<td style="padding:7px 14px;color:rgba(255,255,255,0.45);font-size:12px;'
                    f"font-family:DM Mono,monospace;white-space:nowrap;"
                    f'border-bottom:1px solid rgba(255,255,255,0.04);">{k}</td>'
                    f'<td style="padding:7px 14px;color:#fff;font-size:13px;'
                    f'border-bottom:1px solid rgba(255,255,255,0.04);">{v}</td>'
                    f"</tr>"
                )
    return f"""<div style="background:rgba(249,115,22,0.05);border:1px solid rgba(249,115,22,0.18);border-radius:10px;overflow:hidden;">
        <div style="padding:8px 14px;font-size:10px;font-family:DM Mono,monospace;color:#f97316;
                    letter-spacing:2px;text-transform:uppercase;border-bottom:1px solid rgba(249,115,22,0.12);">
            🏷 TITLE BLOCK
        </div>
        <table style="width:100%;border-collapse:collapse;">{rows}</table>
    </div>"""


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

st.markdown(
    """
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
[data-testid="stHeader"] {
    background: transparent !important;
    height: auto !important;
    min-height: 0 !important;
    overflow: visible !important;
    position: relative !important;
    z-index: 100001 !important;
}
[data-testid="stHeader"] > div { overflow: visible !important; }

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
[data-testid="stToolbar"] { display: none !important; }
[data-testid="stDecoration"] { display: none !important; }
#stDecoration { display: none !important; }
[class*="viewerBadge"] { display: none !important; }
.viewerBadge_container__r5tak { display: none !important; }

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
    display: none !important;
}
[data-testid="stSidebarCollapseButton"] { display: none !important; }


/* ── SIDEBAR COLLAPSE ARROW ── */
/* Hide the default text/icon and replace with clean arrow */
[data-testid="stSidebarCollapsedControl"],
[data-testid="collapsedControl"] {
    background: #0d0d0d !important;
    border: 1px solid rgba(249,115,22,0.25) !important;
    border-radius: 0 8px 8px 0 !important;
    width: 24px !important;
    height: 48px !important;
    display: flex !important;
    align-items: center !important;
    justify-content: center !important;
    position: fixed !important;
    top: 50% !important;
    left: 0 !important;
    transform: translateY(-50%) !important;
    z-index: 99999 !important;
    cursor: pointer !important;
    transition: all 0.2s !important;
    visibility: visible !important;
    opacity: 1 !important;
}
[data-testid="stSidebarCollapsedControl"]:hover,
[data-testid="collapsedControl"]:hover {
    background: rgba(249,115,22,0.12) !important;
    border-color: rgba(249,115,22,0.5) !important;
    width: 28px !important;
}
[data-testid="stSidebarCollapsedControl"] svg,
[data-testid="collapsedControl"] svg {
    color: #f97316 !important;
    fill: #f97316 !important;
    width: 14px !important;
    height: 14px !important;
}

/* The expand/collapse button inside the sidebar */
[data-testid="stSidebar"] [data-testid="stBaseButton-headerNoPadding"],
[data-testid="stSidebar"] button[aria-label="close sidebar"],
[data-testid="stSidebar"] button[aria-label="Close sidebar"],
[data-testid="stSidebar"] button[kind="header"] {
    background: transparent !important;
    border: 1px solid rgba(249,115,22,0.2) !important;
    border-radius: 0 8px 8px 0 !important;
    color: #f97316 !important;
    width: 24px !important;
    height: 48px !important;
    position: fixed !important;
    left: 238px !important;
    top: 50% !important;
    transform: translateY(-50%) !important;
    z-index: 99999 !important;
    padding: 0 !important;
    display: flex !important;
    align-items: center !important;
    justify-content: center !important;
}
[data-testid="stSidebar"] [data-testid="stBaseButton-headerNoPadding"]:hover,
[data-testid="stSidebar"] button[aria-label="close sidebar"]:hover {
    background: rgba(249,115,22,0.1) !important;
    border-color: #f97316 !important;
}
[data-testid="stSidebar"] [data-testid="stBaseButton-headerNoPadding"] svg,
[data-testid="stSidebar"] button[aria-label="close sidebar"] svg {
    color: #f97316 !important;
    fill: #f97316 !important;
}

/* ── SIDEBAR ── */
[data-testid="stSidebar"] {
    background: #0d0d0d !important;
    border-right: 1px solid rgba(255,255,255,0.05) !important;
    min-width: 300px !important;
    max-width: 300px !important;
    transform: translateX(0) !important;
    margin-left: 0 !important;
    visibility: visible !important;
}
[data-testid="stSidebar"][aria-expanded="false"] {
    min-width: 300px !important;
    max-width: 300px !important;
    transform: translateX(0) !important;
    margin-left: 0 !important;
    visibility: visible !important;
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

/* ── AUTH PAGE ── */
.auth-intro { margin: 28px 0 10px; }
.auth-kicker {
    font-family: 'DM Mono', monospace;
    font-size: 10px;
    letter-spacing: 0.14em;
    text-transform: uppercase;
    color: rgba(249,115,22,0.8);
    margin-bottom: 8px;
}
.auth-title {
    font-family: 'Syne', sans-serif;
    font-size: 34px;
    font-weight: 800;
    letter-spacing: -0.04em;
    color: #fff;
    margin-bottom: 6px;
}
.auth-sub {
    font-family: 'DM Mono', monospace;
    font-size: 11px;
    color: rgba(255,255,255,0.45);
    letter-spacing: 0.03em;
}
.auth-feature-card,
.auth-form-card {
    background: linear-gradient(145deg, rgba(255,255,255,0.025), rgba(249,115,22,0.03));
    border: 1px solid rgba(249,115,22,0.16);
    border-radius: 14px;
    padding: 18px 20px;
}
.auth-feature-card { min-height: 212px; }
.auth-feature-title {
    font-family: 'Syne', sans-serif;
    font-size: 18px;
    font-weight: 700;
    color: #fff;
    margin-bottom: 14px;
}
.auth-feature-line {
    font-family: 'DM Mono', monospace;
    font-size: 11px;
    color: rgba(255,255,255,0.65);
    margin-bottom: 8px;
    letter-spacing: 0.02em;
}
.auth-form-title {
    font-family: 'Syne', sans-serif;
    font-size: 18px;
    font-weight: 700;
    color: #fff;
    margin-bottom: 4px;
}
.auth-form-sub {
    font-family: 'DM Mono', monospace;
    font-size: 10px;
    color: rgba(255,255,255,0.45);
    letter-spacing: 0.03em;
}
.auth-form-note {
    font-family: 'DM Mono', monospace;
    font-size: 10px;
    color: rgba(255,255,255,0.4);
    letter-spacing: 0.03em;
    margin-top: 8px;
}
[data-testid="stTabs"] button[role="tab"] {
    font-family: 'DM Mono', monospace !important;
    font-size: 10px !important;
    text-transform: uppercase !important;
    letter-spacing: 0.1em !important;
    color: rgba(255,255,255,0.45) !important;
}
[data-testid="stTabs"] button[role="tab"][aria-selected="true"] {
    color: #f97316 !important;
}
[data-testid="stTabs"] [data-baseweb="tab-border"] {
    background: rgba(249,115,22,0.75) !important;
}
[data-testid="stTabs"] [data-baseweb="tab-highlight"] {
    background: rgba(249,115,22,0.75) !important;
}

/* ── SPLASH ── */
#draft-ai-splash {
    position: fixed; inset: 0; background: #0b0b0b;
    display: flex; flex-direction: column; align-items: center; justify-content: center;
    z-index: 999999; animation: splashFade 0.5s ease 3.2s forwards;
    overflow: hidden;
}
@keyframes splashFade { from { opacity: 1; pointer-events: all; } to { opacity: 0; pointer-events: none; } }


.splash-content { position: relative; z-index: 2; text-align: center; }
.splash-title { font-family: 'Syne', sans-serif; font-size: 58px; font-weight: 800; letter-spacing: -0.05em; color: #fff; margin-bottom: 6px; }
.splash-title span { color: #f97316; }
.splash-sub  { font-family: 'DM Mono', monospace; font-size: 11px; color: rgba(255,255,255,0.25); letter-spacing: 0.16em; text-transform: uppercase; animation: splashSubFade 0.6s ease 0.4s both; }
@keyframes splashSubFade { from { opacity: 0; transform: translateY(8px); } to { opacity: 1; transform: translateY(0); } }
.splash-bar-wrap { margin: 44px auto 0 auto; width: 120px; height: 1px; background: rgba(255,255,255,0.08); overflow: hidden; }
.splash-bar { height: 100%; background: #f97316; animation: splashBarFill 3.0s ease forwards; box-shadow: 0 0 14px rgba(249,115,22,0.7); }
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
""",
    unsafe_allow_html=True,
)


# ------------------------------------------------------------------
# SPLASH SCREEN � shown for 3 seconds on first load
# ------------------------------------------------------------------

if "splash_shown" not in st.session_state:
    st.session_state.splash_shown = True
    st.markdown(
        """
<div id="draft-ai-splash">
    <div class="splash-content">
        <div class="splash-title">Draft <span>AI</span></div>
        <div class="splash-sub">Get your design analysis in seconds</div>
        <div class="splash-bar-wrap"><div class="splash-bar"></div></div>
    </div>
</div>
""",
        unsafe_allow_html=True,
    )

for k, v in [
    ("chat_history", []),
    ("messages_display", []),
    ("current_drawing_name", None),
    ("title_block_data", None),
    ("active_tab", "analyze"),
    ("show_revision_panel", False),
    ("uploader_key", 0),
    ("batch_results", []),
    ("batch_running", False),
    ("standards_result", None),
]:
    if k not in st.session_state:
        st.session_state[k] = v

if "saved_chats" not in st.session_state:
    st.session_state.saved_chats = load_chats()

if "auth_user" not in st.session_state:
    st.session_state.auth_user = None

if "cloud_pairing_token" not in st.session_state:
    st.session_state.cloud_pairing_token = ""

if "auth_redirect_attempted" not in st.session_state:
    st.session_state.auth_redirect_attempted = False

pair_from_query = _read_pair_code_from_query()
if pair_from_query and pair_from_query != st.session_state.cloud_pairing_token:
    st.session_state.cloud_pairing_token = pair_from_query
_sync_pair_code_to_query(st.session_state.cloud_pairing_token)

if _read_auth_intent_from_query() and not _is_authenticated():
    if not st.session_state.auth_redirect_attempted:
        st.session_state.auth_redirect_attempted = True
        _do_sign_in()
elif st.session_state.auth_redirect_attempted:
    st.session_state.auth_redirect_attempted = False

_auth_key = _auth_identity_key()
if _auth_key:
    _saved_pair = get_user_pairing(_auth_key)
    _current_pair = _normalize_pair_code(st.session_state.cloud_pairing_token)
    if not _current_pair and _saved_pair:
        st.session_state.cloud_pairing_token = _saved_pair
        _sync_pair_code_to_query(_saved_pair)
    elif _is_valid_pairing_code(_current_pair) and _current_pair != _saved_pair:
        set_user_pairing(_auth_key, _current_pair)


# ------------------------------------------------------------------
# SIDEBAR
# ------------------------------------------------------------------

with st.sidebar:
    render_navigation_panel("sidebar")
    render_auth_panel()


# ------------------------------------------------------------------
# TOP NAV � App title with spinning gear + white/orange color split
# ------------------------------------------------------------------

# ── TOP BAR ──
_fname = st.session_state.get("current_drawing_name")
_file_pill = (
    f"""<div class="top-bar-file"><span class="dot">●</span>{_fname}</div>"""
    if _fname
    else ""
)
st.markdown(
    f"""
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
""",
    unsafe_allow_html=True,
)


# ------------------------------------------------------------------
# TAB: BATCH ANALYSIS
# ------------------------------------------------------------------

if st.session_state.active_tab == "batch":

    st.markdown(
        '<div class="section-label" style="margin-top:12px;">Batch Analysis</div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        """
<div style="background:rgba(249,115,22,0.05);border:1px solid rgba(249,115,22,0.15);border-radius:8px;padding:12px 16px;margin-bottom:14px;">
    <div style="font-size:13px;color:rgba(255,255,255,0.85);font-family:Syne,sans-serif;">
        Upload up to <b style="color:#f97316;">5 drawings</b> at once. Draft AI will analyze each one and generate a
        comparison report — exportable as <b style="color:#f97316;">Excel</b> or <b style="color:#f97316;">PDF</b>.
    </div>
</div>
""",
        unsafe_allow_html=True,
    )

    batch_files = st.file_uploader(
        "Upload drawings for batch analysis",
        type=["png", "jpg", "jpeg", "webp", "pdf"],
        accept_multiple_files=True,
        label_visibility="collapsed",
        key="batch_uploader",
    )

    # Analysis options
    st.markdown(
        '<div class="section-label" style="margin-top:10px;">Analysis Options</div>',
        unsafe_allow_html=True,
    )
    opt1, opt2, opt3 = st.columns(3)
    with opt1:
        opt_status = st.checkbox("Production Status", value=True)
    with opt2:
        opt_score = st.checkbox("Manufacturability Score", value=True)
    with opt3:
        opt_cost = st.checkbox("Cost Estimate", value=True)

    # File list preview
    if batch_files:
        st.markdown(
            f'<div class="section-label" style="margin-top:10px;">{len(batch_files)} drawings selected</div>',
            unsafe_allow_html=True,
        )
        if len(batch_files) > MAX_BATCH_FILES:
            st.warning(
                f"Maximum {MAX_BATCH_FILES} drawings per batch. Only the first {MAX_BATCH_FILES} will be analyzed."
            )
            batch_files = batch_files[:MAX_BATCH_FILES]

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
            run_batch = st.button(
                "Run Batch Analysis", type="primary", use_container_width=True
            )
        with clear_col:
            if st.button("Clear", use_container_width=True):
                st.session_state.batch_results = []
                st.rerun()

        if run_batch:
            st.session_state.batch_results = []
            progress_bar = st.progress(0, text="Starting batch analysis...")
            status_text = st.empty()
            results_so_far = []

            for idx, f in enumerate(batch_files):
                pct = int((idx / len(batch_files)) * 100)
                progress_bar.progress(
                    pct, text=f"Analyzing {idx+1}/{len(batch_files)}: {f.name[:30]}..."
                )
                status_text.markdown(
                    f"<div style=\"font-size:11px;color:rgba(255,255,255,0.4);font-family:'Syne',Helvetica,Arial,sans-serif;\">"
                    f"Processing: {f.name}</div>",
                    unsafe_allow_html=True,
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
        total = len(results)
        ready = sum(1 for r in results if "Ready" in r.get("status", ""))
        needs = sum(1 for r in results if "Revision" in r.get("status", ""))
        rework = sum(
            1
            for r in results
            if "Major" in r.get("status", "") or "Failed" in r.get("status", "")
        )
        scores = [
            r.get("manufacturability_score", 0)
            for r in results
            if isinstance(r.get("manufacturability_score"), (int, float))
        ]
        avg_sc = round(sum(scores) / len(scores)) if scores else "—"

        # Stats row
        st.markdown("<div style='height:6px'></div>", unsafe_allow_html=True)
        m1, m2, m3, m4, m5 = st.columns(5)
        for col, label, val, color in [
            (m1, "Total", total, "#ffffff"),
            (m2, "Production Ready", ready, "#16a34a"),
            (m3, "Needs Revision", needs, "#d97706"),
            (m4, "Major Rework", rework, "#dc2626"),
            (m5, "Avg Mfg. Score", f"{avg_sc}/100", "#f97316"),
        ]:
            with col:
                st.markdown(
                    f"""
<div style="background:rgba(255,255,255,0.03);border:1px solid rgba(255,255,255,0.07);
border-radius:8px;padding:12px 14px;text-align:center;">
    <div style="font-size:22px;font-weight:700;color:{color};font-family:Syne,sans-serif;">{val}</div>
    <div style="font-size:10px;color:rgba(255,255,255,0.3);margin-top:2px;font-family:Syne,sans-serif;text-transform:uppercase;letter-spacing:0.08em;">{label}</div>
</div>""",
                    unsafe_allow_html=True,
                )

        st.markdown("<div style='height:14px'></div>", unsafe_allow_html=True)

        # Drawing cards
        st.markdown('<div class="section-label">Results</div>', unsafe_allow_html=True)
        for i, r in enumerate(results, 1):
            status = r.get("status", "—")
            score = r.get("manufacturability_score", "—")
            if "Ready" in status:
                status_color = "#16a34a"
                status_bg = "rgba(22,163,74,0.08)"
                border_c = "rgba(22,163,74,0.2)"
            elif "Revision" in status:
                status_color = "#d97706"
                status_bg = "rgba(217,119,6,0.08)"
                border_c = "rgba(217,119,6,0.2)"
            else:
                status_color = "#dc2626"
                status_bg = "rgba(220,38,38,0.08)"
                border_c = "rgba(220,38,38,0.2)"

            issues_html = ""
            for iss in r.get("critical_issues", []):
                issues_html += f'<div style="font-size:11px;color:#dc2626;margin-top:3px;">Critical: {iss}</div>'
            for w in r.get("warnings", []):
                issues_html += f'<div style="font-size:11px;color:#d97706;margin-top:3px;">Warning: {w}</div>'

            st.markdown(
                f"""
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
</div>""",
                unsafe_allow_html=True,
            )

        # Export buttons
        st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)
        st.markdown(
            '<div class="section-label">Export Report</div>', unsafe_allow_html=True
        )
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
    st.markdown(
        '<div class="footer-txt" style="margin-top:20px;">Draft <span>AI</span> &nbsp;|&nbsp; Made with ♥ by Rishi</div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        '<div class="sticky-wrap"><div class="sticky-inner">', unsafe_allow_html=True
    )
    batch_q = st.text_area(
        "batchq",
        placeholder="Ask anything about the drawing...",
        label_visibility="collapsed",
        height=52,
        key="batch_chat_input",
    )
    bq_col1, bq_col2 = st.columns([5, 1], gap="small")
    with bq_col1:
        bq_btn = st.button(
            "Analyze", type="primary", use_container_width=True, key="batch_ask_btn"
        )
    with bq_col2:
        if st.button(
            "🗑️ Clear",
            use_container_width=True,
            key="batch_clear_btn",
            help="Clear chat",
        ):
            st.session_state.chat_history = []
            st.session_state.messages_display = []
            st.rerun()
    st.markdown("</div></div>", unsafe_allow_html=True)
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

    st.markdown(
        '<div class="section-label" style="margin-top:12px;">BOM Generator</div>',
        unsafe_allow_html=True,
    )

    # Hero banner
    st.markdown(
        """
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
""",
        unsafe_allow_html=True,
    )

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
                        bom_file = io.BytesIO(result)
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
                st.image(
                    bom_file.read() if img_bytes is None else img_bytes,
                    use_container_width=True,
                )
                bom_file.seek(0)
            with info_col:
                st.markdown(
                    f"""
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
""",
                    unsafe_allow_html=True,
                )
                run_bom = st.button(
                    "Generate BOM", type="primary", use_container_width=True
                )
                st.markdown(
                    """
<div style="font-size:11px;color:rgba(255,255,255,0.25);margin-top:8px;line-height:1.5;">
    AI will scan all part balloons, title block fields, and annotations to build the BOM.
</div>
""",
                    unsafe_allow_html=True,
                )

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
        bom = st.session_state["bom_result"]
        items = bom.get("items", [])

        st.markdown("<div style='height:6px'></div>", unsafe_allow_html=True)

        # ── Stat cards row ────────────────────────────────────────────
        total_qty = sum(int(it.get("quantity", 1)) for it in items)
        materials = len(
            set(
                it.get("material", "—")
                for it in items
                if it.get("material") and it.get("material") != "—"
            )
        )

        s1, s2, s3, s4 = st.columns(4)
        for col, label, value, sub in [
            (s1, "ASSEMBLY", bom.get("assembly_name", "—"), None),
            (s2, "DRAWING NO.", bom.get("drawing_number", "—"), None),
            (s3, "UNIQUE PARTS", str(len(items)), f"{total_qty} total qty"),
            (s4, "REVISION", bom.get("revision", "—"), f"{materials} materials"),
        ]:
            with col:
                st.markdown(
                    f"""
<div style="background:rgba(249,115,22,0.06);border:1px solid rgba(249,115,22,0.18);
            border-radius:10px;padding:14px 16px;text-align:center;">
    <div style="font-size:9px;color:rgba(255,255,255,0.35);font-family:DM Mono,monospace;
                letter-spacing:.12em;text-transform:uppercase;margin-bottom:6px;">{label}</div>
    <div style="font-size:16px;font-weight:700;color:#f97316;font-family:Syne,sans-serif;
                white-space:nowrap;overflow:hidden;text-overflow:ellipsis;" title="{value}">{value}</div>
    {f'<div style="font-size:10px;color:rgba(255,255,255,0.3);margin-top:4px;">{sub}</div>' if sub else ''}
</div>""",
                    unsafe_allow_html=True,
                )

        st.markdown("<div style='height:14px'></div>", unsafe_allow_html=True)

        # ── BOM table ─────────────────────────────────────────────────
        rows_html = ""
        for i, item in enumerate(items):
            bg = "rgba(255,255,255,0.015)" if i % 2 == 0 else "rgba(255,255,255,0.035)"
            qty_val = item.get("quantity", 1)
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

        st.markdown(
            f"""
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
</div>""",
            unsafe_allow_html=True,
        )

        st.markdown("<div style='height:16px'></div>", unsafe_allow_html=True)

        # ── Export + actions row ──────────────────────────────────────
        excel_buf = generate_bom_excel(bom)
        pdf_buf = generate_bom_pdf(bom)
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
            if st.button(
                "🗑 Clear", use_container_width=True, help="Remove current BOM result"
            ):
                del st.session_state["bom_result"]
                st.rerun()

    # ── Quick question bar for BOM tab ──
    st.markdown(
        '<div class="footer-txt" style="margin-top:20px;">Draft <span>AI</span> &nbsp;|&nbsp; Made with ♥ by Rishi</div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        '<div class="sticky-wrap"><div class="sticky-inner">', unsafe_allow_html=True
    )
    bom_q = st.text_area(
        "bomq",
        placeholder="Ask anything about the drawing...",
        label_visibility="collapsed",
        height=52,
        key="bom_chat_input",
    )
    bomq_col1, bomq_col2 = st.columns([5, 1], gap="small")
    with bomq_col1:
        bomq_btn = st.button(
            "Analyze", type="primary", use_container_width=True, key="bom_ask_btn"
        )
    with bomq_col2:
        if st.button(
            "🗑️ Clear", use_container_width=True, key="bom_clear_btn", help="Clear chat"
        ):
            st.session_state.chat_history = []
            st.session_state.messages_display = []
            st.rerun()
    st.markdown("</div></div>", unsafe_allow_html=True)
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
    st.markdown(
        '<div class="section-label" style="margin-top:12px;">Add to Library</div>',
        unsafe_allow_html=True,
    )
    add_file = st.file_uploader(
        "Add drawing",
        type=["png", "jpg", "jpeg", "webp", "pdf"],
        label_visibility="collapsed",
        key="lib_upload",
    )

    if add_file:
        size_mb = check_file_size(add_file)
        is_valid, _ = validate_file(add_file)

        if size_mb > MAX_FILE_SIZE_MB:
            st.error(
                f"File too large ({size_mb:.1f} MB). Max is {MAX_FILE_SIZE_MB} MB."
            )
        elif not is_valid:
            st.error("Invalid file type. Only real PNG/JPEG/WEBP images accepted.")
        else:
            col_tag, col_note = st.columns([1, 1])
            with col_tag:
                tags = st.text_input(
                    "Tags (comma separated)",
                    placeholder="shaft, tolerance, Rev-A",
                    key="lib_tags",
                )
            with col_note:
                notes = st.text_input(
                    "Notes (optional)",
                    placeholder="Customer drawing, pending review",
                    key="lib_notes",
                )
            if st.button("Save to Library", type="primary", use_container_width=True):
                uid = add_to_library(add_file, tags, notes)
                st.success(f"Saved: {add_file.name}")
                st.rerun()

    st.markdown(
        "<div style='height:1px;background:rgba(255,255,255,0.05);margin:14px 0'></div>",
        unsafe_allow_html=True,
    )

    # -- Browse and search library --
    st.markdown('<div class="section-label">Library</div>', unsafe_allow_html=True)
    search = st.text_input(
        "Search",
        placeholder="Search by name or tag...",
        label_visibility="collapsed",
        key="lib_search",
    )

    lib = load_library()  # Reload after possible new addition
    if not lib:
        st.markdown(
            '<div class="chat-empty">'
            '<div style="font-size:30px;opacity:0.15;margin-bottom:8px;">⚙️</div>'
            "<div>No drawings saved yet</div></div>",
            unsafe_allow_html=True,
        )
    else:
        # Filter by name or tag
        filtered = {
            k: v
            for k, v in lib.items()
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
                tags_html = "".join(
                    f'<span class="lib-tag">{t}</span>' for t in meta.get("tags", [])
                )
                notes_txt = (
                    f'<div style="font-size:11px;color:rgba(255,255,255,0.25);margin-top:4px;">{meta["notes"]}</div>'
                    if meta.get("notes")
                    else ""
                )
                st.markdown(
                    f"""<div class="lib-card">
                    <div class="lib-name">📄 {meta["name"]}</div>
                    <div class="lib-meta">{meta["added"]}  �  {meta["size_mb"]} MB</div>
                    {tags_html}{notes_txt}
                </div>""",
                    unsafe_allow_html=True,
                )

                c1, c2, c3 = st.columns([2, 2, 1])

                with c1:
                    # Open drawing in Analyze tab
                    if st.button(
                        "Open & Analyze", key=f"open_{uid}", use_container_width=True
                    ):
                        try:
                            with open(meta["path"], "rb") as f:
                                img_bytes = f.read()
                            import io

                            fake_file = io.BytesIO(img_bytes)
                            fake_file.name = meta["name"]
                            st.session_state["_lib_open_file"] = img_bytes
                            st.session_state["_lib_open_name"] = meta["name"]
                            st.session_state.current_drawing_name = meta["name"]
                            st.session_state.chat_history = []
                            st.session_state.messages_display = []
                            st.session_state.active_tab = "analyze"
                            st.info(
                                "Drawing loaded � switch to Analyze tab and upload the file to start chatting."
                            )
                            st.rerun()
                        except Exception as e:
                            st.error(f"Could not open file: {e}")

                with c2:
                    # Download original file
                    try:
                        with open(meta["path"], "rb") as f:
                            file_bytes = f.read()
                        st.download_button(
                            "Download",
                            data=file_bytes,
                            file_name=meta["name"],
                            use_container_width=True,
                            key=f"dl_{uid}",
                        )
                    except Exception:
                        st.button(
                            "Download",
                            disabled=True,
                            use_container_width=True,
                            key=f"dl_{uid}",
                        )

                with c3:
                    # Delete from library
                    if st.button(
                        "Clear",
                        key=f"libdel_{uid}",
                        use_container_width=True,
                        help="Remove from library",
                    ):
                        delete_from_library(uid)
                        st.rerun()

                st.markdown("<div style='height:4px'></div>", unsafe_allow_html=True)


# ------------------------------------------------------------------
# TAB: STANDARDS CHECKER
# ------------------------------------------------------------------

elif st.session_state.active_tab == "standards":
    if not _is_authenticated():
        render_feature_auth_gate("Standards Checker", "standards")
        st.markdown(
            '<div style="font-family:DM Mono,monospace;font-size:10px;color:rgba(255,255,255,0.42);'
            'margin-top:8px;">Sign in is required only for <span style="color:#f97316;">Standards Checker</span> and '
            '<span style="color:#f97316;">3D → 2D</span>. Other tools remain open.</div>',
            unsafe_allow_html=True,
        )
        st.stop()

    st.markdown(
        '<div class="section-label" style="margin-top:12px;">Standards Checker</div>',
        unsafe_allow_html=True,
    )

    st.markdown(
        """
<div style="background:linear-gradient(135deg,rgba(249,115,22,0.10) 0%,rgba(249,115,22,0.03) 100%);
            border:1px solid rgba(249,115,22,0.22);border-radius:12px;padding:16px 20px;margin-bottom:14px;">
    <div style="font-size:14px;font-weight:700;color:#fff;font-family:Syne,sans-serif;margin-bottom:6px;">
        Drawing Standards &amp; 3D Model Analysis
    </div>
    <div style="font-size:12px;color:rgba(255,255,255,0.55);line-height:1.8;">
        Upload any engineering file — Draft AI checks it against
        <b style="color:#f97316;">ASME Y14.5</b>,
        <b style="color:#f97316;">ISO GPS</b>, and
        <b style="color:#f97316;">BS 8888</b> and returns a scored Pass / Fail report across 8 categories.<br>
        For <b style="color:#f97316;">STEP / STP / IGES / STL</b> files, the Draft AI SolidWorks add-in opens the model,
        exports 2D views, extracts dimensions, and runs the full standards check automatically.
    </div>
    <div style="margin-top:10px;display:flex;gap:8px;flex-wrap:wrap;">
        <span style="font-family:DM Mono,monospace;font-size:10px;background:rgba(249,115,22,0.12);color:#f97316;padding:3px 8px;border-radius:4px;border:1px solid rgba(249,115,22,0.2);">PNG · JPG · WEBP</span>
        <span style="font-family:DM Mono,monospace;font-size:10px;background:rgba(249,115,22,0.12);color:#f97316;padding:3px 8px;border-radius:4px;border:1px solid rgba(249,115,22,0.2);">STEP · STP</span>
        <span style="font-family:DM Mono,monospace;font-size:10px;background:rgba(249,115,22,0.12);color:#f97316;padding:3px 8px;border-radius:4px;border:1px solid rgba(249,115,22,0.2);">IGES · IGS</span>
        <span style="font-family:DM Mono,monospace;font-size:10px;background:rgba(249,115,22,0.12);color:#f97316;padding:3px 8px;border-radius:4px;border:1px solid rgba(249,115,22,0.2);">STL</span>
    </div>
</div>
""",
        unsafe_allow_html=True,
    )

    # ── Single unified uploader ──────────────────────────────────────────────
    unified_file = st.file_uploader(
        "Upload file for analysis",
        type=["png", "jpg", "jpeg", "webp", "step", "stp", "iges", "igs", "stl"],
        label_visibility="collapsed",
        key="unified_std_uploader",
    )
    st.markdown(
        '<div style="text-align:center;font-family:DM Mono,monospace;font-size:10px;color:rgba(255,255,255,0.2);padding:4px 0 10px;">PNG · JPG · WEBP · STEP · STP · IGES · IGS · STL</div>',
        unsafe_allow_html=True,
    )

    if unified_file:
        ext = unified_file.name.lower().rsplit(".", 1)[-1]
        is_3d = ext in ("step", "stp", "iges", "igs", "stl")
        is_img = ext in ("png", "jpg", "jpeg", "webp")

        # ── 3D file path ─────────────────────────────────────────────────────
        if is_3d:
            from cad_converter import is_addin_running, prepare_and_export

            addin_local = is_addin_running()
            addin_ok    = addin_local
            st.session_state.addin_ok_cache = addin_ok

            if addin_local:
                st.markdown(
                    '<div style="background:rgba(34,197,94,0.08);border:1px solid rgba(34,197,94,0.25);border-radius:8px;padding:8px 14px;font-family:DM Mono,monospace;font-size:11px;color:#22c55e;margin-bottom:10px;">⚡ SolidWorks Add-in connected on this PC · Ready</div>',
                    unsafe_allow_html=True,
                )
            else:
                st.markdown(
                    '<div style="background:rgba(249,115,22,0.08);border:1px solid rgba(249,115,22,0.25);border-radius:8px;padding:8px 14px;font-family:DM Mono,monospace;font-size:11px;color:#f97316;margin-bottom:10px;">⚠️ SolidWorks Add-in not detected on this PC — open SolidWorks with Draft AI add-in loaded, then click Analyze</div>',
                    unsafe_allow_html=True,
                )

            fc1, fc2 = st.columns([3, 1])
            with fc1:
                st.markdown(
                    f"""
<div style="background:rgba(255,255,255,0.03);border:1px solid rgba(255,255,255,0.07);border-radius:10px;padding:12px 16px;font-family:DM Mono,monospace;font-size:11px;">
    <span style="color:#f97316;">⚙️</span>&nbsp; <span style="color:#fff;">{unified_file.name}</span>
    <span style="color:rgba(255,255,255,0.3);margin-left:12px;">{check_file_size(unified_file):.1f} MB</span>
</div>""",
                    unsafe_allow_html=True,
                )
            with fc2:
                run_3d = st.button(
                    "⚡ Analyze via SW",
                    type="primary",
                    use_container_width=True,
                    key="run_3d_unified",
                    disabled=not addin_ok,
                )

            if run_3d:
                can_try = addin_ok
                if not can_try:
                    st.error(
                        "⚠️ SolidWorks Add-in must be running on this PC. "
                        "Open SolidWorks with Draft AI add-in loaded, then click Analyze again."
                    )
                else:
                    with st.spinner("SolidWorks is opening and analyzing your file..."):
                        try:
                            unified_file.seek(0)
                            sw_result = prepare_and_export(
                                unified_file.read(),
                                unified_file.name,
                            )
                            st.session_state["step_analysis_result"] = sw_result
                            st.session_state["standards_result"] = None  # force re-run
                            st.session_state["standards_ran_for"] = None # reset tracker
                            st.rerun()
                        except Exception as e:
                            st.error(f"Analysis failed: {e}")

        # ── Image file path ───────────────────────────────────────────────────
        elif is_img:
            sz = check_file_size(unified_file)
            valid, _ = validate_file(unified_file)
            if sz > MAX_FILE_SIZE_MB:
                st.error(f"File too large: {sz:.1f} MB. Max {MAX_FILE_SIZE_MB} MB.")
            elif not valid:
                st.error("Invalid image file.")
            else:
                prev_col, btn_col = st.columns([3, 1])
                with prev_col:
                    unified_file.seek(0)
                    st.image(unified_file.read(), use_container_width=True)
                    unified_file.seek(0)
                with btn_col:
                    st.markdown(
                        "<div style='height:8px'></div>", unsafe_allow_html=True
                    )
                    run_std = st.button(
                        "▶ Run Standards Check",
                        type="primary",
                        use_container_width=True,
                        key="run_std_unified",
                    )
                    st.markdown(
                        '<div style="font-size:10px;color:rgba(255,255,255,0.2);margin-top:8px;line-height:1.5;font-family:DM Mono,monospace;">Checks 8 categories against ASME / ISO / BS 8888</div>',
                        unsafe_allow_html=True,
                    )

                if run_std:
                    ip = get_client_ip()
                    allowed, remaining, mins_left = check_rate_limit(ip)
                    if not allowed:
                        st.markdown(
                            f"""
<div style="background:rgba(249,115,22,0.07);border:1px solid rgba(249,115,22,0.25);border-radius:12px;padding:16px 20px;margin:8px 0;">
    <div style="font-size:15px;margin-bottom:6px;">🪫 Whoa, easy there!</div>
    <div style="font-family:'Syne',sans-serif;font-size:13px;color:rgba(255,255,255,0.85);line-height:1.7;margin-bottom:10px;">
        You've hit the <b style="color:#f97316;">2 requests/hour</b> free limit.<br>
        Honestly? We're running on <b>dreams and ramen</b> over here. 🍜<br>
        Every API call costs us money and our wallets are crying. 😭<br><br>
        If you're enjoying Draft AI, consider buying us a coffee — or just a cup of water at this point.<br>
        We'll use it to raise your limit, we promise. XOXO 🧡
    </div>
    <div style="font-family:'DM Mono',monospace;font-size:10px;color:rgba(255,255,255,0.3);letter-spacing:0.05em;">
        ⏱ Try again in ~{mins_left} min &nbsp;·&nbsp; Or donate and get more — coming soon
    </div>
</div>""",
                            unsafe_allow_html=True,
                        )
                    else:
                        with st.spinner("Checking drawing against standards..."):
                            unified_file.seek(0)
                            try:
                                result = check_drawing_standards(unified_file)
                                st.session_state.standards_result = result
                                st.session_state["step_analysis_result"] = None
                                increment_rate_limit(ip)
                                st.rerun()
                            except Exception as e:
                                err_msg = str(e)
                                if "empty response from AI backend" in err_msg or "non-JSON output" in err_msg:
                                    st.error(
                                        "Standards check failed: AI backend returned invalid data. "
                                        "Verify OPENAI_API_KEY is valid (single line, no line breaks) "
                                        "and PROXY_URL points to a working OpenAI-compatible /v1 endpoint."
                                    )
                                else:
                                    st.error(f"Standards check failed: {err_msg}")

    # ── SolidWorks 3D result ─────────────────────────────────────────────────
    if st.session_state.get("step_analysis_result"):
        sr = st.session_state["step_analysis_result"]
        st.markdown(
            '<div class="section-label" style="margin-top:14px;">SolidWorks Analysis Result</div>',
            unsafe_allow_html=True,
        )
        if sr.get("ready"):
            dims = sr.get("dimensions", {})
            st.markdown(
                f"""
<div style="background:rgba(34,197,94,0.06);border:1px solid rgba(34,197,94,0.2);border-radius:12px;padding:16px 20px;margin-bottom:12px;">
    <div style="font-size:13px;font-weight:700;color:#22c55e;margin-bottom:10px;">✅ File analyzed successfully via SolidWorks</div>
    <div style="display:flex;gap:24px;flex-wrap:wrap;">
        <div style="font-family:DM Mono,monospace;font-size:11px;color:rgba(255,255,255,0.6);">X <span style="color:#fff;margin-left:6px;">{dims.get('length','—')} mm</span></div>
        <div style="font-family:DM Mono,monospace;font-size:11px;color:rgba(255,255,255,0.6);">Y <span style="color:#fff;margin-left:6px;">{dims.get('width','—')} mm</span></div>
        <div style="font-family:DM Mono,monospace;font-size:11px;color:rgba(255,255,255,0.6);">Z <span style="color:#fff;margin-left:6px;">{dims.get('height','—')} mm</span></div>
    </div>
</div>""",
                unsafe_allow_html=True,
            )

            views = sr.get("views", {})
            view_order = ["front", "top", "side", "isometric"]
            available = [
                (v, views[v]) for v in view_order if views.get(v, {}).get("png")
            ]
            if available:
                st.markdown(
                    '<div class="section-label">Exported Views</div>',
                    unsafe_allow_html=True,
                )
                vcols = st.columns(len(available))
                for col, (vkey, vdata) in zip(vcols, available):
                    with col:
                        st.image(
                            vdata["png"],
                            caption=vdata.get("label", vkey.capitalize()),
                            use_container_width=True,
                        )

            # ── Run standards check on ALL available views ────────────────────
            already_ran = st.session_state.get("standards_ran_for") == sr.get("filename")
            if views and not already_ran:
                ip = get_client_ip()
                allowed, _, _ = check_rate_limit(ip)
                if allowed:
                    with st.spinner("Running standards check across all views..."):
                        try:
                            from utils import check_drawing_standards_multiview, gemini_model
                            import io as _io

                            views_bytes = {}
                            for vkey, vdata in views.items():
                                if vdata.get("png"):
                                    views_bytes[vkey] = vdata["png"]

                            result = check_drawing_standards_multiview(views_bytes)
                            st.session_state.standards_result = result
                            st.session_state["standards_ran_for"] = sr.get("filename")
                            increment_rate_limit(ip)
                            st.rerun()
                        except Exception as e:
                            err_msg = str(e)
                            if "empty response from AI backend" in err_msg or "non-JSON output" in err_msg:
                                st.error(
                                    "Standards check failed: AI backend returned invalid data. "
                                    "Verify OPENAI_API_KEY is valid (single line, no line breaks) "
                                    "and PROXY_URL points to a working OpenAI-compatible /v1 endpoint."
                                )
                            else:
                                st.error(f"Standards check failed: {err_msg}")

            if sr.get("pdf"):
                st.download_button(
                    "📄 Download Engineering PDF",
                    data=sr["pdf"],
                    file_name=f"{sr.get('filename','drawing')}_2D.pdf",
                    mime="application/pdf",
                    use_container_width=True,
                )
        else:
            st.error(f"Analysis error: {sr.get('reason', 'Unknown error')}")

        if st.button("🗑 Clear Result", key="step_clear"):
            st.session_state["step_analysis_result"] = None
            st.session_state.standards_result = None
            st.rerun()

    # ── Standards check result ───────────────────────────────────────────────
    if st.session_state.get("standards_result"):
        r = st.session_state.standards_result
        score = r.get("overall_score", 0)
        verdict = r.get("verdict", "—")
        std_det = r.get("standard_detected", "Unknown")

        if verdict == "PASS":
            v_color = "#16a34a"
            v_bg = "rgba(22,163,74,0.08)"
            v_border = "rgba(22,163,74,0.25)"
        elif verdict == "CONDITIONAL PASS":
            v_color = "#d97706"
            v_bg = "rgba(217,119,6,0.08)"
            v_border = "rgba(217,119,6,0.25)"
        else:
            v_color = "#dc2626"
            v_bg = "rgba(220,38,38,0.08)"
            v_border = "rgba(220,38,38,0.25)"

        st.markdown(
            f"""
<div style="display:flex;gap:16px;margin:16px 0;align-items:stretch;flex-wrap:wrap;">
  <div style="flex:0 0 160px;background:{v_bg};border:1px solid {v_border};border-radius:12px;
              padding:20px;text-align:center;display:flex;flex-direction:column;align-items:center;justify-content:center;">
    <div style="font-size:48px;font-weight:800;color:{v_color};font-family:Syne,sans-serif;line-height:1;">{score}</div>
    <div style="font-size:10px;color:rgba(255,255,255,0.3);font-family:DM Mono,monospace;letter-spacing:.1em;margin:4px 0 10px;">/ 100</div>
    <div style="font-size:11px;font-weight:700;color:{v_color};background:{v_bg};
                border:1px solid {v_border};border-radius:6px;padding:4px 10px;letter-spacing:.04em;">{verdict}</div>
    <div style="font-size:9px;color:rgba(255,255,255,0.25);font-family:DM Mono,monospace;margin-top:8px;">{std_det}</div>
  </div>
  <div style="flex:1;background:rgba(255,255,255,0.02);border:1px solid rgba(255,255,255,0.07);
              border-radius:12px;padding:16px 18px;">
    <div style="font-size:9px;color:rgba(255,255,255,0.25);font-family:DM Mono,monospace;
                letter-spacing:.12em;text-transform:uppercase;margin-bottom:10px;">Executive Summary</div>
    <div style="font-size:13px;color:rgba(255,255,255,0.8);line-height:1.7;font-family:Syne,sans-serif;">
        {r.get("summary","—")}
    </div>
  </div>
</div>
""",
            unsafe_allow_html=True,
        )

        checks = r.get("checks", [])
        if checks:
            st.markdown(
                '<div class="section-label" style="margin-top:4px;">Category Breakdown</div>',
                unsafe_allow_html=True,
            )
            cols = st.columns(2)
            for i, chk in enumerate(checks):
                cat_status = chk.get("status", "—")
                cat_score = chk.get("score", 0)
                if cat_status == "PASS":
                    cs_color = "#16a34a"
                    cs_bg = "rgba(22,163,74,0.06)"
                    cs_border = "rgba(22,163,74,0.18)"
                elif cat_status == "WARNING":
                    cs_color = "#d97706"
                    cs_bg = "rgba(217,119,6,0.06)"
                    cs_border = "rgba(217,119,6,0.18)"
                else:
                    cs_color = "#dc2626"
                    cs_bg = "rgba(220,38,38,0.06)"
                    cs_border = "rgba(220,38,38,0.18)"
                findings_html = "".join(
                    f'<div style="font-size:11px;color:rgba(255,255,255,0.45);margin-top:2px;">✓ {f}</div>'
                    for f in chk.get("findings", [])[:3]
                )
                violations_html = "".join(
                    f'<div style="font-size:11px;color:#dc2626;margin-top:2px;">✗ {v}</div>'
                    for v in chk.get("violations", [])[:3]
                )
                with cols[i % 2]:
                    st.markdown(
                        f"""
<div style="background:{cs_bg};border:1px solid {cs_border};border-radius:10px;padding:12px 14px;margin-bottom:10px;">
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;">
        <div style="font-size:12px;font-weight:600;color:#fff;font-family:Syne,sans-serif;">{chk.get("category","—")}</div>
        <div style="display:flex;gap:8px;align-items:center;">
            <span style="font-size:11px;color:#f97316;font-family:DM Mono,monospace;">{cat_score}/100</span>
            <span style="font-size:9px;background:{cs_bg};color:{cs_color};border:1px solid {cs_border};
                         padding:2px 7px;border-radius:4px;font-family:DM Mono,monospace;letter-spacing:.04em;">{cat_status}</span>
        </div>
    </div>
    {findings_html}{violations_html}
</div>""",
                        unsafe_allow_html=True,
                    )

        crits = r.get("critical_violations", [])
        warns = r.get("warnings", [])
        recs = r.get("recommendations", [])

        if crits:
            st.markdown(
                '<div class="section-label" style="margin-top:4px;">Critical Violations</div>',
                unsafe_allow_html=True,
            )
            for c in crits:
                st.markdown(
                    f'<div style="background:rgba(220,38,38,0.06);border:1px solid rgba(220,38,38,0.2);border-radius:8px;padding:10px 14px;margin-bottom:6px;font-size:12px;color:#fca5a5;font-family:Syne,sans-serif;">✗ {c}</div>',
                    unsafe_allow_html=True,
                )
        if warns:
            st.markdown(
                '<div class="section-label" style="margin-top:8px;">Warnings</div>',
                unsafe_allow_html=True,
            )
            for w in warns:
                st.markdown(
                    f'<div style="background:rgba(217,119,6,0.06);border:1px solid rgba(217,119,6,0.18);border-radius:8px;padding:10px 14px;margin-bottom:6px;font-size:12px;color:#fcd34d;font-family:Syne,sans-serif;">⚠ {w}</div>',
                    unsafe_allow_html=True,
                )
        if recs:
            st.markdown(
                '<div class="section-label" style="margin-top:8px;">Recommendations</div>',
                unsafe_allow_html=True,
            )
            for idx, rec in enumerate(recs, 1):
                st.markdown(
                    f'<div style="background:rgba(249,115,22,0.04);border:1px solid rgba(249,115,22,0.12);border-radius:8px;padding:10px 14px;margin-bottom:6px;font-size:12px;color:rgba(255,255,255,0.7);font-family:Syne,sans-serif;"><span style="color:#f97316;font-weight:700;">{idx}.</span> {rec}</div>',
                    unsafe_allow_html=True,
                )

        st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)
        if st.button("🗑 Clear Results", key="std_clear"):
            st.session_state.standards_result = None
            st.rerun()

    st.markdown(
        '<div class="footer-txt" style="margin-top:20px;">Draft <span>AI</span> &nbsp;|&nbsp; Made with ♥ by Rishi</div>',
        unsafe_allow_html=True,
    )


# ------------------------------------------------------------------
# TAB: 3D → 2D CONVERTER (PREMIUM FEATURE - PASSWORD PROTECTED)
# ------------------------------------------------------------------

elif st.session_state.active_tab == "cad3d":
    if not _is_authenticated():
        render_feature_auth_gate("3D → 2D Converter", "cad3d")
        st.markdown(
            '<div style="font-family:DM Mono,monospace;font-size:10px;color:rgba(255,255,255,0.42);'
            'margin-top:8px;">Sign in with Google to unlock 3D → 2D conversion on your local SolidWorks machine.</div>',
            unsafe_allow_html=True,
        )
        st.stop()

    from cad_converter import is_addin_running, prepare_and_export

    st.markdown(
        """
<style>
.cad-hero{text-align:center;padding:28px 0 16px;}
.cad-hero h1{font-family:'Syne',sans-serif;font-size:30px;font-weight:800;color:#fff;margin:0 0 6px;letter-spacing:-0.03em;}
.cad-hero h1 span{color:#f97316;}
.cad-hero p{font-family:'DM Mono',monospace;font-size:11px;color:rgba(255,255,255,0.3);letter-spacing:0.06em;}
.addin-status{display:flex;align-items:center;gap:10px;padding:12px 16px;border-radius:10px;font-family:'DM Mono',monospace;font-size:11px;margin-bottom:16px;}
.addin-on{background:rgba(34,197,94,0.08);border:1px solid rgba(34,197,94,0.3);color:#22c55e;}
.addin-off{background:rgba(249,115,22,0.08);border:1px solid rgba(249,115,22,0.3);color:#f97316;}
.install-card{background:#111;border:1px solid rgba(255,255,255,0.07);border-radius:12px;padding:20px 24px;margin-bottom:12px;}
.install-step{font-family:'DM Mono',monospace;font-size:11px;color:rgba(255,255,255,0.4);line-height:2.2;}
.install-step strong{color:#fff;}
.install-step code{background:rgba(249,115,22,0.1);color:#f97316;padding:2px 6px;border-radius:4px;}
</style>
""",
        unsafe_allow_html=True,
    )

    st.markdown(
        """
<div class="cad-hero">
  <h1>3D → <span>2D</span> Converter</h1>
  <p>SOLIDWORKS ADD-IN · EXACT DIMENSIONS · PROFESSIONAL VIEWS</p>
</div>""",
        unsafe_allow_html=True,
    )

    # Check add-in status — local first, then cloud relay
    if "addin_ok_cache" not in st.session_state:
        st.session_state.addin_ok_cache = False

    addin_local = is_addin_running()
    addin_ok    = addin_local
    st.session_state.addin_ok_cache = addin_ok

    if addin_local:
        st.markdown(
            '<div class="addin-status addin-on">⚡ SolidWorks Add-in connected on this PC · Ready</div>',
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            '<div class="addin-status addin-off">⚠️ SolidWorks Add-in not detected on this PC · Open SolidWorks with Draft AI add-in loaded, then click Analyze</div>',
            unsafe_allow_html=True,
        )

        with st.expander("📦  Install the Draft AI SolidWorks Add-in", expanded=True):
            st.markdown(
                """
<div class="install-card">
  <div style="font-family:'Syne',sans-serif;font-weight:700;color:#f97316;margin-bottom:12px;">
    One-time setup — takes ~2 minutes
  </div>
  <div class="install-step">
    <strong>1.</strong> Click the button below to download <code>DraftAI.Plugin.V1.zip</code><br>
    <strong>2.</strong> Extract the ZIP to any permanent folder on your PC<br>
    <strong>3.</strong> Right-click <code>install.bat</code> → <strong>Run as Administrator</strong><br>
    <strong>4.</strong> Open SolidWorks → <strong>Tools → Add-Ins</strong> → check <strong>Draft AI</strong> → OK<br>
    <strong>5.</strong> Come back to <b>this website</b> (draftaii.streamlit.app) — it will show ⚡ Connected
  </div>
  <div style="margin-top:12px;padding:10px 14px;background:rgba(249,115,22,0.06);border-radius:8px;font-family:'DM Mono',monospace;font-size:11px;color:rgba(255,255,255,0.5);line-height:1.8;">
    💡 <span style="color:#f97316;">Tip:</span><br>
    Open SolidWorks and make sure Draft AI add-in is loaded before clicking Analyze.
  </div>
</div>
<div style="margin-top:14px;display:flex;align-items:center;gap:10px;">
  <a href="https://github.com/Rishi24-alt/DraftAI-Addin/releases/download/V2/DraftAI.Plugin.V1.zip"
     style="display:inline-flex;align-items:center;gap:7px;
            background:rgba(249,115,22,0.1);
            border:1px solid rgba(249,115,22,0.35);
            color:#f97316;
            font-family:'DM Mono',monospace;
            font-size:11px;
            letter-spacing:0.04em;
            padding:7px 14px;
            border-radius:6px;
            text-decoration:none;
            transition:all 0.2s;
            width:fit-content;"
     onmouseover="this.style.background='#f97316';this.style.color='#000';this.style.borderColor='#f97316';"
     onmouseout="this.style.background='rgba(249,115,22,0.1)';this.style.color='#f97316';this.style.borderColor='rgba(249,115,22,0.35)';">
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" style="width:12px;height:12px;flex-shrink:0;">
      <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M7 10l5 5 5-5M12 15V3"/>
    </svg>
    Download Add-in v1.0
  </a>
  <span style="font-family:'DM Mono',monospace;font-size:10px;color:rgba(255,255,255,0.2);">DraftAI.Plugin.V1.zip · Windows · .NET 4.8</span>
</div>
""",
                unsafe_allow_html=True,
            )

        st.info(
            "Once the add-in is installed, just keep SolidWorks open and upload files here."
        )

    # Upload section (always visible)
    st.markdown("<br>", unsafe_allow_html=True)
    cad_file = st.file_uploader(
        "Upload CAD file",
        type=["step", "stp", "iges", "igs", "stl"],
        label_visibility="collapsed",
        key="cad_uploader",
    )
    st.markdown(
        '<div style="text-align:center;font-family:DM Mono,monospace;font-size:11px;color:rgba(255,255,255,0.2);padding:6px 0 16px;">↑ STEP · STP · IGES · IGS · STL</div>',
        unsafe_allow_html=True,
    )

    if cad_file:
        if st.button(
            "⚡  Generate 2D Views via SolidWorks",
            use_container_width=True,
            key="cad_gen_btn",
            disabled=not addin_ok,
        ):
            can_try = addin_ok
            if not can_try:
                st.warning(
                    "⚠️ SolidWorks Add-in must be running on this PC. "
                    "Open SolidWorks with Draft AI add-in loaded, then click Analyze."
                )
            else:
                with st.spinner("SolidWorks is processing your file... this may take up to 60 seconds"):
                    try:
                        result = prepare_and_export(
                            cad_file.read(),
                            cad_file.name,
                        )
                        st.session_state["cad_result"] = result
                        st.rerun()
                    except Exception as e:
                        st.error(f"Error: {e}")

    # ── Results ──
    if "cad_result" in st.session_state and st.session_state["cad_result"]:
        result = st.session_state["cad_result"]
        views = result["views"]
        dims = result.get("dimensions", {})

        st.markdown(
            "<hr style='border-color:rgba(255,255,255,0.06);margin:24px 0'>",
            unsafe_allow_html=True,
        )

        # Backend badge
        st.markdown(
            f"""<div style="display:inline-flex;align-items:center;gap:8px;
background:rgba(34,197,94,0.08);border:1px solid rgba(34,197,94,0.25);
border-radius:6px;padding:5px 12px;font-family:DM Mono,monospace;
font-size:10px;color:#22c55e;letter-spacing:0.06em;margin-bottom:16px;">
⚡ {result.get("backend","SolidWorks")} · Exact dimensions
</div>""",
            unsafe_allow_html=True,
        )

        # Dimensions
        if dims and "error" not in dims:
            st.markdown(
                '<div style="font-family:DM Mono,monospace;font-size:9px;letter-spacing:0.14em;text-transform:uppercase;color:rgba(255,255,255,0.2);margin-bottom:10px;">Part Dimensions</div>',
                unsafe_allow_html=True,
            )
            d1, d2, d3, d4 = st.columns(4)
            for col, label, val in [
                (d1, "X", f"{dims.get('length','—')} mm"),
                (d2, "Y", f"{dims.get('width','—')} mm"),
                (d3, "Z", f"{dims.get('height','—')} mm"),
                (d4, "SOURCE", dims.get("source", "SolidWorks")),
            ]:
                with col:
                    st.markdown(
                        f'<div style="background:#111;border:1px solid rgba(249,115,22,0.2);border-radius:10px;padding:14px 12px;text-align:center;"><div style="font-family:DM Mono,monospace;font-size:9px;letter-spacing:0.1em;text-transform:uppercase;color:rgba(255,255,255,0.25);margin-bottom:6px;">{label}</div><div style="font-family:Syne,sans-serif;font-size:18px;font-weight:700;color:#f97316;">{val}</div></div>',
                        unsafe_allow_html=True,
                    )

        # Views
        st.markdown(
            '<div style="font-family:DM Mono,monospace;font-size:9px;letter-spacing:0.14em;text-transform:uppercase;color:rgba(255,255,255,0.2);margin:20px 0 10px;">Generated Views</div>',
            unsafe_allow_html=True,
        )
        col1, col2 = st.columns(2)
        for idx, (vkey, vdata) in enumerate(views.items()):
            col = col1 if idx % 2 == 0 else col2
            with col:
                st.markdown(
                    '<div style="background:#111;border:1px solid rgba(255,255,255,0.07);border-radius:12px;padding:16px;margin-bottom:12px;">',
                    unsafe_allow_html=True,
                )
                if vdata.get("png"):
                    b64 = base64.b64encode(vdata["png"]).decode()
                    st.markdown(
                        f'<img src="data:image/png;base64,{b64}" style="width:100%;border-radius:6px;">',
                        unsafe_allow_html=True,
                    )
                else:
                    st.markdown(
                        f'<div style="color:rgba(255,255,255,0.2);padding:40px;text-align:center;">{vdata.get("error","No view")}</div>',
                        unsafe_allow_html=True,
                    )
                st.markdown(
                    f'<div style="font-family:DM Mono,monospace;font-size:10px;letter-spacing:0.1em;text-transform:uppercase;color:rgba(255,255,255,0.3);margin-top:8px;text-align:center;">{vdata["label"]}</div>',
                    unsafe_allow_html=True,
                )
                st.markdown("</div>", unsafe_allow_html=True)

        # Downloads
        import zipfile

        dl1, _, dl3 = st.columns(3)
        with dl1:
            zbuf = io.BytesIO()
            with zipfile.ZipFile(zbuf, "w") as zf:
                for vk, vd in views.items():
                    if vd.get("png"):
                        zf.writestr(f"{vk}.png", vd["png"])
            st.download_button(
                "⬇ PNG Views (.zip)",
                zbuf.getvalue(),
                f"{Path(result['filename']).stem}_views.zip",
                "application/zip",
                use_container_width=True,
                key="dl_png",
            )
        with dl3:
            st.download_button(
                "⬇ PDF Drawing Sheet",
                result["pdf"],
                f"{Path(result['filename']).stem}_drawing.pdf",
                "application/pdf",
                use_container_width=True,
                key="dl_pdf",
            )

        if st.button("🗑 Clear", key="cad_clear"):
            del st.session_state["cad_result"]
            st.rerun()


# ------------------------------------------------------------------
# TAB: ANALYZE
# ------------------------------------------------------------------

else:

    # -- File uploader --
    uploaded_file = st.file_uploader(
        "upload",
        type=["png", "jpg", "jpeg", "webp", "pdf"],
        label_visibility="collapsed",
        key=f"uploader_{st.session_state.uploader_key}",
    )

    # -- If file is removed, clear cache immediately so stale image never shows --
    if not uploaded_file:
        st.session_state.current_drawing_image = None
        st.session_state.current_drawing_name = None
        st.markdown(
            """<div class="upload-hint"><span>⬆</span> Drop your engineering drawing to begin &nbsp;·&nbsp; PNG · JPEG · WEBP · max 10 MB</div>""",
            unsafe_allow_html=True,
        )

    file_ok = False

    if uploaded_file:
        size_mb = check_file_size(uploaded_file)
        if size_mb > MAX_FILE_SIZE_MB:
            st.error(
                f"File too large: {size_mb:.1f} MB. Maximum is {MAX_FILE_SIZE_MB} MB."
            )
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
                    st.session_state.current_drawing_image = base64.b64encode(
                        img_bytes
                    ).decode("utf-8")
            else:
                file_ok = True
                uploaded_file.seek(0)
                img_bytes = uploaded_file.read()
                uploaded_file.seek(0)
                render_drawing_preview(img_bytes, uploaded_file.name)
                st.session_state.current_drawing_name = uploaded_file.name
                st.session_state.current_drawing_image = base64.b64encode(
                    img_bytes
                ).decode("utf-8")

    # -- Quick action buttons --
    st.markdown(
        '<div class="section-label" style="margin-top:8px;">Quick Analysis</div>',
        unsafe_allow_html=True,
    )
    c1, c2, c3, c4 = st.columns(4, gap="small")
    with c1:
        q1 = st.button("📐  Dimensions", use_container_width=True)
        q5 = st.button("📝  Summarize", use_container_width=True)
    with c2:
        q2 = st.button("🎯  GD&T Analysis", use_container_width=True)
        q6 = st.button("⚠️  Design Concerns", use_container_width=True)
    with c3:
        q3 = st.button("🧱  Material Rec.", use_container_width=True)
        q7 = st.button("🏭  Manufacturing", use_container_width=True)
    with c4:
        q4 = st.button("🏷️  Title Block", use_container_width=True)
        q8 = st.button("👁️  View Type", use_container_width=True)

    # -- Advanced Features --
    st.markdown(
        '<div class="section-label" style="margin-top:10px;">Advanced Analysis</div>',
        unsafe_allow_html=True,
    )
    a1, a2, a3, a4, a5 = st.columns(5, gap="small")
    with a1:
        qa1 = st.button(
            "⚖️  Tolerance",
            use_container_width=True,
            help="Analyse dimensional chains and worst-case fits",
        )
    with a2:
        qa2 = st.button(
            "🔬  DFM Score",
            use_container_width=True,
            help="Score manufacturability 0-100 with breakdown",
        )
    with a3:
        qa3 = st.button(
            "💰  Cost Est.",
            use_container_width=True,
            help="Rough per-unit cost estimate across volumes",
        )
    with a4:
        qa4 = st.button(
            "🔍  Dim. Check",
            use_container_width=True,
            help="Find missing dimensions, tolerances & annotations",
        )
    with a5:
        qa5 = st.button(
            "🔄  Rev. Diff",
            use_container_width=True,
            help="Upload a second drawing to compare revisions",
        )

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
        st.markdown("</div>", unsafe_allow_html=True)

    # -- Chat section --
    st.markdown(
        """<div class="chat-section-header">Conversation</div>""",
        unsafe_allow_html=True,
    )

    # Enable scroll only when chat has messages — no visible scrollbar
    if st.session_state.messages_display:
        st.markdown(
            """<style>
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
</style>""",
            unsafe_allow_html=True,
        )

    # suggestion chip state
    chip_question = None

    # -- Chat message display --
    if not st.session_state.messages_display:
        st.markdown(
            """
<div class="chat-empty">
  <div class="chat-empty-icon">⚙️</div>
  <div class="chat-empty-title">No analysis yet</div>
  <div class="chat-empty-sub">Upload a drawing above, then tap a suggestion or ask anything</div>
</div>""",
            unsafe_allow_html=True,
        )
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
                chip_question = (
                    "Suggest the best material for this part and explain why."
                )
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

    st.markdown(
        '<div class="footer-txt" style="margin-top:20px;">Draft <span>AI</span> &nbsp;|&nbsp; Made with ♥ by Rishi</div>',
        unsafe_allow_html=True,
    )

    # -- Bottom input bar --
    st.markdown(
        """
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
""",
        unsafe_allow_html=True,
    )

    custom_q = st.text_area(
        "msg",
        placeholder="Ask anything about the drawing...",
        label_visibility="collapsed",
        height=52,
    )
    col_ask, col_clear, col_pdf = st.columns([4, 1, 1], gap="small")

    with col_ask:
        ask_btn = st.button("Analyze", type="primary", use_container_width=True)

    with col_clear:
        if st.button(
            "\U0001f5d1\ufe0f Clear", use_container_width=True, help="Clear chat"
        ):
            st.session_state.chat_history = []
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
                "\U0001f4c4 Export PDF",
                data=pdf_buf,
                file_name="drawing_analysis.pdf",
                mime="application/pdf",
                use_container_width=True,
            )
        else:
            st.button("\U0001f4c4 Export PDF", disabled=True, use_container_width=True)

    st.markdown("</div></div>", unsafe_allow_html=True)

    # ------------------------------------------
    # PROCESS � Determine which action to run
    # ------------------------------------------

    question = None
    special_action = None
    if "chip_question" not in dir():
        chip_question = None
    # Pick up questions forwarded from batch/BOM tabs
    if st.session_state.get("_pending_question"):
        question = st.session_state.pop("_pending_question")

    if q1:
        special_action = "dimensions"
    elif q2:
        special_action = "gdt"
    elif q3:
        special_action = "material"
    elif q4:
        special_action = "titleblock"
    elif q5:
        question = "Give a comprehensive summary: drawing type, component description, key dimensions, materials, and special requirements."
    elif q6:
        special_action = "design"
    elif q7:
        special_action = "manufacturing"
    elif q8:
        question = "Identify all views shown (front, side, top, isometric, section etc.) and explain what each view reveals about the component."
    elif qa1:
        special_action = "tolerance_stackup"
    elif qa2:
        special_action = "mfg_score"
    elif qa3:
        special_action = "cost_estimate"
    elif qa4:
        special_action = "missing_dims"
    elif chip_question:
        question = chip_question
    elif ask_btn and custom_q:
        question = custom_q
    elif ask_btn and not custom_q:
        st.warning("Please type a question first.")

    # Spinner messages and user-facing labels per action
    ACTION_MAP = {
        "dimensions": ("Detecting dimensions...", "Dimension Detection"),
        "gdt": ("Analyzing GD&T...", "GD&T Analysis"),
        "design": ("Reviewing design concerns...", "Design Concern Review"),
        "material": ("Generating material analysis...", "Material Recommendation"),
        "manufacturing": (
            "Analyzing manufacturing methods...",
            "Manufacturing Suggestions",
        ),
        "titleblock": ("Reading title block...", "Title Block"),
        "tolerance_stackup": (
            "Calculating tolerance stack-up...",
            "Tolerance Stack-Up Analysis",
        ),
        "mfg_score": ("Scoring manufacturability...", "Manufacturability Score"),
        "cost_estimate": ("Estimating part cost...", "Cost Estimation"),
        "missing_dims": (
            "Checking for missing dimensions...",
            "Missing Dimension Detection",
        ),
    }

    # -- Special action handler --
    if special_action:
        if not uploaded_file or not file_ok:
            st.warning("Please upload a valid engineering drawing first.")
        else:
            ip = get_client_ip()
            allowed, remaining, mins_left = check_rate_limit(ip)
            if not allowed:
                st.markdown(
                    f"""
<div style="background:rgba(249,115,22,0.07);border:1px solid rgba(249,115,22,0.25);border-radius:12px;padding:16px 20px;margin:8px 0;">
    <div style="font-size:15px;margin-bottom:6px;">🪫 Whoa, easy there!</div>
    <div style="font-family:'Syne',sans-serif;font-size:13px;color:rgba(255,255,255,0.85);line-height:1.7;margin-bottom:10px;">
        You've hit the <b style="color:#f97316;">2 requests/hour</b> free limit.<br>
        Honestly? We're running on <b>dreams and ramen</b> over here. 🍜<br>
        Every API call costs us money and our wallets are crying. 😭<br><br>
        If you're enjoying Draft AI, consider buying us a coffee — or just a cup of water at this point.<br>
        We'll use it to raise your limit, we promise. XOXO 🧡
    </div>
    <div style="font-family:'DM Mono',monospace;font-size:10px;color:rgba(255,255,255,0.3);letter-spacing:0.05em;">
        ⏱ Try again in ~{mins_left} min &nbsp;·&nbsp; Or donate and get more — coming soon
    </div>
</div>
""",
                    unsafe_allow_html=True,
                )
            else:
                spinner_msg, user_label = ACTION_MAP[special_action]
                with st.spinner(spinner_msg):
                    uploaded_file.seek(0)
                    if special_action == "dimensions":
                        result = detect_dimensions(uploaded_file)
                    elif special_action == "gdt":
                        result = analyze_gdt(uploaded_file)
                    elif special_action == "design":
                        result = analyze_design_concerns(uploaded_file)
                    elif special_action == "material":
                        result = analyze_material(uploaded_file)
                    elif special_action == "manufacturing":
                        result = analyze_manufacturing(uploaded_file)
                    elif special_action == "tolerance_stackup":
                        result = analyze_tolerance_stackup(uploaded_file)
                    elif special_action == "mfg_score":
                        result = analyze_manufacturability_score(uploaded_file)
                    elif special_action == "cost_estimate":
                        result = estimate_cost(uploaded_file)
                    elif special_action == "missing_dims":
                        result = detect_missing_dimensions(uploaded_file)
                    elif special_action == "titleblock":
                        result = extract_title_block(uploaded_file)
                        st.session_state.title_block_data = result
                increment_rate_limit(ip)
                prefix = {"dimensions": "__DIM__", "titleblock": "__TB__"}.get(
                    special_action, ""
                )
                ai_content = f"{prefix}{result}"
                st.session_state.messages_display.append(
                    {"role": "user", "content": user_label}
                )
                st.session_state.messages_display.append(
                    {"role": "ai", "content": ai_content}
                )
                st.session_state.chat_history.append(
                    {"role": "user", "content": user_label}
                )
                st.session_state.chat_history.append(
                    {"role": "assistant", "content": result}
                )
                persist_chat()
                st.rerun()

    # -- Revision comparison handler (needs two files) --
    if st.session_state.show_revision_panel and rev_file_b:
        if not uploaded_file or not file_ok:
            st.warning(
                "Please upload the primary drawing (Rev A) using the upload box above first."
            )
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

                st.session_state.messages_display.append(
                    {
                        "role": "user",
                        "content": f"🔄 Compare Revisions: {uploaded_file.name} vs {rev_file_b.name}",
                    }
                )
                st.session_state.messages_display.append(
                    {"role": "ai", "content": result}
                )
                st.session_state.chat_history.append(
                    {"role": "user", "content": "Compare drawing revisions"}
                )
                st.session_state.chat_history.append(
                    {"role": "assistant", "content": result}
                )
                st.session_state.show_revision_panel = False
                persist_chat()
                st.rerun()
    # -- Free-text question handler --
    if question:
        if not uploaded_file or not file_ok:
            st.warning("Please upload a valid engineering drawing first.")
        else:
            ip = get_client_ip()
            allowed, remaining, mins_left = check_rate_limit(ip)
            if not allowed:
                st.markdown(
                    f"""
<div style="background:rgba(249,115,22,0.07);border:1px solid rgba(249,115,22,0.25);border-radius:12px;padding:16px 20px;margin:8px 0;">
    <div style="font-size:15px;margin-bottom:6px;">🪫 Whoa, easy there!</div>
    <div style="font-family:'Syne',sans-serif;font-size:13px;color:rgba(255,255,255,0.85);line-height:1.7;margin-bottom:10px;">
        You've hit the <b style="color:#f97316;">2 requests/hour</b> free limit.<br>
        Honestly? We're running on <b>dreams and ramen</b> over here. 🍜<br>
        Every API call costs us money and our wallets are crying. 😭<br><br>
        If you're enjoying Draft AI, consider buying us a coffee — or just a cup of water at this point.<br>
        We'll use it to raise your limit, we promise. XOXO 🧡
    </div>
    <div style="font-family:'DM Mono',monospace;font-size:10px;color:rgba(255,255,255,0.3);letter-spacing:0.05em;">
        ⏱ Try again in ~{mins_left} min &nbsp;·&nbsp; Or donate and get more — coming soon
    </div>
</div>
""",
                    unsafe_allow_html=True,
                )
            else:
                with st.spinner("Analyzing..."):
                    uploaded_file.seek(0)
                    answer = analyze_drawing(
                        uploaded_file, question, st.session_state.chat_history
                    )
                increment_rate_limit(ip)
                st.session_state.messages_display.append(
                    {"role": "user", "content": question}
                )
                st.session_state.messages_display.append(
                    {"role": "ai", "content": answer}
                )
                st.session_state.chat_history.append(
                    {"role": "user", "content": question}
                )
                st.session_state.chat_history.append(
                    {"role": "assistant", "content": answer}
                )
                persist_chat()
                st.rerun()
