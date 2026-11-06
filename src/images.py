"""Bước 2a: tạo ảnh NỀN (không có người) bằng Pollinations (free).

- Logo "pollinations.ai" ở góc dưới bị loại bỏ: ảnh được tạo cao hơn rồi cắt bỏ phần đáy.
  Nếu có POLLINATIONS_TOKEN (đăng ký free tại https://auth.pollinations.ai) thì xin ảnh không logo luôn.
- Nhân vật KHÔNG lấy từ AI mà được vẽ bằng code (character.py) để luôn giống nhau và chuyển động được.
"""
import os
import random
import time
import urllib.parse
from pathlib import Path

import requests
from PIL import Image, ImageDraw, ImageFilter, ImageFont

STYLE_PROMPTS = {
    "doodle": ("clean hand-drawn doodle illustration, black ink outlines on warm white paper, "
               "a few soft pastel color accents, minimalist explainer video background, "
               "simple shapes, flat, lots of empty space, no people, no characters, no text. Scene: "),
    "shirt": ("modern flat vector illustration background, soft pastel colors, clean simple shapes, "
              "minimal explainer video style, gentle gradients, lots of empty space, "
              "no people, no characters, no text, no letters. Scene: "),
}
URL = "https://image.pollinations.ai/prompt/{prompt}"
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
W, H = 1920, 1080
CROP = 140  # phần đáy bị cắt bỏ (chứa logo)


def generate_background(prompt: str, out: Path, seed: int, style: str = "doodle", offline: bool = False) -> Path:
    if not offline:
        full = STYLE_PROMPTS.get(style, STYLE_PROMPTS["doodle"]) + prompt
        params = {"width": W, "height": H + CROP, "nologo": "true", "seed": seed,
                  "model": "flux", "enhance": "false", "safe": "true"}
        headers = {}
        token = os.environ.get("POLLINATIONS_TOKEN", "").strip()
        if token:
            headers["Authorization"] = f"Bearer {token}"
        for attempt in range(6):
            try:
                r = requests.get(URL.format(prompt=urllib.parse.quote(full)), params=params,
                                 headers=headers, timeout=180)
                if r.ok and r.headers.get("content-type", "").startswith("image"):
                    out.write_bytes(r.content)
                    _finish(out)
                    print(f"[image] {out.name} OK")
                    return out
                print(f"[image] {out.name} HTTP {r.status_code}, đợi rồi thử lại")
            except requests.RequestException as e:
                print(f"[image] {out.name} lỗi {e}, thử lại")
            # free không cần key bị giới hạn ~1 ảnh mỗi vài giây
            time.sleep(12 * (attempt + 1))
        print(f"[image] {out.name}: dùng nền dự phòng")
    _fallback(out, seed, style)
    return out


def _finish(path: Path):
    """Cắt bỏ dải đáy có logo, đưa về đúng 1920x1080, làm dịu nền để nhân vật nổi bật."""
    img = Image.open(path).convert("RGB")
    w, h = img.size
    cut = int(h * CROP / (H + CROP)) + 4
    img = img.crop((0, 0, w, h - cut))
    # cắt về tỷ lệ 16:9
    tw, th = img.size
    if tw / th > W / H:
        nw = int(th * W / H)
        img = img.crop(((tw - nw) // 2, 0, (tw - nw) // 2 + nw, th))
    else:
        nh = int(tw * H / W)
        img = img.crop((0, 0, tw, nh))
    img = img.resize((W, H), Image.LANCZOS)
    # làm nhạt 18% để nhân vật và chữ nổi trên nền
    img = Image.blend(img, Image.new("RGB", img.size, (255, 255, 255)), 0.18)
    img.save(path, "PNG")


def _fallback(out: Path, seed: int, style: str):
    """Nền dự phòng: giấy trắng/pastel với vài hình trang trí."""
    rnd = random.Random(seed)
    base = (252, 250, 244) if style == "doodle" else rnd.choice([(232, 244, 255), (255, 240, 232), (236, 250, 238)])
    img = Image.new("RGB", (W, H), base)
    d = ImageDraw.Draw(img)
    for _ in range(14):
        x, y, r = rnd.randint(0, W), rnd.randint(0, H), rnd.randint(30, 140)
        col = tuple(max(0, c - rnd.randint(8, 25)) for c in base)
        d.ellipse([x - r, y - r, x + r, y + r], fill=col)
    d.rectangle([0, 1000, W, H], fill=tuple(max(0, c - 18) for c in base))
    img = img.filter(ImageFilter.GaussianBlur(6))
    img.save(out, "PNG")


def make_thumbnail(frame: Path, title: str, out: Path) -> Path:
    img = Image.open(frame).convert("RGB").resize((1280, 720))
    d = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype(FONT, 76)
    except OSError:
        font = ImageFont.load_default()
    words, lines, cur = title.upper().split(), [], ""
    for wd in words:
        test = (cur + " " + wd).strip()
        if d.textlength(test, font=font) > 700 and cur:
            lines.append(cur)
            cur = wd
        else:
            cur = test
    lines.append(cur)
    y = 60
    for line in lines[:5]:
        d.text((560, y), line, font=font, fill="#FFD400", stroke_width=7, stroke_fill="black")
        y += 92
    img.save(out, "JPEG", quality=92)
    return out
