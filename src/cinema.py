"""Kiểu dựng "cinema": mỗi góc máy là một ảnh AI trọn cảnh (nhân vật nằm trong cảnh), cắt góc máy mỗi
1,5–3 giây, máy quay chỉ trôi nhẹ, KHÔNG có hiệu ứng đè lên hình; phụ đề trắng 1–2 chữ nhỏ.
Học từ Short "The Instinct That Makes You Crash" (xem prompts/cinema_spec.md)."""
import json
import math
import re
import subprocess
import zlib
from pathlib import Path

import cairo
from PIL import Image, ImageFilter

import scene_video as SV
from assets import LOGO_CROP, _fetch, _key, _placeholder_stage

ROOT = Path(__file__).resolve().parent.parent
SPEC = (ROOT / "prompts" / "cinema_spec.md").read_text(encoding="utf-8")
FPS = 30
OVER = 1.12          # ảnh lớn hơn khung 12 % để máy quay có chỗ trôi
DRIFT = 0.06         # biên độ trôi của một góc máy (~6 %)
LEAD = 2 / FPS       # hình đổi trước chữ 2 khung
MAX_SHOT = 3.5       # giữ một ảnh quá lâu → nhắc ở báo cáo
CAMS = ("push_in", "pull_out", "pan_left", "pan_right", "tilt_up", "tilt_down", "static")
QUALITY = ("masterpiece, highly detailed 3D animated movie frame, cinematic composition, sharp focus, "
           "high resolution, no watermark, no subtitles, no UI, no borders")


# ------------------------------------------------------------------ kịch bản ---

def build_prompt(topic, plan, notes=""):
    shots = max(3, round(plan["duration"] / 2.2))
    return f"""{SPEC}

---
TASK
Topic: "{topic}"
Language of title/description/tags/narration/sign text: {plan['language']}
Aspect ratio: {plan['aspect']} ({'vertical Shorts: compose for a tall frame' if plan['vertical'] else 'horizontal frame'})
Target length: about {plan['duration']} seconds → exactly {plan['scenes']} scenes (one per sentence or two),
about {plan['words_per_scene_latin']} words each, and about {shots} shots in total.
Extra requests from the user: {notes or 'none'}
Content must be factually correct and specific. Spell out symbols (%, /, &) as words.
Return only the JSON."""


def clean(film):
    film.setdefault("title", "Video")
    film.setdefault("description", "")
    film.setdefault("tags", [])
    film.setdefault("music", "chill")
    film.setdefault("art_style", "stylized 3D animated film still, soft global illumination, realistic soft "
                                 "shadows, rich detailed environment, saturated natural colors, cinematic lighting")
    chars = []
    for c in film.get("characters", []) or []:
        if c.get("id") and c.get("look"):
            chars.append({"id": str(c["id"]), "look": str(c["look"]).strip()})
    film["characters"] = chars
    scenes = []
    for sc in film.get("scenes", []) or []:
        nar = str(sc.get("narration", "")).strip()
        if not nar:
            continue
        n = len(nar.split())
        shots = []
        for sh in sc.get("shots", []) or []:
            pr = str(sh.get("prompt", "")).strip()
            if not pr:
                continue
            try:
                at = max(0.0, min(n - 0.01, float(sh.get("at", 0))))
            except (TypeError, ValueError):
                at = 0.0
            cam = sh.get("camera") if sh.get("camera") in CAMS else "push_in"
            shots.append({"at": at, "camera": cam, "prompt": pr,
                          "characters": [x for x in sh.get("characters", []) or [] if isinstance(x, str)]})
        if not shots:  # cảnh thiếu góc máy: lặp góc trước
            if not scenes:
                continue
            last = scenes[-1]["shots"][-1]
            shots = [dict(last, at=0.0, camera="static")]
        shots.sort(key=lambda s: s["at"])
        shots[0]["at"] = 0.0
        scenes.append({"narration": nar, "shots": shots})
    if not scenes:
        raise ValueError("Kịch bản không có cảnh nào")
    film["scenes"] = scenes
    th = film.get("thumbnail") if isinstance(film.get("thumbnail"), dict) else {}
    film["thumbnail"] = th
    return film


def generate(topic, plan, model="auto", notes=""):
    import motion_script
    return motion_script.generate(topic, plan, model, notes, prompt=build_prompt(topic, plan, notes),
                                  cleaner=clean)


def full_prompt(film, shot):
    looks = {c["id"]: c["look"] for c in film["characters"]}
    pr = re.sub(r"\{(\w+)\}", lambda m: looks.get(m.group(1), m.group(1)), shot["prompt"])
    return f"{film['art_style']}. {pr}. {QUALITY}"


# ------------------------------------------------------------------ ảnh ---

def make_shot(prompt, out_dir: Path, size, offline=False) -> Path:
    fw, fh = size
    sw, sh = int(fw * OVER), int(fh * OVER)
    key = _key(prompt, sw, sh, "cinema")
    out = out_dir / f"shot_{key}.jpg"
    if out.exists():
        return out
    k = min(1.0, 1536 / max(sw, sh))
    rw, rh = int(sw * k) // 16 * 16, int(sh * k * (1 + LOGO_CROP)) // 16 * 16
    img = None if offline else _fetch(prompt, rw, rh, int(key[:6], 16), out.name)
    if img is not None:
        w, h = img.size
        img = img.crop((0, 0, w, int(h / (1 + LOGO_CROP))))
        if img.size != (sw, sh):
            kk = sw / img.size[0]
            img = img.resize((sw, sh), Image.LANCZOS)
            if kk > 1.05:
                img = img.filter(ImageFilter.UnsharpMask(radius=1.4 * kk, percent=60, threshold=2))
    else:
        img = _placeholder_stage((sw, sh), key)
    img.save(out, "JPEG", quality=94)
    return out


def shot_list(film):
    """[(cảnh, góc máy, dict góc máy)] theo thứ tự."""
    return [(i, j, sh) for i, sc in enumerate(film["scenes"]) for j, sh in enumerate(sc["shots"])]


# ------------------------------------------------------------------ dựng ---

def timeline(film, timings):
    """Danh sách góc máy với thời điểm bắt đầu/kết thúc + danh sách từ (start, end, word)."""
    cuts, words = [], []
    off = 0.0
    for sc, (dur, wt) in zip(film["scenes"], timings):
        ws = sc["narration"].split()
        for w, (a, b) in zip(ws, wt):
            words.append((off + a, off + b, w))
        for j, sh in enumerate(sc["shots"]):
            wi = int(sh["at"])
            t = off + (wt[wi][0] if wi < len(wt) else 0) - (LEAD if (j or off) else 0)
            cuts.append([max(0.0, t), sh])
        off += dur
    total = off
    out = []
    for k, (t, sh) in enumerate(cuts):
        end = cuts[k + 1][0] if k + 1 < len(cuts) else total
        if end - t > 0.05:
            out.append((t, end, sh))
    return out, words, total


def _view(cam, p, iw, ih, W, H):
    """Ma trận camera: trả (scale, cx, cy) — tâm ảnh nhìn vào và độ phóng, p 0→1 tốc độ đều."""
    base = max(W / iw, H / ih)
    z, dx, dy = 1.0, 0.0, 0.0
    if cam == "push_in":
        z = 1 + DRIFT * p
    elif cam == "pull_out":
        z = 1 + DRIFT * (1 - p)
    elif cam == "static":
        z = 1 + 0.015 * p
    else:
        z = 1.03
        s = (p - 0.5) * 2  # -1 → 1
        if cam == "pan_left":
            dx = -s
        elif cam == "pan_right":
            dx = s
        elif cam == "tilt_up":
            dy = -s
        else:
            dy = s
    sc = base * z
    vis_w, vis_h = W / sc, H / sc
    mx, my = (iw - vis_w) / 2, (ih - vis_h) / 2
    return sc, iw / 2 + dx * mx * 0.9, ih / 2 + dy * my * 0.9


def _ease(p):
    # gần như tốc độ đều (như flycam), chỉ mềm ở 2 đầu một chút
    return 0.85 * p + 0.15 * p * p * (3 - 2 * p)


def caption_groups(words, vertical):
    out, cur = [], []
    for i, (a, b, w) in enumerate(words):
        cur.append((a, b, w))
        if len(cur) >= 2 or sum(len(x[2]) for x in cur) > 9 or w[-1:] in ",.!?;:…":
            out.append(cur)
            cur = []
    if cur:
        out.append(cur)
    g = []
    for i, grp in enumerate(out):
        end = out[i + 1][0][0] if i + 1 < len(out) else grp[-1][1] + 0.4
        g.append((grp[0][0], min(end, grp[-1][1] + 0.5), " ".join(x[2] for x in grp)))
    return g


def _caption(ctx, text, W, H, font):
    vertical = H > W
    fs = (64 if vertical else 50) * (W / 1080 if vertical else H / 1080)
    ctx.save()
    ctx.select_font_face(font, cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
    ctx.set_font_size(fs)
    ext = ctx.text_extents(text)
    k = min(1.0, W * 0.86 / max(ext.x_advance, 1))
    ctx.set_font_size(fs * k)
    ext = ctx.text_extents(text)
    x = W / 2 - ext.x_advance / 2
    y = H * (0.70 if vertical else 0.86)
    ctx.move_to(x, y)
    ctx.text_path(text)
    ctx.set_line_join(cairo.LINE_JOIN_ROUND)
    ctx.set_source_rgba(0, 0, 0, 0.85)
    ctx.set_line_width(fs * k * 0.16)
    ctx.stroke_preserve()
    ctx.set_source_rgb(1, 1, 1)
    ctx.fill()
    ctx.restore()


def render(film, timings, shot_paths, voice_wav, out_mp4, cwd, subtitles=True, qa_dir=None,
           preview_dir=None, preview_only=False):
    from motion import mix_audio, to_surface
    W, H = SV.W, SV.H
    cuts, words, total = timeline(film, timings)
    groups = caption_groups(words, H > W) if subtitles else []
    fams = subprocess.run(["fc-list", ":", "family"], capture_output=True, text=True).stdout
    font = next((f"{SV.FONT} {w}" for w in ("ExtraBold", "Bold") if f"{SV.FONT} {w}" in fams), SV.FONT)
    surfs = {}

    def surf_for(sh):
        p = shot_paths[id(sh)]
        if p not in surfs:
            surfs.clear() if len(surfs) > 6 else None
            surfs[p] = to_surface(p)
        return surfs[p]

    surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, W, H)

    def draw(t):
        ctx = cairo.Context(surf)
        ctx.set_source_rgb(0, 0, 0)
        ctx.paint()
        c = next((c for c in cuts if c[0] <= t < c[1]), cuts[-1])
        s = surf_for(c[2])
        iw, ih = s.get_width(), s.get_height()
        p = _ease(min(1.0, max(0.0, (t - c[0]) / max(c[1] - c[0], 0.1))))
        sc, cx, cy = _view(c[2]["camera"], p, iw, ih, W, H)
        ctx.save()
        ctx.translate(W / 2, H / 2)
        ctx.scale(sc, sc)
        ctx.translate(-cx, -cy)
        ctx.set_source_surface(s, 0, 0)
        ctx.get_source().set_filter(cairo.FILTER_GOOD)
        ctx.paint()
        ctx.restore()
        g = next((g for g in groups if g[0] - 0.03 <= t < g[1]), None)
        if g:
            _caption(ctx, g[2], W, H, font)
        surf.flush()

    if preview_dir:
        Path(preview_dir).mkdir(parents=True, exist_ok=True)
        files = []
        for k, (a, b, _sh) in enumerate(cuts):
            draw((a + b) / 2)
            f = Path(preview_dir) / f"shot_{k + 1:02d}.png"
            surf.write_to_png(str(f))
            files.append(f)
        if preview_only:
            return files

    work = Path(cwd)
    silent = work / "sfx_silent.wav"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                    "anullsrc=r=48000:cl=stereo", "-t", f"{total:.2f}", str(silent)], check=True)
    music = None
    if film.get("music", "chill") != "none":
        import music as MUSIC
        music = work / "music.wav"
        mseed = zlib.crc32((str(film.get("title", "")) + str(film.get("topic", ""))).encode()) % 100000
        MUSIC.build(total, music, film.get("music", "chill"), seed=mseed, downbeat_at=0.0)
    mix_wav = mix_audio(voice_wav, silent, music, work / "mix.wav")
    nframes = int(total * FPS)
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "bgra",
           "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-", "-i", str(Path(mix_wav).resolve()),
           "-map", "0:v", "-map", "1:a", "-c:v", "libx264", "-preset", "medium", "-crf", "18",
           "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "256k", "-shortest", "-movflags", "+faststart",
           str(Path(out_mp4).resolve())]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    for fi in range(nframes):
        draw(fi / FPS)
        proc.stdin.write(bytes(surf.get_data()))
        if fi % (FPS * 10) == 0:
            print(f"[cinema] {fi / FPS:.0f}/{total:.0f}s")
    proc.stdin.close()
    if proc.wait() != 0:
        raise SystemExit("ffmpeg lỗi khi dựng video")
    if qa_dir:
        try:
            import qa
            planned = [[int(a * FPS) - 1, int(a * FPS) + 1] for a, _b, _s in cuts]
            planned += [[int(g[0] * FPS) - 1, int(g[0] * FPS) + 1] for g in groups]
            planned += [[int(g[1] * FPS) - 1, int(g[1] * FPS) + 1] for g in groups]
            lines, _warn = qa.check(out_mp4, qa_dir, planned)
            print("[qa] " + "\n[qa] ".join(lines))
        except Exception as e:
            print(f"[qa] bỏ qua: {e}")
    return out_mp4


def report(film, timings):
    cuts, _w, total = timeline(film, timings)
    lens = [round(b - a, 2) for a, b, _ in cuts]
    return {"total_seconds": round(total, 1), "shots": len(cuts),
            "avg_shot_seconds": round(total / max(1, len(cuts)), 2),
            "too_long_shots": [i + 1 for i, d in enumerate(lens) if d > MAX_SHOT],
            "shot_seconds": lens}


def cover_crop(path, size, out):
    im = Image.open(path).convert("RGB")
    tw, th = size
    k = max(tw / im.width, th / im.height)
    im = im.resize((math.ceil(im.width * k), math.ceil(im.height * k)), Image.LANCZOS)
    x, y = (im.width - tw) // 2, (im.height - th) // 3
    im.crop((x, y, x + tw, y + th)).save(out, "JPEG", quality=93)
    return out


def dump(film, path):
    Path(path).write_text(json.dumps(film, ensure_ascii=False, indent=2), encoding="utf-8")
