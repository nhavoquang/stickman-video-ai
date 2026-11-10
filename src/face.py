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
PROMPT = """This is a cartoon character on a transparent background (image {w}x{h} px).
Find its face. Return ONLY JSON:
{{"face": true/false,
  "eyes": [[x, y, r], [x, y, r]],      // eye centres and radius, normalised 0-1 (x by width, y by height, r by width)
  "mouth": [x, y],                     // centre of the mouth, or where the mouth should be if it has none
  "mouth_width": w,                    // natural mouth width, fraction of image width
  "has_mouth": true/false,             // is a mouth drawn?
  "skin": "#rrggbb"}}                  // face colour just around the mouth
If there is no visible face (object, back view), return {{"face": false}}."""

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
    if _fails >= 3:  # Gemini đang quá tải/hết hạn mức: dùng cách dò điểm ảnh cho nhanh
        return None
    for m in _models[:2]:
        try:
            r = requests.post(API.format(model=m), params={"key": key}, json=body, timeout=25)
            if not r.ok:
                print(f"[face] {m}: HTTP {r.status_code}")
                _fails += 1
                if r.status_code == 429:
                    _fails = max(_fails, 3)
                    return None
                continue
            text = r.json()["candidates"][0]["content"]["parts"][0]["text"]
            text = re.sub(r"//.*", "", text)
            return json.loads(text)
        except (requests.RequestException, KeyError, IndexError, ValueError) as e:
            print(f"[face] {m}: {e}")
            _fails += 1
    return None


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
        return override
    if cache.exists():
        try:
            return json.loads(cache.read_text())
        except ValueError:
            pass
    info = _gemini(path) if use_ai else None
    if info and info.get("face") and info.get("mouth"):
        info["source"] = "gemini"
        if not info.get("skin"):
            info["skin"] = _heuristic(path).get("skin", "#F2C9A0")
    elif info and info.get("face") is False:
        info = {"face": False, "source": "gemini"}
    else:
        info = _heuristic(path)
    cache.write_text(json.dumps(info))
    return info
