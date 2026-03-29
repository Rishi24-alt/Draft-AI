"""
Draft AI — 3D to 2D CAD Converter
Communicates with the DraftAI SolidWorks Add-in via:
  - localhost:7432 when running locally on same PC as SolidWorks
  - Railway cloud relay when running on hosted site
"""

import os
import io
import json
import time
import uuid
import re
import base64
import urllib.request
from pathlib import Path

CLOUD_URL  = "https://web-production-a87eb.up.railway.app"
ADDIN_URL  = "http://localhost:7432"
OUTPUT_DIR = os.path.join(os.path.expanduser("~"), "DraftAI_Output")


def _json_from_response(raw: bytes, context: str) -> dict:
    """Decode JSON API responses with clear error context."""
    text = raw.decode("utf-8", errors="replace").strip()
    if not text:
        raise ValueError(f"{context} returned an empty response.")
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        preview = text[:220].replace("\n", " ")
        raise ValueError(f"{context} returned non-JSON response: {preview}") from e


def _json_from_value(raw_value, context: str, default=None):
    """Decode optional JSON string/dict values safely."""
    if default is None:
        default = {}

    if raw_value is None or raw_value == "":
        return default
    if isinstance(raw_value, (dict, list)):
        return raw_value
    if isinstance(raw_value, bytes):
        raw_value = raw_value.decode("utf-8", errors="replace")

    text = str(raw_value).strip()
    if not text:
        return default
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        preview = text[:180].replace("\n", " ")
        raise ValueError(f"{context} is not valid JSON: {preview}") from e


def _sanitize_pairing_code(pairing_code: str) -> str:
    """Keep pairing code URL-safe without lossy truncation."""
    if not pairing_code:
        return ""
    clean = re.sub(r"[^A-Za-z0-9_-]", "", pairing_code.strip())
    return clean[:160]


# ─────────────────────────────────────────────────────────────
# Image processing
# ─────────────────────────────────────────────────────────────

def convert_to_2d_style(png_bytes: bytes) -> bytes:
    """
    Convert a raw SolidWorks render into a crisp, professional engineering drawing style:
    - Dark navy/charcoal background (#0d0d0d)
    - Clean white/bright-white geometry lines with sharpened edges
    - Upscaled to 1200×900 for high-res display
    - Subtle brightness/contrast pass to punch up faint geometry
    """
    try:
        from PIL import Image, ImageOps, ImageFilter, ImageEnhance

        img = Image.open(io.BytesIO(png_bytes)).convert("RGB")

        # ── 1. Upscale for sharper display ──────────────────────────────
        TARGET_W, TARGET_H = 1200, 900
        img = img.resize((TARGET_W, TARGET_H), Image.LANCZOS)

        # ── 2. Convert to grayscale, extract geometry ────────────────────
        gray = img.convert("L")

        # Aggressive contrast lift — pulls faint lines out of near-white bg
        gray = ImageEnhance.Contrast(gray).enhance(3.5)
        gray = ImageEnhance.Brightness(gray).enhance(0.85)

        # Edge detection to find geometry outlines
        edges = gray.filter(ImageFilter.FIND_EDGES)
        edges = ImageEnhance.Contrast(edges).enhance(8.0)

        # Also keep original dark pixels (thick geometry lines)
        # Invert gray so geometry = white, background = black
        inv = ImageOps.invert(gray)
        inv = inv.point(lambda x: 255 if x > 90 else 0)

        # Merge: edges OR original dark geometry
        import PIL.ImageChops as chops
        geometry = chops.lighter(edges, inv)

        # Sharpen the merged geometry mask
        geometry = geometry.filter(ImageFilter.MaxFilter(2))
        geometry = ImageEnhance.Contrast(geometry).enhance(4.0)
        geometry = geometry.point(lambda x: 255 if x > 60 else 0)

        # ── 3. Compose onto dark engineering background ──────────────────
        BG_COLOR   = (13,  13,  20)   # near-black dark navy
        LINE_COLOR = (235, 240, 255)  # clean blue-white for lines

        bg = Image.new("RGB", (TARGET_W, TARGET_H), BG_COLOR)

        # Tint geometry lines with line color
        line_layer = Image.new("RGB", (TARGET_W, TARGET_H), LINE_COLOR)
        mask = geometry.convert("L")

        result = Image.composite(line_layer, bg, mask)

        # ── 4. Final sharpening pass ─────────────────────────────────────
        result = result.filter(ImageFilter.SHARPEN)
        result = result.filter(ImageFilter.SHARPEN)

        out = io.BytesIO()
        result.save(out, format="PNG", optimize=False)
        return out.getvalue()

    except Exception:
        return png_bytes


# ─────────────────────────────────────────────────────────────
# Connection detection
# ─────────────────────────────────────────────────────────────

def is_addin_running() -> bool:
    """Check if add-in is running locally on this machine."""
    try:
        with urllib.request.urlopen(f"{ADDIN_URL}/ping", timeout=2) as r:
            return _json_from_response(r.read(), "Local add-in /ping").get("status") == "ok"
    except Exception:
        return False


def is_addin_online_cloud() -> bool:
    """Check if any add-in instance is connected via cloud relay."""
    try:
        with urllib.request.urlopen(f"{CLOUD_URL}/addin/status", timeout=5) as r:
            return _json_from_response(r.read(), "Cloud relay /addin/status").get("online", False)
    except Exception:
        return False


# ─────────────────────────────────────────────────────────────
# Cloud relay
# ─────────────────────────────────────────────────────────────

def _cloud_post(endpoint: str, payload: dict) -> dict:
    body = json.dumps(payload).encode()
    req  = urllib.request.Request(
        f"{CLOUD_URL}{endpoint}",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    with urllib.request.urlopen(req, timeout=15) as r:
        return _json_from_response(r.read(), f"Cloud relay POST {endpoint}")


def _cloud_get(endpoint: str) -> dict:
    with urllib.request.urlopen(f"{CLOUD_URL}{endpoint}", timeout=10) as r:
        return _json_from_response(r.read(), f"Cloud relay GET {endpoint}")


def _cloud_poll(session_id: str, timeout: int = 120) -> dict:
    deadline = time.monotonic() + timeout
    poll_interval_seconds = 3
    last_error = None

    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(
                f"{CLOUD_URL}/addin/poll/{session_id}", timeout=5
            ) as r:
                data = _json_from_response(r.read(), f"Cloud relay poll {session_id}")
                if data.get("status") != "waiting":
                    return data
        except Exception as exc:
            last_error = exc

        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        time.sleep(min(poll_interval_seconds, remaining))

    error_message = "Add-in did not respond in time. Make sure SolidWorks is open with Draft AI add-in loaded."
    if last_error is not None:
        error_message = f"{error_message} Last poll error: {last_error}"
    return {
        "success": False,
        "error": error_message
    }


def _get_dedicated_addin(user_session: str) -> str:
    """
    Get a dedicated add-in instance for this user session.
    Returns addin_id or None if no add-in available.
    """
    result = _cloud_post("/addin/connect", {"user_session": user_session})
    addin_id = result.get("addin_id")
    status   = result.get("status")
    if not addin_id or status == "no_addin_available":
        return None
    return addin_id


def prepare_and_export_cloud(file_bytes: bytes, filename: str, user_token: str = "") -> dict:
    """Upload file to cloud relay with automatic routing first, manual pairing as fallback."""
    raw_token = (user_token or "").strip()
    pairing_code = _sanitize_pairing_code(raw_token)
    session_id   = str(uuid.uuid4())[:12]
    b64          = base64.b64encode(file_bytes).decode()

    # 1) If a full addin_id_cloud is provided, use strict exact routing.
    # 2) Otherwise, ask cloud for a dedicated add-in bound to this user/session key.
    target_addin_id = ""
    if pairing_code and "_" in pairing_code:
        target_addin_id = pairing_code
    else:
        user_session = raw_token or f"guest_{session_id}"
        target_addin_id = _get_dedicated_addin(user_session)
        if not target_addin_id:
            raise RuntimeError(
                "No SolidWorks add-in instance is currently available for this account. "
                "Open SolidWorks with Draft AI add-in loaded on your machine, then retry."
            )

    # Push job to the resolved add-in instance.
    _cloud_post("/addin/job", {
        "session_id": session_id,
        "addin_id":   target_addin_id,
        "job":        "export_3d",
        "filename":   filename,
        "file_b64":   b64,
    })

    result = _cloud_poll(session_id, timeout=120)
    if not result.get("success"):
        raise RuntimeError(result.get("error", "Export failed"))
    result_addin_id = str(result.get("addin_id", "")).strip()
    if result_addin_id and result_addin_id != target_addin_id:
        raise RuntimeError(
            "Relay safety check failed: result came from a different add-in instance."
        )

    views_b64 = result.get("views", {})
    dims = _json_from_value(result.get("dimensions", {}), "Cloud relay dimensions")
    view_labels = {
        "front": "Front View", "top": "Top View",
        "side":  "Side View",  "isometric": "Isometric View"
    }
    views = {}
    for vkey, vlabel in view_labels.items():
        if vkey in views_b64 and views_b64[vkey]:
            png = base64.b64decode(views_b64[vkey])
            png = convert_to_2d_style(png)
            if dims:
                png = annotate_with_dims(png, dims, vkey)
            views[vkey] = {"png": png, "svg": None, "label": vlabel}
        else:
            views[vkey] = {"png": None, "svg": None, "label": vlabel, "error": "Not exported"}

    return {
        "ready":      True,
        "views":      views,
        "dimensions": dims,
        "pdf":        generate_pdf(views, filename, dims),
        "filename":   filename,
        "backend":    "SolidWorks Add-in ✓ (cloud relay)",
    }


# ─────────────────────────────────────────────────────────────
# Smart router — local or cloud
# ─────────────────────────────────────────────────────────────

def prepare_and_export(file_bytes: bytes, filename: str, user_token: str = "") -> dict:
    """
    Secure hybrid mode:
    - Prefer local add-in if available on this PC.
    - Otherwise route through cloud relay to the exact paired add-in_id instance.
    """
    if is_addin_running():
        return _prepare_and_export_local(file_bytes, filename)
    return prepare_and_export_cloud(file_bytes, filename, user_token=user_token)


def _prepare_and_export_local(file_bytes: bytes, filename: str) -> dict:
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    file_path = os.path.join(OUTPUT_DIR, filename)
    with open(file_path, "wb") as f:
        f.write(file_bytes)

    for fn in ["status.json", "dimensions.json", "front.png", "top.png", "side.png", "isometric.png"]:
        fp = os.path.join(OUTPUT_DIR, fn)
        if os.path.exists(fp):
            os.remove(fp)

    payload = json.dumps({"file_path": file_path, "output_dir": OUTPUT_DIR}).encode()
    req = urllib.request.Request(
        f"{ADDIN_URL}/export",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    with urllib.request.urlopen(req, timeout=120) as r:
        result = _json_from_response(r.read(), "Local add-in /export")

    if not result.get("success"):
        raise RuntimeError(result.get("error", "Export failed"))
    return load_results(OUTPUT_DIR)


def load_results(output_dir: str = None) -> dict:
    if output_dir is None:
        output_dir = OUTPUT_DIR
    sf = os.path.join(output_dir, "status.json")
    if not os.path.exists(sf):
        return {"ready": False, "reason": "No results yet"}
    try:
        with open(sf, "r", encoding="utf-8") as status_file:
            status = _json_from_value(status_file.read(), "status.json")
        if not status.get("completed"):
            return {"ready": False, "reason": "Export did not complete"}
    except Exception:
        return {"ready": False, "reason": "Could not read status.json"}

    dims = {}
    df = os.path.join(output_dir, "dimensions.json")
    if os.path.exists(df):
        with open(df, "r", encoding="utf-8") as dims_file:
            dims = _json_from_value(dims_file.read(), "dimensions.json")

    view_labels = {
        "front": "Front View", "top": "Top View",
        "side":  "Side View",  "isometric": "Isometric View"
    }
    views = {}
    for vkey, vlabel in view_labels.items():
        pp = os.path.join(output_dir, f"{vkey}.png")
        if os.path.exists(pp):
            with open(pp, "rb") as png_file:
                png = png_file.read()
            png = convert_to_2d_style(png)
            if dims:
                png = annotate_with_dims(png, dims, vkey)
            views[vkey] = {"png": png, "svg": None, "label": vlabel}
        else:
            views[vkey] = {"png": None, "svg": None, "label": vlabel, "error": "Not exported"}

    return {
        "ready":      True,
        "views":      views,
        "dimensions": dims,
        "pdf":        generate_pdf(views, Path(status.get("file", "drawing")).name, dims),
        "filename":   Path(status.get("file", "drawing")).name,
        "backend":    "SolidWorks Add-in ✓",
        "output_dir": output_dir,
    }


# ─────────────────────────────────────────────────────────────
# Annotation
# ─────────────────────────────────────────────────────────────

def annotate_with_dims(png_bytes: bytes, dims: dict, view_key: str) -> bytes:
    """
    Overlay professional engineering annotations onto a view image:
    - Orange dimension lines with arrowheads
    - Dark pill-shaped dimension labels
    - View title badge (bottom-center)
    - Thin border frame
    - Projection angle indicator (bottom-right for orthographic views)
    """
    try:
        from PIL import Image, ImageDraw, ImageFont

        img  = Image.open(io.BytesIO(png_bytes)).convert("RGBA")
        ov   = Image.new("RGBA", img.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(ov)
        W, H = img.size

        # ── Colour palette ────────────────────────────────────────────────
        ORANGE    = (249, 115,  22, 255)
        ORANGE_DIM= (249, 115,  22, 200)
        BG_PILL   = ( 10,  10,  18, 220)
        WHITE     = (240, 245, 255, 240)
        GRAY      = (160, 170, 190, 160)
        BORDER    = ( 60,  65,  80, 180)

        # ── Fonts ─────────────────────────────────────────────────────────
        try:
            fnt_big  = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 18)
            fnt_med  = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",      15)
            fnt_sml  = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",      13)
            fnt_lbl  = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 13)
        except Exception:
            try:
                fnt_big = ImageFont.truetype("arial.ttf", 18)
                fnt_med = ImageFont.truetype("arial.ttf", 15)
                fnt_sml = ImageFont.truetype("arial.ttf", 13)
                fnt_lbl = ImageFont.truetype("arialbd.ttf", 13)
            except Exception:
                fnt_big = fnt_med = fnt_sml = fnt_lbl = ImageFont.load_default()

        # ── Detect bounding box of visible geometry ───────────────────────
        gray_img = img.convert("L")
        px = gray_img.load()
        x0, y0, x1, y1 = W, H, 0, 0
        for py in range(H):
            for px2 in range(W):
                if px[px2, py] > 30:          # bright pixel = geometry on dark bg
                    x0 = min(x0, px2); x1 = max(x1, px2)
                    y0 = min(y0, py);  y1 = max(y1, py)
        if x1 <= x0 or y1 <= y0:
            x0, y0, x1, y1 = W // 6, H // 6, 5 * W // 6, 5 * H // 6

        PAD = 14  # keep annotations clear of border

        # ── Helper: pill-shaped text badge ────────────────────────────────
        def pill(cx, cy, txt, fnt, fg=ORANGE, bg=BG_PILL, pad_x=10, pad_y=5):
            bb  = draw.textbbox((0, 0), txt, font=fnt)
            tw, th = bb[2]-bb[0], bb[3]-bb[1]
            rx0, ry0 = cx - tw//2 - pad_x, cy - th//2 - pad_y
            rx1, ry1 = cx + tw//2 + pad_x, cy + th//2 + pad_y
            r = (ry1 - ry0) // 2
            draw.rounded_rectangle([rx0, ry0, rx1, ry1], radius=r, fill=bg)
            draw.text((cx - tw//2, cy - th//2), txt, fill=fg, font=fnt)

        # ── Helper: horizontal dimension line ─────────────────────────────
        def hdim(xa, xb, yy, txt, offset=36):
            yl  = yy + offset
            aw  = 10        # arrowhead size
            # extension lines
            draw.line([(xa, yy+4), (xa, yl+6)], fill=ORANGE_DIM, width=1)
            draw.line([(xb, yy+4), (xb, yl+6)], fill=ORANGE_DIM, width=1)
            # dimension line
            draw.line([(xa+aw, yl), (xb-aw, yl)], fill=ORANGE_DIM, width=2)
            # arrowheads
            draw.polygon([(xa, yl), (xa+aw+2, yl-5), (xa+aw+2, yl+5)], fill=ORANGE)
            draw.polygon([(xb, yl), (xb-aw-2, yl-5), (xb-aw-2, yl+5)], fill=ORANGE)
            # label
            pill((xa+xb)//2, yl, txt, fnt_med)

        # ── Helper: vertical dimension line ───────────────────────────────
        def vdim(ya, yb, xx, txt, offset=44):
            xl  = xx - offset
            ah  = 10
            # extension lines
            draw.line([(xx-4, ya), (xl-6, ya)], fill=ORANGE_DIM, width=1)
            draw.line([(xx-4, yb), (xl-6, yb)], fill=ORANGE_DIM, width=1)
            # dimension line
            draw.line([(xl, ya+ah), (xl, yb-ah)], fill=ORANGE_DIM, width=2)
            # arrowheads
            draw.polygon([(xl, ya), (xl-5, ya+ah+2), (xl+5, ya+ah+2)], fill=ORANGE)
            draw.polygon([(xl, yb), (xl-5, yb-ah-2), (xl+5, yb-ah-2)], fill=ORANGE)
            # label (rotated — simulate by placing centered)
            pill(xl, (ya+yb)//2, txt, fnt_med)

        # ── Draw thin frame border ────────────────────────────────────────
        bp = 6
        draw.rectangle([bp, bp, W-bp, H-bp], outline=BORDER, width=1)

        # ── Dimension callouts per view ───────────────────────────────────
        L  = dims.get("length", 0)
        Wd = dims.get("width",  0)
        Ht = dims.get("height", 0)

        h_offset = min(48, (H - y1) // 2 + 8)
        v_offset = min(56, x0 // 2 + 10)

        if view_key == "front":
            if L:  hdim(x0, x1, y1, f"X  {L} mm", offset=h_offset)
            if Ht: vdim(y0, y1, x0, f"Z  {Ht} mm", offset=v_offset)
        elif view_key == "top":
            if L:  hdim(x0, x1, y1, f"X  {L} mm", offset=h_offset)
            if Wd: vdim(y0, y1, x0, f"Y  {Wd} mm", offset=v_offset)
        elif view_key == "side":
            if Wd: hdim(x0, x1, y1, f"Y  {Wd} mm", offset=h_offset)
            if Ht: vdim(y0, y1, x0, f"Z  {Ht} mm", offset=v_offset)
        elif view_key == "isometric":
            # Stack info badges in top-left corner
            infos = []
            if L:  infos.append(f"X  {L} mm")
            if Wd: infos.append(f"Y  {Wd} mm")
            if Ht: infos.append(f"Z  {Ht} mm")
            iy = 28
            for info in infos:
                bb  = draw.textbbox((0, 0), info, font=fnt_med)
                tw, th = bb[2]-bb[0], bb[3]-bb[1]
                pill(tw//2 + PAD + 10, iy, info, fnt_med)
                iy += th + 16

        # ── View title badge — bottom-center ─────────────────────────────
        view_titles = {
            "front":     "FRONT VIEW",
            "top":       "TOP VIEW",
            "side":      "SIDE VIEW  (RIGHT)",
            "isometric": "ISOMETRIC VIEW",
        }
        title = view_titles.get(view_key, view_key.upper())
        title_y = H - 26
        pill(W // 2, title_y, title, fnt_lbl, fg=WHITE, bg=(30, 32, 48, 230), pad_x=16, pad_y=7)

        # ── Third-angle projection symbol for orthographic views ──────────
        if view_key in ("front", "top", "side"):
            sym_x, sym_y = W - 38, H - 38
            r = 10
            draw.ellipse([sym_x-r, sym_y-r, sym_x+r, sym_y+r], outline=GRAY, width=1)
            draw.ellipse([sym_x-r//3, sym_y-r//3, sym_x+r//3, sym_y+r//3], fill=GRAY)

        # ── Composite and return ──────────────────────────────────────────
        combined = Image.alpha_composite(img, ov).convert("RGB")
        out = io.BytesIO()
        combined.save(out, format="PNG")
        return out.getvalue()

    except Exception:
        return png_bytes


# ─────────────────────────────────────────────────────────────
# PDF generation
# ─────────────────────────────────────────────────────────────

def generate_pdf(views: dict, filename: str, dims: dict = None) -> bytes:
    """
    Generate a professional A3 engineering drawing sheet with:
    - Light cream/white background (print-ready)
    - Four properly-scaled views in standard third-angle layout
    - Formal title block matching ISO/ASME conventions
    - Dimension summary per view
    """
    from reportlab.pdfgen import canvas as rl_canvas
    from reportlab.lib.pagesizes import A3, landscape as rl_landscape
    from reportlab.lib.units import mm
    from reportlab.lib.utils import ImageReader
    from PIL import Image
    from datetime import datetime as _dt

    buf = io.BytesIO()
    W, H = rl_landscape(A3)
    c = rl_canvas.Canvas(buf, pagesize=rl_landscape(A3))

    # ── Sheet background ──────────────────────────────────────────────
    c.setFillColorRGB(0.975, 0.972, 0.960)          # warm off-white
    c.rect(0, 0, W, H, fill=1, stroke=0)

    # ── Border: outer thick + inner thin ─────────────────────────────
    c.setStrokeColorRGB(0.1, 0.1, 0.1)
    c.setLineWidth(2.5)
    c.rect(5*mm, 5*mm, W-10*mm, H-10*mm, fill=0, stroke=1)
    c.setLineWidth(0.5)
    fi = 14*mm
    c.rect(fi, fi, W-2*fi, H-2*fi, fill=0, stroke=1)

    # ── Title strip at top ────────────────────────────────────────────
    strip_h = 10*mm
    strip_y = H - fi - strip_h
    c.setFillColorRGB(0.08, 0.08, 0.12)
    c.rect(fi, strip_y, W-2*fi, strip_h, fill=1, stroke=0)
    c.setFillColorRGB(0.976, 0.451, 0.086)         # #f97316 orange
    c.setFont("Helvetica-Bold", 10)
    c.drawString(fi + 5*mm, strip_y + 3.5*mm, "DRAFT AI")
    c.setFillColorRGB(1, 1, 1)
    c.setFont("Helvetica", 8)
    part_name = (filename
                 .replace(".STEP", "").replace(".step", "")
                 .replace(".stp",  "").replace(".STP",  "")
                 .replace(".SLDPRT", "").replace(".sldprt", ""))
    c.drawCentredString(W/2, strip_y + 3.5*mm, f"ENGINEERING DRAWING  —  {part_name.upper()[:40]}")
    c.setFillColorRGB(0.6, 0.6, 0.6)
    c.setFont("Helvetica", 7)
    c.drawRightString(W - fi - 4*mm, strip_y + 3.5*mm, _dt.now().strftime("%d %b %Y"))

    # ── Title block (bottom-right) ────────────────────────────────────
    tb_w, tb_h = 108*mm, 48*mm
    tb_x = W - fi - tb_w
    tb_y = fi

    c.setFillColorRGB(1, 1, 1)
    c.rect(tb_x, tb_y, tb_w, tb_h, fill=1, stroke=0)
    c.setStrokeColorRGB(0.25, 0.25, 0.25)
    c.setLineWidth(0.7)
    c.rect(tb_x, tb_y, tb_w, tb_h, fill=0, stroke=1)

    # Internal grid lines
    row_hs = [tb_h * f for f in (0.78, 0.56, 0.34, 0.12)]
    c.setLineWidth(0.35)
    for rh in row_hs:
        c.line(tb_x, tb_y + rh, tb_x + tb_w, tb_y + rh)
    mx = tb_x + tb_w * 0.5
    c.line(mx, tb_y, mx, tb_y + row_hs[0])

    def lbl_tb(x, y, t, sz=5.5):
        c.setFont("Helvetica", sz)
        c.setFillColorRGB(0.5, 0.5, 0.5)
        c.drawString(x, y, t)

    def val_tb(x, y, t, sz=8.5, bold=False):
        c.setFont("Helvetica-Bold" if bold else "Helvetica", sz)
        c.setFillColorRGB(0.05, 0.05, 0.05)
        c.drawString(x, y, t)

    r0 = tb_y + row_hs[0]
    r1 = tb_y + row_hs[1]
    r2 = tb_y + row_hs[2]
    r3 = tb_y + row_hs[3]
    p  = 2.2*mm

    lbl_tb(tb_x+p, r0+8.5*mm, "PART NAME / TITLE")
    val_tb(tb_x+p, r0+2.5*mm, part_name[:28], 9, bold=True)

    lbl_tb(tb_x+p, r1+8*mm, "DRAWN BY")
    val_tb(tb_x+p, r1+2*mm, "Draft AI")
    lbl_tb(mx+p, r1+8*mm, "DATE")
    val_tb(mx+p, r1+2*mm, _dt.now().strftime("%d/%m/%Y"))

    lbl_tb(tb_x+p, r2+8*mm, "SCALE")
    val_tb(tb_x+p, r2+2*mm, "1:1")
    lbl_tb(mx+p, r2+8*mm, "SHEET")
    val_tb(mx+p, r2+2*mm, "1 OF 1")

    lbl_tb(tb_x+p, r3+8*mm, "BOUNDING BOX (X × Y × Z mm)")
    if dims and "error" not in dims:
        val_tb(tb_x+p, r3+2*mm,
               f"{dims.get('length','—')} × {dims.get('width','—')} × {dims.get('height','—')}", 7.5)

    lbl_tb(tb_x+p, tb_y+2*mm, "MATERIAL:  —       FINISH:  —       UNIT: mm       PROJECTION: 3rd ANGLE")

    # DWG number block above title block
    dwg_h = 11*mm
    c.setFillColorRGB(0.08, 0.08, 0.12)
    c.rect(tb_x, tb_y+tb_h, tb_w, dwg_h, fill=1, stroke=0)
    c.setStrokeColorRGB(0.25, 0.25, 0.25)
    c.setLineWidth(0.5)
    c.rect(tb_x, tb_y+tb_h, tb_w, dwg_h, fill=0, stroke=1)
    c.line(mx, tb_y+tb_h, mx, tb_y+tb_h+dwg_h)

    c.setFont("Helvetica", 5.5); c.setFillColorRGB(0.55, 0.55, 0.55)
    c.drawString(tb_x+p, tb_y+tb_h+7*mm, "DWG NUMBER")
    c.setFont("Helvetica-Bold", 8); c.setFillColorRGB(0.98, 0.98, 0.98)
    c.drawString(tb_x+p, tb_y+tb_h+2*mm, part_name[:18])
    c.setFont("Helvetica", 5.5); c.setFillColorRGB(0.55, 0.55, 0.55)
    c.drawString(mx+p, tb_y+tb_h+7*mm, "REV")
    c.setFont("Helvetica-Bold", 11); c.setFillColorRGB(0.976, 0.451, 0.086)
    c.drawString(mx+p, tb_y+tb_h+1.5*mm, "A")

    # ── View layout grid (third-angle projection standard) ────────────
    # Available area: left of title block, between fi+strip_h and fi
    avail_x0 = fi
    avail_y0 = fi
    avail_x1 = tb_x - 3*mm
    avail_y1 = strip_y - 2*mm
    avail_w  = avail_x1 - avail_x0
    avail_h  = avail_y1 - avail_y0
    hw       = avail_w / 2
    hh       = avail_h / 2

    # Standard third-angle:  TOP | ISO
    #                        FRONT | SIDE
    boxes = {
        "top":       (avail_x0,        avail_y0 + hh, hw - 1.5*mm, hh - 1.5*mm),
        "front":     (avail_x0,        avail_y0,      hw - 1.5*mm, hh - 1.5*mm),
        "side":      (avail_x0 + hw,   avail_y0,      hw - 1.5*mm, hh - 1.5*mm),
        "isometric": (avail_x0 + hw,   avail_y0 + hh, hw - 1.5*mm, hh - 1.5*mm),
    }
    vlabels = {
        "front":     "FRONT VIEW",
        "top":       "TOP VIEW",
        "side":      "SIDE VIEW  (RIGHT)",
        "isometric": "ISOMETRIC VIEW",
    }

    for vkey, (vx, vy, vw, vh) in boxes.items():
        # Cell background
        c.setFillColorRGB(0.99, 0.99, 0.99)
        c.rect(vx, vy, vw, vh, fill=1, stroke=0)
        # Cell border
        c.setStrokeColorRGB(0.7, 0.7, 0.75)
        c.setLineWidth(0.4)
        c.rect(vx, vy, vw, vh, fill=0, stroke=1)

        # View label strip at bottom of cell
        label_strip_h = 8.5*mm
        c.setFillColorRGB(0.94, 0.94, 0.96)
        c.rect(vx, vy, vw, label_strip_h, fill=1, stroke=0)
        c.setStrokeColorRGB(0.8, 0.8, 0.82)
        c.setLineWidth(0.3)
        c.line(vx, vy + label_strip_h, vx + vw, vy + label_strip_h)

        c.setFont("Helvetica-Bold", 7)
        c.setFillColorRGB(0.15, 0.15, 0.22)
        c.drawCentredString(vx + vw/2, vy + 3*mm, vlabels.get(vkey, vkey.upper()))

        # Dimension summary inside label strip
        if dims and "error" not in dims:
            L  = dims.get("length",  0)
            Wd = dims.get("width",   0)
            Ht = dims.get("height",  0)
            dim_str = {
                "front":     f"X = {L} mm    Z = {Ht} mm",
                "top":       f"X = {L} mm    Y = {Wd} mm",
                "side":      f"Y = {Wd} mm    Z = {Ht} mm",
                "isometric": f"X={L}  Y={Wd}  Z={Ht}  mm",
            }.get(vkey, "")
            c.setFont("Helvetica", 5.5)
            c.setFillColorRGB(0.976, 0.451, 0.086)
            c.drawCentredString(vx + vw/2, vy + label_strip_h - 3*mm, dim_str)

        # Place view image
        vdata = views.get(vkey, {})
        if vdata.get("png"):
            try:
                img   = Image.open(io.BytesIO(vdata["png"])).convert("RGB")
                iw, ih = img.size
                ip     = 8*mm
                avail_iw = vw - ip * 2
                avail_ih = vh - ip * 2 - label_strip_h
                scale   = min(avail_iw / iw, avail_ih / ih)
                nw      = iw * scale
                nh      = ih * scale
                ix      = vx + (vw - nw) / 2
                iy      = vy + label_strip_h + (avail_ih - nh) / 2 + ip * 0.5
                ibuf = io.BytesIO()
                img.save(ibuf, "PNG")
                ibuf.seek(0)
                c.drawImage(ImageReader(ibuf), ix, iy, nw, nh)
            except Exception:
                pass
        else:
            # "Not exported" placeholder
            c.setFont("Helvetica", 7)
            c.setFillColorRGB(0.6, 0.6, 0.6)
            c.drawCentredString(vx + vw/2, vy + vh/2, "—  not exported  —")

    # ── Divider lines (cross-hair between views) ──────────────────────
    c.setStrokeColorRGB(0.65, 0.65, 0.70)
    c.setLineWidth(0.25)
    c.setDash(4, 4)
    c.line(avail_x0, avail_y0 + hh, avail_x1, avail_y0 + hh)
    c.line(avail_x0 + hw, avail_y0, avail_x0 + hw, avail_y1)
    c.setDash()

    # ── Third-angle projection symbol ────────────────────────────────
    sym_x = avail_x0 + hw - 18*mm
    sym_y = avail_y0 + 10*mm
    r1, r2 = 6*mm, 2.5*mm
    c.setStrokeColorRGB(0.3, 0.3, 0.3)
    c.setLineWidth(0.5)
    c.circle(sym_x, sym_y, r1, fill=0, stroke=1)
    c.setFillColorRGB(0.3, 0.3, 0.3)
    c.circle(sym_x, sym_y, r2, fill=1, stroke=0)
    c.setFont("Helvetica", 5)
    c.setFillColorRGB(0.4, 0.4, 0.4)
    c.drawCentredString(sym_x, sym_y - r1 - 2*mm, "3rd ANGLE")

    c.save()
    return buf.getvalue()
