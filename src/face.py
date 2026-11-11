"""Tìm mặt (mắt, miệng, màu da) trên ảnh nhân vật cắt nền để vẽ khẩu hình và chớp mắt.

Thứ tự: Gemini nhìn ảnh (chính xác) -> dò mắt bằng điểm ảnh (dự phòng) -> ước lượng theo tỉ lệ.
Kết quả lưu cạnh ảnh: <ảnh>.face.json, toạ độ chuẩn hoá 0..1 theo kích thước ảnh.
"""
import base64
import json
import os
import re
from pathlib import Path

import numpy as np
import requests
from PIL import Image

API = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
PROMPT = """This is a cartoon character on a white background.
Locate its face parts as bounding boxes in the format [ymin, xmin, ymax, xmax] normalised to 0-1000.
Return ONLY JSON:
{"face": true or false,
 "face_box": [ymin, xmin, ymax, xmax],
 "left_eye_box": [...], "right_eye_box": [...],
 "mouth_box": [...],
 "mouth_open": true or false,
 "skin": "#rrggbb"}
"mouth_box" = the drawn mouth (or, if no mouth is drawn, where it should be). "mouth_open" = teeth/tongue or a wide
open mouth is visible. "skin" = face colour right next to the mouth.
If no face is visible (an object, a back view), return {"face": false}."""

_models = None
_fails = 0


def _gemini(path: Path) -> dict | None:
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not key:
        return None
    global _models
    if _models is None:
        from script_gen import available_models
        try:
            _models = available_models(key)[:3] or ["gemini-flash-latest"]
        except SystemExit:
            _models = []
    im = Image.open(path).convert("RGBA")
    bg = Image.new("RGBA", im.size, (255, 255, 255, 255))
    bg.alpha_composite(im)
    bg = bg.convert("RGB")
    bg.thumbnail((768, 768))
    tmp = path.with_suffix(".face.jpg")
    bg.save(tmp, "JPEG", quality=88)
    data = base64.b64encode(tmp.read_bytes()).decode()
    tmp.unlink(missing_ok=True)
    body = {"contents": [{"parts": [
        {"inline_data": {"mime_type": "image/jpeg", "data": data}},
        {"text": PROMPT.format(w=im.width, h=im.height)}]}],
        "generationConfig": {"responseMimeType": "application/json", "temperature": 0.1}}
    global _fails
    if _fails >= 8:  # Gemini hỏng liên tục: thôi, không nhép miệng (còn hơn vẽ sai chỗ)
        return None
    import time
    for m in _models[:2]:
        for attempt in range(4):
            try:
                r = requests.post(API.format(model=m), params={"key": key}, json=body, timeout=40)
                if r.status_code in (429, 500, 503):  # quá tải / hạn mức theo phút: chờ rồi thử lại
                    print(f"[face] {m}: HTTP {r.status_code}, chờ {12 * (attempt + 1)}s")
                    _fails += 1
                    time.sleep(12 * (attempt + 1))
                    continue
                if not r.ok:
                    print(f"[face] {m}: HTTP {r.status_code}")
                    _fails += 1
                    break
                text = r.json()["candidates"][0]["content"]["parts"][0]["text"]
                text = re.sub(r"//.*", "", text)
                _fails = 0
                return json.loads(text)
            except (requests.RequestException, KeyError, IndexError, ValueError) as e:
                print(f"[face] {m}: {e}")
                _fails += 1
                break
    return None


def _box(b):
    """[ymin, xmin, ymax, xmax] 0-1000 -> (x0, y0, x1, y1) 0-1."""
    try:
        y0, x0, y1, x1 = [float(v) for v in b]
    except (TypeError, ValueError):
        return None
    k = 1000.0 if max(y0, x0, y1, x1) > 1.5 else 1.0
    x0, x1 = sorted((x0 / k, x1 / k))
    y0, y1 = sorted((y0 / k, y1 / k))
    if not (0 <= x0 < x1 <= 1 and 0 <= y0 < y1 <= 1):
        return None
    return x0, y0, x1, y1


def from_gemini(info: dict, path: Path) -> dict | None:
    """Đổi kết quả Gemini sang dạng dùng để vẽ, và KIỂM TRA hợp lý; sai thì bỏ (không nhép miệng)."""
    if not info or not info.get("face"):
        return None
    face, mouth = _box(info.get("face_box")), _box(info.get("mouth_box"))
    eyes = [_box(info.get(k)) for k in ("left_eye_box", "right_eye_box")]
    if not face or not mouth:
        return None
    im = Image.open(path).convert("RGBA")
    W, H = im.size
    mx, my = (mouth[0] + mouth[2]) / 2, (mouth[1] + mouth[3]) / 2
    fx0, fy0, fx1, fy1 = face
    fw = fx1 - fx0
    # miệng phải nằm trong mặt, ở nửa dưới của mặt, và trên phần ảnh có hình (không phải nền trong suốt)
    if not (fx0 <= mx <= fx1 and fy0 + (fy1 - fy0) * 0.35 <= my <= fy1 + (fy1 - fy0) * 0.05):
        print(f"[face] {path.name}: miệng ngoài vùng mặt, bỏ nhép miệng")
        return None
    if im.getpixel((min(W - 1, int(mx * W)), min(H - 1, int(my * H))))[3] < 128:
        return None
    mw = mouth[2] - mouth[0]
    if not (0.12 * fw <= mw <= 0.8 * fw):
        mw = 0.3 * fw
    good_eyes = []
    for e in eyes:
        if e and e[3] < my and fx0 <= (e[0] + e[2]) / 2 <= fx1:
            good_eyes.append([(e[0] + e[2]) / 2, (e[1] + e[3]) / 2, max(e[2] - e[0], e[3] - e[1]) / 2 * 1.05])
    a = np.asarray(im).astype(np.float32)
    skin = info.get("skin") if re.fullmatch(r"#[0-9a-fA-F]{6}", str(info.get("skin", ""))) else None
    skin = _skin(a, a[..., 3] > 128, int(mx * W), int(my * H), int(mw * W)) or skin
    return {"face": True, "eyes": good_eyes if len(good_eyes) == 2 else [],
            "mouth": [mx, my], "mouth_width": mw * 1.1,
            "mouth_h": (mouth[3] - mouth[1]), "has_mouth": True,
            "mouth_open": bool(info.get("mouth_open")), "skin": skin, "source": "gemini"}


def _heuristic(path: Path) -> dict:
    """Dò 2 mắt = 2 đốm tối gần nhau ở nửa trên của nhân vật."""
    im = Image.open(path).convert("RGBA")
    a = np.asarray(im).astype(np.float32)
    alpha = a[..., 3] > 128
    ys, xs = np.nonzero(alpha)
    if len(xs) == 0:
        return {"face": False}
    x0, x1, y0, y1 = xs.min(), xs.max(), ys.min(), ys.max()
    W, H = im.size
    bw, bh = x1 - x0, y1 - y0
    lum = a[..., :3].mean(axis=2)
    # vùng đầu: 55% trên, bỏ viền sticker
    top = int(y0 + bh * 0.08), int(y0 + bh * 0.55)
    dark = (lum < 70) & alpha
    dark[: top[0]] = False
    dark[top[1]:] = False
    # loại viền ngoài: điểm tối sát nền trong suốt
    edge = np.zeros_like(alpha)
    k = max(4, int(min(W, H) * 0.02))
    for dy in (-k, 0, k):
        for dx in (-k, 0, k):
            edge |= ~np.roll(np.roll(alpha, dy, 0), dx, 1)
    dark &= ~edge
    blobs = _blobs(dark, min_px=max(12, int(bw * bw * 0.0004)))
    best = None
    for i in range(len(blobs)):
        for j in range(i + 1, len(blobs)):
            (ax, ay, an), (bx, by, bn) = blobs[i], blobs[j]
            d = abs(ax - bx)
            if d < bw * 0.08 or d > bw * 0.6 or abs(ay - by) > d * 0.35:
                continue
            if max(an, bn) > 4 * min(an, bn):
                continue
            score = an + bn - abs(ay - by) * 3
            if best is None or score > best[0]:
                best = (score, blobs[i], blobs[j])
    if best:
        (_, (ax, ay, an), (bx, by, bn)) = best
        if ax > bx:
            (ax, ay, an), (bx, by, bn) = (bx, by, bn), (ax, ay, an)
        d = bx - ax
        mx, my = (ax + bx) / 2, max(ay, by) + d * 0.62
        ra, rb = (an / np.pi) ** 0.5, (bn / np.pi) ** 0.5
        eyes = [[ax / W, ay / H, ra * 1.3 / W], [bx / W, by / H, rb * 1.3 / W]]
        mw = d * 0.55 / W
        src = "eyes"
    else:
        mx, my = (x0 + x1) / 2, y0 + bh * 0.3
        eyes, mw, src = [], bw * 0.18 / W, "guess"
    skin = _skin(a, alpha, int(mx), int(my), int(mw * W))
    return {"face": True, "eyes": eyes, "mouth": [mx / W, my / H], "mouth_width": mw,
            "has_mouth": True, "skin": skin, "source": src}


def _blobs(mask, min_px):
    """Các thành phần liên thông (x, y, số điểm) — BFS đơn giản trên lưới thu nhỏ."""
    h, w = mask.shape
    seen = np.zeros_like(mask)
    out = []
    pts = np.argwhere(mask)
    if len(pts) > 200000:
        return out
    for y, x in pts:
        if seen[y, x]:
            continue
        stack = [(y, x)]
        seen[y, x] = True
        sx = sy = n = 0
        while stack:
            cy, cx = stack.pop()
            sx += cx
            sy += cy
            n += 1
            for ny, nx in ((cy + 1, cx), (cy - 1, cx), (cy, cx + 1), (cy, cx - 1)):
                if 0 <= ny < h and 0 <= nx < w and mask[ny, nx] and not seen[ny, nx]:
                    seen[ny, nx] = True
                    stack.append((ny, nx))
        if n >= min_px:
            out.append((sx / n, sy / n, n))
    out.sort(key=lambda b: -b[2])
    return out[:12]


def _skin(a, alpha, x, y, r):
    r = max(6, r)
    h, w = alpha.shape
    ys, xs = slice(max(0, y - r), min(h, y + r)), slice(max(0, x - r * 2), min(w, x + r * 2))
    px = a[ys, xs][alpha[ys, xs]][:, :3]
    if len(px) == 0:
        return "#F2C9A0"
    px = px[px.mean(axis=1) > 80]  # bỏ nét viền / miệng tối
    if len(px) == 0:
        return "#F2C9A0"
    q = (px // 16).astype(int)
    codes = q[:, 0] * 256 + q[:, 1] * 16 + q[:, 2]
    top = np.bincount(codes).argmax()  # màu phổ biến nhất quanh miệng = màu da
    c = px[codes == top].mean(axis=0).astype(int)
    return "#%02X%02X%02X" % tuple(c)


def locate(path, override: dict | None = None, use_ai=True) -> dict:
    path = Path(path)
    cache = path.with_name(path.name + ".face.json")
    if override:
        return from_override(override, path)
    if cache.exists():
        try:
            return json.loads(cache.read_text())
        except ValueError:
            pass
    raw = _gemini(path) if use_ai else None
    info = from_gemini(raw, path)
    if info is None:
        # không chắc vị trí miệng thì KHÔNG vẽ miệng (vẽ lệch xấu hơn nhiều so với không nhép)
        if os.environ.get("FACE_HEURISTIC") == "1":
            info = _heuristic(path)
        else:
            info = {"face": False, "source": "none" if raw is None else "rejected"}
        if raw is None:
            return info  # lỗi mạng: không lưu cache để lần sau thử lại
    cache.write_text(json.dumps(info))
    return info


def from_override(ov: dict, path: Path) -> dict:
    """Vị trí mặt do Claude (hoặc người) ghi trong script.json: cast[i].faces.<base|expr>.
    Dạng: {"face": false} | {"mouth_box": [x0, y0, x1, y1], "eyes": [[x, y, r], [x, y, r]], "mouth_open": bool}
    (toạ độ 0..1 theo ảnh; x theo chiều ngang). Dạng cũ {"mouth": [x, y], "mouth_width": w} vẫn nhận."""
    if not ov.get("face", True):
        return {"face": False, "source": "claude"}
    info = {"face": True, "source": "claude", "has_mouth": ov.get("has_mouth", True),
            "mouth_open": bool(ov.get("mouth_open")), "eyes": ov.get("eyes") or []}
    mb = ov.get("mouth_box")
    if mb and len(mb) == 4:
        x0, y0, x1, y1 = [float(v) for v in mb]
        x0, x1 = sorted((x0, x1))
        y0, y1 = sorted((y0, y1))
        info["mouth"] = [(x0 + x1) / 2, (y0 + y1) / 2]
        info["mouth_width"] = max(0.02, (x1 - x0) * 1.1)
        info["mouth_h"] = y1 - y0
    elif ov.get("mouth"):
        info["mouth"] = [float(v) for v in ov["mouth"]][:2]
        info["mouth_width"] = float(ov.get("mouth_width", 0.12))
        info["mouth_h"] = float(ov.get("mouth_h", 0))
    elif len(info["eyes"]) == 2:  # chỉ có mắt (nhép miệng đã tắt): ước lượng chỗ miệng dưới hai mắt
        (x1, y1, r1), (x2, y2, r2) = [[float(v) for v in e[:3]] for e in info["eyes"]]
        d = max(0.02, abs(x2 - x1))
        info["mouth"] = [(x1 + x2) / 2, (y1 + y2) / 2 + d * 0.9]
        info["mouth_width"] = d * 0.5
        info["mouth_h"] = 0
    else:
        return {"face": False, "source": "claude"}
    im = Image.open(path).convert("RGBA")
    a = np.asarray(im).astype(np.float32)
    W, H = im.size
    info["skin"] = ov.get("skin") or _skin(a, a[..., 3] > 128, int(info["mouth"][0] * W),
                                           int(info["mouth"][1] * H), int(info["mouth_width"] * W))
    return info


def grid_sheet(path: Path, out: Path, info: dict | None, title: str):
    """Ảnh nhân vật trên nền trắng + lưới toạ độ 0.1 (để Claude đọc vị trí mắt/miệng chính xác),
    kèm khung đỏ = vị trí miệng hiện tại, xanh = mắt (nếu có)."""
    from PIL import ImageDraw, ImageFont
    im = Image.open(path).convert("RGBA")
    k = 760 / im.height
    im = im.resize((max(1, int(im.width * k)), 760), Image.LANCZOS)
    pad = 40
    W, H = im.width + pad * 2, im.height + pad * 2 + 30
    sheet = Image.new("RGB", (W, H), "white")
    sheet.paste(im, (pad, pad + 30), im)
    d = ImageDraw.Draw(sheet)
    try:
        f = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 13)
        fb = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 16)
    except OSError:
        f = fb = ImageFont.load_default()
    d.text((pad, 6), title, fill="black", font=fb)
    ox, oy, iw, ih = pad, pad + 30, im.width, im.height
    for i in range(11):
        v = i / 10
        x, y = ox + v * iw, oy + v * ih
        col = (120, 170, 255) if i % 5 else (40, 90, 220)
        d.line([(x, oy), (x, oy + ih)], fill=col, width=1)
        d.line([(ox, y), (ox + iw, y)], fill=col, width=1)
        d.text((x - 8, oy - 16), f"{v:.1f}", fill=(40, 90, 220), font=f)
        d.text((4, y - 7), f"{v:.1f}", fill=(40, 90, 220), font=f)
    if info and info.get("face") and info.get("mouth"):
        mx, my = info["mouth"]
        mw = info.get("mouth_width", 0.1) / 1.1
        mh = max(info.get("mouth_h", 0), 0.02)
        d.rectangle([ox + (mx - mw / 2) * iw, oy + (my - mh / 2) * ih, ox + (mx + mw / 2) * iw,
                     oy + (my + mh / 2) * ih], outline=(230, 30, 30), width=3)
        for e in info.get("eyes") or []:
            ex, ey, er = e
            d.ellipse([ox + (ex - er) * iw, oy + ey * ih - er * iw, ox + (ex + er) * iw, oy + ey * ih + er * iw],
                      outline=(30, 160, 60), width=3)
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out, "JPEG", quality=88)
    return out
