"""Ảnh mẫu phong cách: AI xem ảnh rồi viết mô tả phong cách để mọi ảnh của video vẽ giống như vậy.

--style-ref nhận: tên thư mục trong style_refs/ (vd "chibi"), đường dẫn ảnh/thư mục, hoặc link ảnh,
cách nhau bởi dấu cách hoặc dấu phẩy. Kết quả lưu ở <out>/style_ref.json (và ảnh ở <out>/style_ref/).
"""
import base64
import hashlib
import json
import os
import re
from pathlib import Path

import requests
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
EXT = {".jpg", ".jpeg", ".png", ".webp"}
API = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
PROMPT = """These are reference images that define the visual style of an animated YouTube video.
Describe that style so an AI image generator can make NEW images (characters, objects, backgrounds) that look
like they come from the same artist/show. Do NOT name any artist, studio, brand or franchise.
Return ONLY JSON:
{"art_style": "one dense paragraph, max 70 words: medium (2D flat vector / cel-shaded / watercolor / 3D clay...),
   line work (thickness, colour), shading, colour palette & saturation, character proportions (head-to-body ratio),
   face/eyes style, texture, background treatment",
 "character": "if a main character appears: its look in max 40 words (species/body, hair, clothes, colours,
   accessories), front view; otherwise null",
 "palette": ["#rrggbb", "... 4-6 main colours"],
 "mood": "2-4 words"}"""


def collect(spec: str, out_dir: Path) -> list:
    """Danh sách ảnh (đã tải về nếu là link), tối đa 6."""
    files = []
    d = out_dir / "style_ref"
    for tok in re.split(r"[\s,]+", (spec or "").strip()):
        if not tok:
            continue
        if tok.startswith(("http://", "https://")):
            d.mkdir(parents=True, exist_ok=True)
            f = d / ("ref_" + hashlib.sha1(tok.encode()).hexdigest()[:10] + ".img")
            if not f.exists():
                try:
                    r = requests.get(tok, timeout=60, headers={"User-Agent": "Mozilla/5.0"})
                    r.raise_for_status()
                    f.write_bytes(r.content)
                except requests.RequestException as e:
                    print(f"[style-ref] không tải được {tok}: {e}")
                    continue
            files.append(f)
            continue
        p = Path(tok)
        for cand in (p, ROOT / "style_refs" / tok, ROOT / tok):
            if cand.is_dir():
                files += sorted(x for x in cand.iterdir() if x.suffix.lower() in EXT)
                break
            if cand.is_file():
                files.append(cand)
                break
        else:
            print(f"[style-ref] không tìm thấy: {tok}")
    ok = []
    for f in files:
        try:
            with Image.open(f) as im:
                im.verify()
            ok.append(f)
        except Exception:
            print(f"[style-ref] bỏ qua file không phải ảnh: {f}")
    return ok[:6]


def _jpeg_b64(path: Path) -> str:
    im = Image.open(path).convert("RGB")
    im.thumbnail((768, 768))
    from io import BytesIO
    buf = BytesIO()
    im.save(buf, "JPEG", quality=85)
    return base64.b64encode(buf.getvalue()).decode()


def analyze(spec: str, out_dir: Path, offline=False) -> dict | None:
    files = collect(spec, out_dir)
    if not files:
        return None
    sig = hashlib.sha1(b"".join(f.read_bytes()[:65536] for f in files)).hexdigest()[:12]
    cache = out_dir / "style_ref.json"
    if cache.exists():
        try:
            c = json.loads(cache.read_text(encoding="utf-8"))
            if c.get("sig") == sig:
                return c
        except ValueError:
            pass
    info = None if offline else _gemini(files)
    if not info:
        info = {"art_style": "", "character": None, "palette": _palette(files), "mood": ""}
    info["sig"] = sig
    info["images"] = [str(f) for f in files]
    cache.write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[style-ref] {len(files)} ảnh mẫu -> {info.get('art_style', '')[:160]}")
    return info


def _gemini(files) -> dict | None:
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not key:
        return None
    from script_gen import available_models
    try:
        models = available_models(key)[:3] or ["gemini-flash-latest"]
    except SystemExit:
        return None
    parts = [{"inline_data": {"mime_type": "image/jpeg", "data": _jpeg_b64(f)}} for f in files]
    parts.append({"text": PROMPT})
    body = {"contents": [{"parts": parts}],
            "generationConfig": {"responseMimeType": "application/json", "temperature": 0.2}}
    for m in models:
        for attempt in range(2):
            try:
                r = requests.post(API.format(model=m), params={"key": key}, json=body, timeout=90)
                if r.status_code in (429, 500, 503):
                    print(f"[style-ref] {m}: HTTP {r.status_code}, thử lại")
                    import time
                    time.sleep(10)
                    continue
                if not r.ok:
                    print(f"[style-ref] {m}: HTTP {r.status_code}")
                    break
                data = json.loads(r.json()["candidates"][0]["content"]["parts"][0]["text"])
                if data.get("art_style"):
                    return data
            except (requests.RequestException, KeyError, IndexError, ValueError) as e:
                print(f"[style-ref] {m}: {e}")
                break
    return None


def _palette(files, n=5):
    """Dự phòng khi không gọi được AI: lấy màu chủ đạo của ảnh mẫu."""
    im = Image.new("RGB", (64 * len(files), 64))
    for i, f in enumerate(files):
        im.paste(Image.open(f).convert("RGB").resize((64, 64)), (64 * i, 0))
    q = im.quantize(n)
    pal = q.getpalette()[: n * 3]
    return ["#%02X%02X%02X" % tuple(pal[i:i + 3]) for i in range(0, len(pal), 3)]


def notes_for_script(info: dict) -> str:
    """Thêm vào yêu cầu cho AI viết kịch bản."""
    s = (f"VISUAL STYLE IS FIXED by the user's reference images. Use exactly this as \"art_style\": "
         f"\"{info.get('art_style', '')}\".")
    if info.get("character"):
        s += (f" The main cast member (first in \"cast\") MUST look like this reference character: "
              f"\"{info['character']}\" — copy this description into its prompt.")
    return s


def apply(film: dict, info: dict):
    """Áp phong cách mẫu vào kịch bản (trừ khi Claude đã tự viết theo ảnh mẫu)."""
    if not info or film.get("style_ref_applied"):
        return film
    if info.get("art_style"):
        film["art_style"] = info["art_style"]
    elif info.get("palette"):
        film["art_style"] = film.get("art_style", "") + ", colour palette " + " ".join(info["palette"])
    film["style_ref_applied"] = True
    return film


if __name__ == "__main__":  # python src/style_ref.py "<style_ref>" output
    import sys
    res = analyze(sys.argv[1], Path(sys.argv[2] if len(sys.argv) > 2 else "output"))
    print(json.dumps(res, ensure_ascii=False, indent=2) if res else "Không có ảnh mẫu hợp lệ")
