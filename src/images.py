"""Bước 2a: tạo ảnh người que bằng Pollinations (free, không cần key).
Nếu dịch vụ lỗi, tự vẽ một ảnh người que đơn giản để video vẫn ra được."""
import random
import time
import urllib.parse
from pathlib import Path

import requests
from PIL import Image, ImageDraw, ImageFont

STYLE = (
    "simple hand-drawn stick figure cartoon, thick black lines on plain white background, "
    "minimalist doodle explainer video style, flat, clean, no text, 16:9. Scene: "
)
URL = "https://image.pollinations.ai/prompt/{prompt}"
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"


def generate_image(prompt: str, out: Path, seed: int, offline: bool = False) -> Path:
    if not offline:
        url = URL.format(prompt=urllib.parse.quote(STYLE + prompt))
        params = {"width": 1920, "height": 1080, "nologo": "true", "seed": seed, "model": "flux"}
        for attempt in range(4):
            try:
                r = requests.get(url, params=params, timeout=180)
                if r.ok and r.headers.get("content-type", "").startswith("image"):
                    out.write_bytes(r.content)
                    Image.open(out).convert("RGB").save(out, "PNG")
                    print(f"[image] {out.name} OK")
                    return out
                print(f"[image] {out.name} HTTP {r.status_code}, thử lại")
            except requests.RequestException as e:
                print(f"[image] {out.name} lỗi {e}, thử lại")
            time.sleep(8 * (attempt + 1))
        print(f"[image] {out.name}: dùng ảnh vẽ dự phòng")
    _draw_fallback(prompt, out, seed)
    return out


def _draw_fallback(prompt: str, out: Path, seed: int) -> None:
    rnd = random.Random(seed)
    img = Image.new("RGB", (1920, 1080), "white")
    d = ImageDraw.Draw(img)
    cx, top = 960 + rnd.randint(-300, 300), 300
    w = 12
    d.ellipse([cx - 70, top - 140, cx + 70, top], outline="black", width=w)
    d.line([cx, top, cx, top + 300], fill="black", width=w)
    arm = rnd.choice([-120, 0, 120])
    d.line([cx, top + 80, cx - 160, top + 80 + arm], fill="black", width=w)
    d.line([cx, top + 80, cx + 160, top + 80 - arm], fill="black", width=w)
    d.line([cx, top + 300, cx - 110, top + 520], fill="black", width=w)
    d.line([cx, top + 300, cx + 110, top + 520], fill="black", width=w)
    try:
        font = ImageFont.truetype(FONT, 34)
    except OSError:
        font = ImageFont.load_default()
    d.text((60, 980), prompt[:110], fill=(150, 150, 150), font=font)
    img.save(out, "PNG")


def make_thumbnail(image: Path, title: str, out: Path) -> Path:
    img = Image.open(image).convert("RGB").resize((1280, 720))
    d = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype(FONT, 72)
    except OSError:
        font = ImageFont.load_default()
    # Ngắt dòng tiêu đề, tối đa 3 dòng, chữ vàng viền đen.
    words, lines, cur = title.upper().split(), [], ""
    for wd in words:
        test = (cur + " " + wd).strip()
        if d.textlength(test, font=font) > 1180 and cur:
            lines.append(cur)
            cur = wd
        else:
            cur = test
    lines.append(cur)
    y = 720 - 40 - 85 * len(lines[:3])
    for line in lines[:3]:
        d.text((50, y), line, font=font, fill="#FFD400", stroke_width=6, stroke_fill="black")
        y += 85
    img.save(out, "JPEG", quality=92)
    return out
