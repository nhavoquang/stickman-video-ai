"""Tạo diễn viên / đạo cụ dạng ảnh cắt nền (sticker) và sân khấu rộng bằng AI ảnh free.

- Diễn viên, đạo cụ: AI vẽ trên nền trắng → tự cắt nền (flood-fill từ mép ảnh) → viền trắng kiểu sticker.
- Sân khấu: ảnh phong cảnh rộng hơn khung hình để camera lướt / zoom trên đó.
Không mạng (offline) thì vẽ hình thay thế để vẫn test được toàn bộ quy trình.
"""
import hashlib
import math
import os
import random
import time
import urllib.parse
from pathlib import Path

import requests
from PIL import Image, ImageDraw, ImageFilter, ImageFont

URL = "https://image.pollinations.ai/prompt/{prompt}"
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
CUTOUT_SUFFIX = ("full body, single subject, centered, isolated on a plain pure white background, "
                 "no background scenery, no shadow, no text, no watermark")
STAGE_SUFFIX = ("wide establishing shot, detailed environment, no people, no characters, no text, "
                "no letters, no watermark, clean composition with open space in the middle")
LOGO_CROP = 0.11  # phần đáy ảnh (có logo) bị cắt bỏ


def _key(*parts):
    return hashlib.sha1("|".join(map(str, parts)).encode()).hexdigest()[:10]


def _fetch(prompt, w, h, seed, tag):
    params = {"width": w, "height": h, "nologo": "true", "seed": seed, "model": "flux",
              "enhance": "false", "safe": "true"}
    headers = {}
    token = os.environ.get("POLLINATIONS_TOKEN", "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    for attempt in range(6):
        try:
            r = requests.get(URL.format(prompt=urllib.parse.quote(prompt)), params=params,
                             headers=headers, timeout=180)
            if r.ok and r.headers.get("content-type", "").startswith("image"):
                from io import BytesIO
                print(f"[asset] {tag} OK")
                return Image.open(BytesIO(r.content)).convert("RGB")
            print(f"[asset] {tag} HTTP {r.status_code}, đợi rồi thử lại")
        except requests.RequestException as e:
            print(f"[asset] {tag} lỗi {e}, thử lại")
        time.sleep(12 * (attempt + 1))
    print(f"[asset] {tag}: dùng hình thay thế")
    return None


# ------------------------------------------------------------------ cắt nền ---

def remove_white_bg(img: Image.Image, tol=28) -> Image.Image:
    """Xoá nền trắng nối liền với mép ảnh, giữ nguyên phần trắng bên trong nhân vật."""
    img = img.convert("RGB")
    w, h = img.size
    px = img.load()
    # ảnh nhị phân: 255 = gần trắng
    mask = Image.new("L", (w, h), 0)
    mp = mask.load()
    thr = 255 - tol
    for y in range(h):
        for x in range(w):
            r, g, b = px[x, y]
            if r > thr and g > thr and b > thr:
                mp[x, y] = 255
    # loang từ mép: vùng trắng chạm mép → 128 (nền)
    for x in range(0, w, 8):
        for y in (0, h - 1):
            if mp[x, y] == 255:
                ImageDraw.floodfill(mask, (x, y), 128)
    for y in range(0, h, 8):
        for x in (0, w - 1):
            if mp[x, y] == 255:
                ImageDraw.floodfill(mask, (x, y), 128)
    alpha = mask.point(lambda v: 0 if v == 128 else 255)
    alpha = alpha.filter(ImageFilter.MinFilter(3)).filter(ImageFilter.GaussianBlur(0.8))
    out = img.convert("RGBA")
    out.putalpha(alpha)
    return out


def sticker(img: Image.Image, border=10) -> Image.Image:
    """Cắt sát, thêm viền trắng + viền tối mảnh để nổi trên mọi nền."""
    bbox = img.getchannel("A").point(lambda v: 255 if v > 40 else 0).getbbox()
    if bbox:
        img = img.crop(bbox)
    pad = border * 2 + 4
    w, h = img.size
    canvas = Image.new("RGBA", (w + pad * 2, h + pad * 2), (0, 0, 0, 0))
    canvas.paste(img, (pad, pad), img)
    a = canvas.getchannel("A").point(lambda v: 255 if v > 60 else 0)
    white = a.filter(ImageFilter.MaxFilter(border * 2 + 1))
    dark = white.filter(ImageFilter.MaxFilter(5))
    base = Image.new("RGBA", canvas.size, (30, 30, 30, 0))
    base.putalpha(dark.point(lambda v: int(v * 0.55)))
    wl = Image.new("RGBA", canvas.size, (255, 255, 255, 0))
    wl.putalpha(white)
    base.alpha_composite(wl)
    base.alpha_composite(canvas)
    return base


# ------------------------------------------------------------------ tạo tài nguyên ---

def make_cutout(prompt: str, style: str, out_dir: Path, kind="actor", offline=False, label="") -> Path:
    full = f"{style}. {prompt}. {CUTOUT_SUFFIX}"
    key = _key(full, kind)
    out = out_dir / f"{kind}_{key}.png"
    if out.exists():
        return out
    img = None if offline else _fetch(full, 1024, 1024, int(key[:6], 16), out.name)
    if img is not None:
        # cắt dải đáy có logo trước khi tách nền
        w, h = img.size
        img = img.crop((0, 0, w, int(h * (1 - LOGO_CROP))))
        cut = remove_white_bg(img)
        # nếu tách nền thất bại (gần như không còn gì hoặc còn nguyên) thì vẫn dùng, chỉ bo góc
        cov = sum(1 for v in cut.getchannel("A").resize((64, 64)).getdata() if v > 128) / 4096
        if cov < 0.03 or cov > 0.97:
            cut = img.convert("RGBA")
        res = sticker(cut)
    else:
        res = _placeholder(kind, label or prompt, key)
    res.thumbnail((900, 900))
    res.save(out)
    return out


def make_stage(prompt: str, style: str, out_dir: Path, size, offline=False) -> Path:
    """Sân khấu rộng gấp ~1.5 lần khung hình để camera di chuyển."""
    fw, fh = size
    sw, sh = int(fw * 1.5), int(fh * 1.5)
    full = f"{style}. {prompt}. {STAGE_SUFFIX}"
    key = _key(full, sw, sh)
    out = out_dir / f"stage_{key}.jpg"
    if out.exists():
        return out
    # API ảnh free giới hạn cỡ ~2048: xin ảnh nhỏ hơn cùng tỉ lệ rồi phóng to
    k = min(1.0, 2048 / max(sw, sh))
    rw, rh = int(sw * k) // 16 * 16, int(sh * k * (1 + LOGO_CROP)) // 16 * 16
    img = None if offline else _fetch(full, rw, rh, int(key[:6], 16), out.name)
    if img is not None:
        w, h = img.size
        img = img.crop((0, 0, w, int(h / (1 + LOGO_CROP))))
        img = img.resize((sw, sh), Image.LANCZOS)
    else:
        img = _placeholder_stage((sw, sh), key)
    img.save(out, "JPEG", quality=92)
    return out


def _placeholder(kind, label, key):
    rnd = random.Random(key)
    if kind == "actor":
        import cairo
        from character import draw_character, pose_at
        s = cairo.ImageSurface(cairo.FORMAT_ARGB32, 520, 760)
        c = cairo.Context(s)
        expr = "surprised" if "shock" in label or "surpris" in label else "happy"
        draw_character(c, pose_at(rnd.choice(["wave", "talk", "point", "idle"]), 0.4), 260, 740, 1.0,
                       "shirt", {"expression": expr, "mouth": 0.3})
        img = Image.frombuffer("RGBA", (520, 760), bytes(s.get_data()), "raw", "BGRA", 0, 1)
        return sticker(img)
    col = tuple(rnd.randint(60, 230) for _ in range(3))
    img = Image.new("RGBA", (360, 360), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([20, 20, 340, 340], 60, fill=col + (255,), outline=(20, 20, 20, 255), width=8)
    try:
        f = ImageFont.truetype(FONT, 40)
    except OSError:
        f = ImageFont.load_default()
    d.text((180, 180), label[:12], fill="white", font=f, anchor="mm", stroke_width=3, stroke_fill="black")
    return sticker(img)


def _placeholder_stage(size, key):
    rnd = random.Random(key)
    w, h = size
    top = tuple(rnd.randint(150, 230) for _ in range(3))
    bot = tuple(max(0, c - 60) for c in top)
    img = Image.new("RGB", size)
    d = ImageDraw.Draw(img)
    for y in range(h):
        k = y / h
        d.line([(0, y), (w, y)], fill=tuple(int(a + (b - a) * k) for a, b in zip(top, bot)))
    for _ in range(40):
        x, y, r = rnd.randint(0, w), rnd.randint(0, h), rnd.randint(30, 180)
        c = tuple(min(255, v + rnd.randint(-40, 40)) for v in top)
        d.ellipse([x - r, y - r, x + r, y + r], fill=c)
    for i in range(0, w, 240):  # lưới để thấy rõ camera di chuyển
        d.line([(i, 0), (i, h)], fill=(255, 255, 255), width=2)
    for j in range(0, h, 240):
        d.line([(0, j), (w, j)], fill=(255, 255, 255), width=2)
    return img.filter(ImageFilter.GaussianBlur(2))
