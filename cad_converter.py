"""
Draft AI — 3D to 2D CAD Converter
Communicates with the DraftAI SolidWorks Add-in via HTTP on localhost:7432
"""

import os, io, json, base64
from pathlib import Path

def convert_to_2d_style(png_bytes: bytes) -> bytes:
    """Convert 3D shaded PNG to clean 2D engineering line drawing."""
    try:
        from PIL import Image, ImageOps, ImageFilter, ImageEnhance
        img   = Image.open(io.BytesIO(png_bytes)).convert("L")
        edges = img.filter(ImageFilter.FIND_EDGES)
        edges = ImageEnhance.Contrast(edges).enhance(5.0)
        edges = ImageOps.invert(edges)
        edges = edges.point(lambda x: 255 if x > 180 else 0)
        out   = io.BytesIO()
        edges.convert("RGB").save(out, format="PNG")
        return out.getvalue()
    except Exception:
        return png_bytes

ADDIN_URL  = "http://localhost:7432"
OUTPUT_DIR = os.path.join(os.path.expanduser("~"), "DraftAI_Output")


def is_addin_running() -> bool:
    try:
        import urllib.request
        with urllib.request.urlopen(f"{ADDIN_URL}/ping", timeout=2) as r:
            return json.loads(r.read()).get("status") == "ok"
    except Exception:
        return False


def prepare_and_export(file_bytes: bytes, filename: str) -> dict:
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    file_path = os.path.join(OUTPUT_DIR, filename)
    with open(file_path, "wb") as f:
        f.write(file_bytes)
    for fn in ["status.json","dimensions.json","front.png","top.png","side.png","isometric.png"]:
        fp = os.path.join(OUTPUT_DIR, fn)
        if os.path.exists(fp): os.remove(fp)

    import urllib.request
    payload = json.dumps({"file_path": file_path, "output_dir": OUTPUT_DIR}).encode()
    req = urllib.request.Request(f"{ADDIN_URL}/export", data=payload,
                                  headers={"Content-Type":"application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=120) as r:
        result = json.loads(r.read())
    if not result.get("success"):
        raise RuntimeError(result.get("error","Export failed"))
    return load_results(OUTPUT_DIR)


def load_results(output_dir: str = None) -> dict:
    if output_dir is None: output_dir = OUTPUT_DIR
    sf = os.path.join(output_dir, "status.json")
    if not os.path.exists(sf):
        return {"ready": False, "reason": "No results yet — run the add-in first"}
    try:
        status = json.loads(open(sf).read())
        if not status.get("completed"):
            return {"ready": False, "reason": "Export did not complete"}
    except Exception:
        return {"ready": False, "reason": "Could not read status.json"}

    dims = {}
    df = os.path.join(output_dir, "dimensions.json")
    if os.path.exists(df): dims = json.loads(open(df).read())

    view_labels = {"front":"Front View","top":"Top View","side":"Side View","isometric":"Isometric View"}
    views = {}
    for vkey, vlabel in view_labels.items():
        pp = os.path.join(output_dir, f"{vkey}.png")
        if os.path.exists(pp):
            png = open(pp,"rb").read()
            png = convert_to_2d_style(png)
            if dims: png = annotate_with_dims(png, dims, vkey)
            views[vkey] = {"png":png,"svg":None,"label":vlabel}
        else:
            views[vkey] = {"png":None,"svg":None,"label":vlabel,"error":"Not exported"}

    return {
        "ready":True,"views":views,"dimensions":dims,
        "pdf":generate_pdf(views, Path(status.get("file","drawing")).name, dims),
        "filename":Path(status.get("file","drawing")).name,
        "backend":"SolidWorks Add-in ✓","output_dir":output_dir,
    }


def annotate_with_dims(png_bytes: bytes, dims: dict, view_key: str) -> bytes:
    try:
        from PIL import Image, ImageDraw, ImageFont
        img = Image.open(io.BytesIO(png_bytes)).convert("RGBA")
        ov  = Image.new("RGBA", img.size, (0,0,0,0))
        draw = ImageDraw.Draw(ov)
        W, H = img.size
        orange=(249,115,22,240); dimline=(249,115,22,180); bg=(13,13,13,210); white=(255,255,255,220)
        try: fnt=ImageFont.truetype("arial.ttf",16); fntS=ImageFont.truetype("arial.ttf",13)
        except: fnt=fntS=ImageFont.load_default()

        gray=img.convert("L"); px=gray.load()
        x0,y0,x1,y1=W,H,0,0
        for py in range(H):
            for px2 in range(W):
                if px[px2,py]<235:
                    x0=min(x0,px2);x1=max(x1,px2);y0=min(y0,py);y1=max(y1,py)
        if x1<=x0 or y1<=y0: x0,y0,x1,y1=W//6,H//6,5*W//6,5*H//6

        def hdim(xa,xb,yy,txt,gap=30):
            yl=yy+gap
            draw.line([(xa,yy-4),(xa,yl+4)],fill=dimline,width=1)
            draw.line([(xb,yy-4),(xb,yl+4)],fill=dimline,width=1)
            draw.line([(xa,yl),(xb,yl)],fill=dimline,width=2)
            aw=12
            draw.polygon([(xa,yl),(xa+aw,yl-5),(xa+aw,yl+5)],fill=orange)
            draw.polygon([(xb,yl),(xb-aw,yl-5),(xb-aw,yl+5)],fill=orange)
            mx=(xa+xb)//2; bb=draw.textbbox((0,0),txt,font=fnt); tw,th=bb[2]-bb[0],bb[3]-bb[1]
            draw.rectangle([mx-tw//2-6,yl-th-6,mx+tw//2+6,yl+4],fill=bg)
            draw.text((mx-tw//2,yl-th-3),txt,fill=orange,font=fnt)

        def vdim(ya,yb,xx,txt,gap=36):
            xl=xx-gap
            draw.line([(xx-4,ya),(xl-4,ya)],fill=dimline,width=1)
            draw.line([(xx-4,yb),(xl-4,yb)],fill=dimline,width=1)
            draw.line([(xl,ya),(xl,yb)],fill=dimline,width=2)
            ah=12
            draw.polygon([(xl,ya),(xl-5,ya+ah),(xl+5,ya+ah)],fill=orange)
            draw.polygon([(xl,yb),(xl-5,yb-ah),(xl+5,yb-ah)],fill=orange)
            my=(ya+yb)//2; bb=draw.textbbox((0,0),txt,font=fnt); tw,th=bb[2]-bb[0],bb[3]-bb[1]
            draw.rectangle([xl-tw-10,my-th//2-4,xl-1,my+th//2+4],fill=bg)
            draw.text((xl-tw-6,my-th//2),txt,fill=orange,font=fnt)

        L=dims.get("length",0); Wd=dims.get("width",0); Ht=dims.get("height",0)
        if view_key=="front":     hdim(x0,x1,y1,f"X = {L} mm"); vdim(y0,y1,x0,f"Z = {Ht} mm")
        elif view_key=="top":     hdim(x0,x1,y1,f"X = {L} mm"); vdim(y0,y1,x0,f"Y = {Wd} mm")
        elif view_key=="side":    hdim(x0,x1,y1,f"Y = {Wd} mm"); vdim(y0,y1,x0,f"Z = {Ht} mm")
        elif view_key=="isometric":
            infos=[f"X = {L} mm",f"Y = {Wd} mm",f"Z = {Ht} mm"]; ix,iy=14,14
            for info in infos:
                bb=draw.textbbox((0,0),info,font=fnt); tw,th=bb[2]-bb[0],bb[3]-bb[1]
                draw.rectangle([ix-4,iy-3,ix+tw+4,iy+th+3],fill=bg); draw.text((ix,iy),info,fill=orange,font=fnt); iy+=th+10

        lbl={"front":"FRONT","top":"TOP","side":"SIDE","isometric":"ISO"}.get(view_key,view_key.upper())
        bb=draw.textbbox((0,0),lbl,font=fntS); tw,th=bb[2]-bb[0],bb[3]-bb[1]
        draw.rectangle([W-tw-14,6,W-4,th+14],fill=bg); draw.text((W-tw-9,9),lbl,fill=white,font=fntS)
        combined=Image.alpha_composite(img,ov).convert("RGB"); out=io.BytesIO(); combined.save(out,format="PNG"); return out.getvalue()
    except Exception: return png_bytes


def generate_pdf(views: dict, filename: str, dims: dict = None) -> bytes:
    """Generate a professional A3 engineering drawing sheet."""
    from reportlab.pdfgen import canvas as rl_canvas
    from reportlab.lib.pagesizes import A3, landscape as rl_landscape
    from reportlab.lib.units import mm
    from reportlab.lib.utils import ImageReader
    from PIL import Image
    from datetime import datetime as _dt

    buf = io.BytesIO()
    W, H = rl_landscape(A3)
    c = rl_canvas.Canvas(buf, pagesize=rl_landscape(A3))

    # Background — cream
    c.setFillColorRGB(0.957, 0.949, 0.918)
    c.rect(0, 0, W, H, fill=1, stroke=0)

    # Outer border
    c.setStrokeColorRGB(0, 0, 0)
    c.setLineWidth(2.5)
    c.rect(5*mm, 5*mm, W-10*mm, H-10*mm, fill=0, stroke=1)

    # Inner frame
    c.setLineWidth(0.6)
    fi = 10*mm
    c.rect(fi, fi, W-2*fi, H-2*fi, fill=0, stroke=1)

    part_name = filename.replace(".STEP","").replace(".step","").replace(".stp","").replace(".SLDPRT","")

    # ── Title block ──────────────────────────────────────────────────────
    tb_w, tb_h = 100*mm, 50*mm
    tb_x = W - fi - tb_w
    tb_y = fi
    c.setFillColorRGB(1,1,1)
    c.rect(tb_x, tb_y, tb_w, tb_h, fill=1, stroke=0)
    c.setStrokeColorRGB(0,0,0)
    c.setLineWidth(0.8)
    c.rect(tb_x, tb_y, tb_w, tb_h, fill=0, stroke=1)

    # Row lines
    row_hs = [tb_h*0.78, tb_h*0.56, tb_h*0.34, tb_h*0.12]
    for rh in row_hs:
        c.setLineWidth(0.4)
        c.line(tb_x, tb_y+rh, tb_x+tb_w, tb_y+rh)
    # Mid vertical
    mx = tb_x + tb_w*0.5
    c.line(mx, tb_y, mx, tb_y+row_hs[0])

    def lbl(x, y, t, sz=5.5):
        c.setFont("Helvetica", sz); c.setFillColorRGB(0.45,0.45,0.45); c.drawString(x,y,t)
    def val(x, y, t, sz=8.5, bold=False):
        c.setFont("Helvetica-Bold" if bold else "Helvetica", sz); c.setFillColorRGB(0,0,0); c.drawString(x,y,t)

    r0 = tb_y+row_hs[0]; r1 = tb_y+row_hs[1]; r2 = tb_y+row_hs[2]; r3 = tb_y+row_hs[3]
    lbl(tb_x+2*mm, r0+8*mm, "PART NAME / TITLE")
    val(tb_x+2*mm, r0+2*mm, part_name[:26], 9, bold=True)
    lbl(tb_x+2*mm, r1+8*mm, "DRAWN BY")
    val(tb_x+2*mm, r1+2*mm, "Draft AI")
    lbl(mx+2*mm, r1+8*mm, "DATE")
    val(mx+2*mm, r1+2*mm, _dt.now().strftime("%d/%m/%Y"))
    lbl(tb_x+2*mm, r2+8*mm, "SCALE")
    val(tb_x+2*mm, r2+2*mm, "1:1")
    lbl(mx+2*mm, r2+8*mm, "SHEET")
    val(mx+2*mm, r2+2*mm, "1 OF 1")
    if dims and "error" not in dims:
        lbl(tb_x+2*mm, r3+8*mm, "BOUNDING BOX (X x Y x Z)")
        val(tb_x+2*mm, r3+2*mm,
            f"{dims.get('length','—')} x {dims.get('width','—')} x {dims.get('height','—')} mm", 7)
    lbl(tb_x+2*mm, tb_y+2*mm, "MATERIAL: —       FINISH: —       UNIT: mm")

    # DWG No box above title block
    c.setFillColorRGB(1,1,1)
    c.rect(tb_x, tb_y+tb_h, tb_w, 12*mm, fill=1, stroke=0)
    c.setStrokeColorRGB(0,0,0); c.setLineWidth(0.5)
    c.rect(tb_x, tb_y+tb_h, tb_w, 12*mm, fill=0, stroke=1)
    c.line(mx, tb_y+tb_h, mx, tb_y+tb_h+12*mm)
    lbl(tb_x+2*mm, tb_y+tb_h+7*mm, "DWG NUMBER")
    val(tb_x+2*mm, tb_y+tb_h+2*mm, part_name[:16], 8)
    lbl(mx+2*mm, tb_y+tb_h+7*mm, "REVISION")
    val(mx+2*mm, tb_y+tb_h+2*mm, "A", 10, bold=True)

    # ── View layout ───────────────────────────────────────────────────────
    dx1, dy1 = fi, fi
    dx2, dy2 = tb_x - 4*mm, H - fi
    dw = dx2 - dx1
    dh = dy2 - dy1
    hw = dw / 2
    hh = dh / 2

    boxes = {
        "top":       (dx1,      dy1+hh, hw-2*mm, hh-2*mm),
        "front":     (dx1,      dy1,    hw-2*mm, hh-2*mm),
        "side":      (dx1+hw,   dy1,    hw-2*mm, hh-2*mm),
        "isometric": (dx1+hw,   dy1+hh, hw-2*mm, hh-2*mm),
    }
    vlabels = {"front":"FRONT VIEW","top":"TOP VIEW","side":"SIDE VIEW","isometric":"ISOMETRIC VIEW"}

    for vkey, (vx, vy, vw, vh) in boxes.items():
        # Light view border
        c.setStrokeColorRGB(0.7,0.7,0.7); c.setLineWidth(0.3)
        c.rect(vx, vy, vw, vh, fill=0, stroke=1)

        vdata = views.get(vkey, {})
        if vdata.get("png"):
            try:
                img = Image.open(io.BytesIO(vdata["png"])).convert("RGB")
                iw, ih = img.size
                ip = 8*mm; label_h = 10*mm
                avail_w = vw - ip*2
                avail_h = vh - ip*2 - label_h
                ratio = min(avail_w / (iw * mm/mm), avail_h / (ih * mm/mm),
                            avail_w / iw * 2.8346,  avail_h / ih * 2.8346)
                # pts per px at 96dpi = 72/96 = 0.75
                nw_pt = iw * 0.75
                nh_pt = ih * 0.75
                scale = min(avail_w / nw_pt, avail_h / nh_pt)
                nw_pt *= scale; nh_pt *= scale
                px_pt = vx + (vw - nw_pt)/2
                py_pt = vy + label_h + (avail_h - nh_pt)/2 + ip
                ibuf = io.BytesIO(); img.save(ibuf, "PNG"); ibuf.seek(0)
                c.drawImage(ImageReader(ibuf), px_pt, py_pt, nw_pt, nh_pt)
            except Exception:
                pass

        # Label
        c.setFont("Helvetica", 7); c.setFillColorRGB(0.15,0.15,0.15)
        c.drawCentredString(vx+vw/2, vy+3*mm, vlabels.get(vkey, vkey.upper()))

        # Dim text top of each view
        if dims and "error" not in dims:
            L=dims.get("length",0); Wd=dims.get("width",0); Ht=dims.get("height",0)
            dim_str = {"front":f"X={L}  Z={Ht} mm","top":f"X={L}  Y={Wd} mm",
                       "side":f"Y={Wd}  Z={Ht} mm","isometric":f"X={L} Y={Wd} Z={Ht} mm"}.get(vkey,"")
            c.setFont("Helvetica",6); c.setFillColorRGB(0.3,0.3,0.3)
            c.drawCentredString(vx+vw/2, vy+vh-5*mm, dim_str)

    # Centre lines
    c.setStrokeColorRGB(0.65,0.65,0.65); c.setLineWidth(0.25); c.setDash(5,4)
    c.line(dx1, dy1+hh, dx2, dy1+hh)
    c.line(dx1+hw, dy1, dx1+hw, dy2)
    c.setDash()

    c.save()
    return buf.getvalue()