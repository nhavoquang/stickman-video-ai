"""Đóng gói đầu ra để đăng YouTube: video, thumbnail thiết kế riêng, tiêu đề, mô tả, tags.

Thư mục <out>/youtube/:
  video.mp4, thumbnail.jpg (1280x720), title.txt, description.txt, tags.txt, metadata.json
"""
import json
import math
import shutil
import subprocess
from pathlib import Path

import cairo
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

TW, TH = 1280, 720


def heavy_font(font_path: str) -> str:
    """Bản đậm nhất của font (Black/ExtraBold) nếu máy có, để chữ thumbnail thật dày."""
    fam = subprocess.run(["fc-query", "-f", "%{family[0]}", font_path], capture_output=True,
                         text=True).stdout.strip()
    for w in ("black", "extrabold", "bold"):
        p = subprocess.run(["fc-match", "-f", "%{file}", f"{fam}:{w}"], capture_output=True,
                           text=True).stdout.strip()
        if p and Path(p).exists() and (fam.split()[0].lower() in Path(p).name.lower() or w == "bold"):
            return p
    return font_path


def _cover(img: Image.Image, size) -> Image.Image:
    w, h = size
    k = max(w / img.width, h / img.height)
    img = img.resize((int(img.width * k) + 1, int(img.height * k) + 1), Image.LANCZOS)
    x, y = (img.width - w) // 2, (img.height - h) // 2
    return img.crop((x, y, x + w, y + h))


def _cutout_with_face(path: Path, expr: str) -> Image.Image:
    """Ảnh nhân vật + miệng theo biểu cảm (vẽ giống trong video)."""
    import face as FACE
    import motion
    im = Image.open(path).convert("RGBA")
    try:
        fc = FACE.locate(path)
    except Exception:
        fc = None
    if not fc or not fc.get("face"):
        return im
    surf = cairo.ImageSurface.create_from_png(str(path))
    ctx = cairo.Context(surf)
    talk = 1.0 if motion._mood(expr) in ("o", "grin") else 0.0
    word = "ô" if motion._mood(expr) == "o" else "a"
    motion.draw_face(ctx, fc, surf.get_width(), surf.get_height(), 10.0, 0.0, talk, word, expr)
    surf.flush()
    out = Image.frombuffer("RGBA", (surf.get_width(), surf.get_height()), bytes(surf.get_data()),
                           "raw", "BGRA", 0, 1).copy()
    return out


def _glow(im: Image.Image, color=(255, 255, 255), r=10) -> Image.Image:
    a = im.getchannel("A").filter(ImageFilter.MaxFilter(r * 2 + 1)).filter(ImageFilter.GaussianBlur(r / 2))
    base = Image.new("RGBA", im.size, color + (0,))
    base.putalpha(a)
    base.alpha_composite(im)
    return base


def _wrap(draw, text, font, max_w, no_space):
    tokens, sep = (list(text), "") if no_space else (text.split(), " ")
    lines, cur = [], ""
    for t in tokens:
        test = (cur + sep + t).strip() if sep else cur + t
        if draw.textlength(test, font=font) > max_w and cur:
            lines.append(cur)
            cur = t
        else:
            cur = test
    lines.append(cur)
    return lines


def design_thumbnail(film: dict, assets: dict, out: Path, font_path: str, no_space=False,
                     fallback_frame: Path | None = None) -> Path:
    th = film.get("thumbnail") or {}
    cast_ids = [c["id"] for c in film.get("cast", [])]
    stage = th.get("stage") or (film.get("stages") or [{}])[0].get("id")
    cid = th.get("cast") if th.get("cast") in cast_ids else (cast_ids[0] if cast_ids else None)
    expr = th.get("expr") or ""
    text = (th.get("text") or film.get("title", "")).strip().upper()

    # nền: sân khấu (hoặc khung hình video), tăng màu, tối dần bên trái để chữ nổi
    src = assets.get(f"stage:{stage}") or fallback_frame
    bg = Image.open(src).convert("RGB") if src else Image.new("RGB", (TW, TH), (40, 60, 120))
    bg = _cover(bg, (TW, TH)).filter(ImageFilter.GaussianBlur(2.5))
    bg = ImageEnhance.Color(bg).enhance(1.35)
    bg = ImageEnhance.Contrast(bg).enhance(1.1).convert("RGBA")
    shade = Image.new("L", (TW, TH))
    sd = ImageDraw.Draw(shade)
    for x in range(TW):
        sd.line([(x, 0), (x, TH)], fill=int(170 * max(0.0, 1 - x / (TW * 0.62)) ** 1.3))
    dark = Image.new("RGBA", (TW, TH), (12, 10, 24, 0))
    dark.putalpha(shade)
    bg.alpha_composite(dark)

    # tia sáng phía sau nhân vật
    rays = Image.new("RGBA", (TW, TH), (0, 0, 0, 0))
    rd = ImageDraw.Draw(rays)
    cx, cy = int(TW * 0.74), int(TH * 0.55)
    for i in range(18):
        a0 = i * 2 * math.pi / 18
        a1 = a0 + math.pi / 18
        rd.polygon([(cx, cy), (cx + 1600 * math.cos(a0), cy + 1600 * math.sin(a0)),
                    (cx + 1600 * math.cos(a1), cy + 1600 * math.sin(a1))], fill=(255, 220, 90, 46))
    bg.alpha_composite(rays.filter(ImageFilter.GaussianBlur(3)))

    # đạo cụ
    pid = th.get("prop")
    if pid and pid in assets:
        pr = Image.open(assets[pid]).convert("RGBA")
        k = TH * 0.36 / pr.height
        pr = pr.resize((max(1, int(pr.width * k)), max(1, int(pr.height * k))), Image.LANCZOS)
        pr = _glow(pr, (255, 255, 255), 6).rotate(-8, expand=True, resample=Image.BICUBIC)
        bg.alpha_composite(pr, (int(TW * 0.50), int(TH * 0.95 - pr.height)))

    # nhân vật lớn bên phải, tràn xuống đáy
    if cid:
        key = f"{cid}:{expr}" if f"{cid}:{expr}" in assets else cid
        if key in assets:
            ch = _cutout_with_face(Path(assets[key]), expr if ":" in key else "")
            bb = ch.getchannel("A").getbbox()
            if bb:
                ch = ch.crop(bb)
            k = TH * 1.02 / ch.height
            ch = ch.resize((max(1, int(ch.width * k)), max(1, int(ch.height * k))), Image.LANCZOS)
            ch = _glow(ch, (255, 255, 255), 9)
            sh = Image.new("RGBA", ch.size, (0, 0, 0, 0))
            sh.putalpha(ch.getchannel("A").point(lambda v: v * 0.45))
            sh = sh.filter(ImageFilter.GaussianBlur(14))
            x = int(TW * 0.76 - ch.width / 2)
            x = min(x, TW - int(ch.width * 0.85))
            bg.alpha_composite(sh, (x + 14, int(TH * 0.06) + 14))
            bg.alpha_composite(ch, (x, int(TH * 0.06)))

    # chữ: 2-3 dòng rất to, trắng/vàng xen kẽ, viền đen dày, nghiêng nhẹ
    layer = Image.new("RGBA", (TW, TH), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    fp = heavy_font(font_path)
    max_w = TW * 0.56
    fs = 170
    while fs > 60:
        font = ImageFont.truetype(fp, fs)
        lines = _wrap(d, text, font, max_w, no_space)
        if len(lines) <= 3 and fs * 1.08 * len(lines) < TH * 0.8:
            break
        fs -= 8
    lh = int(fs * 1.06)
    y = int((TH - lh * len(lines)) / 2) - 10
    for i, ln in enumerate(lines):
        col = "#FFFFFF" if i % 2 == 0 else "#FFD400"
        d.text((52 + 6, y + 8), ln, font=font, fill=(0, 0, 0, 150), stroke_width=int(fs * 0.09),
               stroke_fill=(0, 0, 0, 150))
        d.text((52, y), ln, font=font, fill=col, stroke_width=int(fs * 0.085), stroke_fill="#111111")
        y += lh
    layer = layer.rotate(3, resample=Image.BICUBIC, center=(TW * 0.3, TH / 2))
    bg.alpha_composite(layer)
    bg.convert("RGB").save(out, "JPEG", quality=90)
    return out


def description_text(film: dict, vertical: bool) -> str:
    desc = str(film.get("description", "")).strip()
    tags = film.get("hashtags") or ["#" + t.replace(" ", "") for t in film.get("tags", [])[:3]]
    if vertical and "#Shorts" not in tags:
        tags = ["#Shorts"] + tags
    return (desc + "\n\n" + " ".join(tags)).strip()[:4900]


def tags_list(film: dict) -> list:
    out, total = [], 0
    for t in film.get("tags", []):
        t = str(t).strip().replace("<", "").replace(">", "")
        if t and total + len(t) + 1 <= 480:
            out.append(t)
            total += len(t) + 1
    return out


def package(out_dir: Path, film: dict, video: Path, thumb: Path, vertical: bool, lang: str,
            settings: dict | None = None) -> Path:
    yt = out_dir / "youtube"
    yt.mkdir(parents=True, exist_ok=True)
    shutil.copy(video, yt / "video.mp4")
    shutil.copy(thumb, yt / "thumbnail.jpg")
    title = str(film.get("title", "Video")).strip()[:100]
    desc = description_text(film, vertical)
    tags = tags_list(film)
    (yt / "title.txt").write_text(title, encoding="utf-8")
    (yt / "description.txt").write_text(desc, encoding="utf-8")
    (yt / "tags.txt").write_text(", ".join(tags), encoding="utf-8")
    meta = {"title": title, "description": desc, "tags": tags, "language": lang,
            "categoryId": "27", "shorts": vertical, "settings": settings or {}}
    (yt / "metadata.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return yt
