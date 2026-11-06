"""Dựng toàn bộ video: nền AI + nhân vật vector chuyển động + chữ nổi + nhép miệng theo giọng.

Mỗi frame được vẽ bằng cairo rồi đẩy thẳng vào ffmpeg.
"""
import math
import subprocess
from array import array
from pathlib import Path

import cairo

from character import Blinker, blend, draw_character, pose_at

W, H, FPS = 1920, 1080, 30
GROUND = 935
XFADE = 0.45  # thời gian chuyển cảnh (giây)
FONT = "DejaVu Sans"
NO_SPACE_LANGS = {"zh", "ja", "th"}
LANG = "vi"

# Bố cục cho từng tỉ lệ khung hình
LAYOUTS = {
    "16:9": dict(size=(1920, 1080), ground=935, scale=1.25, char_x=(470, 1450), card=((1290, 360), (630, 360)),
                 card_w=760, font=70, thumb=(1280, 720), still=(430, 1.55, 60)),
    "9:16": dict(size=(1080, 1920), ground=1560, scale=1.55, char_x=(540, 540), card=((540, 430), (540, 430)),
                 card_w=820, font=78, thumb=(720, 1280), still=(540, 1.45, 260)),
    "1:1": dict(size=(1080, 1080), ground=950, scale=1.0, char_x=(290, 790), card=((730, 300), (350, 300)),
                card_w=520, font=58, thumb=(1080, 1080), still=(300, 1.25, 40)),
}
L = LAYOUTS["16:9"]


def configure(aspect="16:9", lang="vi", font="DejaVu Sans"):
    """Đặt tỉ lệ khung hình, ngôn ngữ và font cho toàn bộ module."""
    global W, H, GROUND, L, LANG, FONT
    L = LAYOUTS.get(aspect, LAYOUTS["16:9"])
    W, H = L["size"]
    GROUND = L["ground"]
    LANG, FONT = lang, font


def tokens(text):
    """Tách chữ để xuống dòng; tiếng Trung/Nhật/Thái không có dấu cách nên tách theo ký tự."""
    if LANG in NO_SPACE_LANGS:
        return list(text), ""
    return text.split(), " "


def _ease_out_back(t):
    c1, c3 = 1.70158, 2.70158
    return 1 + c3 * (t - 1) ** 3 + c1 * (t - 1) ** 2


def _ease(t):
    return 0.5 - 0.5 * math.cos(math.pi * max(0.0, min(1.0, t)))


def mouth_envelope(wav: Path, total_frames: int) -> list:
    """Âm lượng giọng đọc theo từng frame (0..1) để nhân vật nhép miệng."""
    raw = subprocess.run(["ffmpeg", "-loglevel", "error", "-i", str(wav), "-f", "s16le",
                          "-ac", "1", "-ar", "16000", "-"], capture_output=True, check=True).stdout
    samples = array("h")
    samples.frombytes(raw[: len(raw) // 2 * 2])
    hop = 16000 // FPS
    env = []
    for i in range(total_frames):
        chunk = samples[i * hop:(i + 1) * hop]
        env.append(math.sqrt(sum(s * s for s in chunk) / len(chunk)) if chunk else 0.0)
    peak = sorted(env)[int(len(env) * 0.95)] if env else 1.0
    peak = peak or 1.0
    out, prev = [], 0.0
    for v in env:
        v = min(1.0, v / peak)
        v = v if v > 0.18 else 0.0
        prev = prev * 0.35 + v * 0.65  # làm mượt
        out.append(prev)
    return out


def _load_bg(path: Path) -> cairo.ImageSurface:
    return cairo.ImageSurface.create_from_png(str(path))


def _paint_bg(ctx, surf, t, dur, direction):
    """Nền chuyển động chậm (zoom nhẹ) để khung hình luôn "sống"."""
    k = t / max(dur, 0.1)
    z = 1.04 + 0.06 * (k if direction > 0 else 1 - k)
    sw, sh = surf.get_width(), surf.get_height()
    s = max(W / sw, H / sh) * z
    ctx.save()
    ctx.translate(W / 2 + direction * 25 * (k - 0.5), H / 2)
    ctx.scale(s, s)
    ctx.translate(-sw / 2, -sh / 2)
    ctx.set_source_surface(surf, 0, 0)
    ctx.get_source().set_filter(cairo.FILTER_GOOD)
    ctx.paint()
    ctx.restore()


def _rounded(ctx, x, y, w, h, r):
    ctx.new_sub_path()
    ctx.arc(x + w - r, y + r, r, -math.pi / 2, 0)
    ctx.arc(x + w - r, y + h - r, r, 0, math.pi / 2)
    ctx.arc(x + r, y + h - r, r, math.pi / 2, math.pi)
    ctx.arc(x + r, y + r, r, math.pi, 3 * math.pi / 2)
    ctx.close_path()


def _keyword_card(ctx, text, cx, cy, t, accent):
    """Thẻ chữ nổi bật bật ra kiểu hiện đại (phóng to có nảy)."""
    if not text or t < 0.35:
        return
    k = min(1.0, (t - 0.35) / 0.45)
    s = max(0.0, _ease_out_back(k))
    ctx.save()
    ctx.select_font_face(FONT, cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
    size = L["font"]
    ctx.set_font_size(size)
    # tự xuống dòng nếu dài
    words, sep = tokens(text.upper())
    lines, cur = [], ""
    for w in words:
        test = (cur + sep + w).strip() if sep else cur + w
        if ctx.text_extents(test).x_advance > L["card_w"] and cur:
            lines.append(cur)
            cur = w
        else:
            cur = test
    lines.append(cur)
    lines = lines[:3]
    tw = max(ctx.text_extents(l).x_advance for l in lines)
    lh = size * 1.18
    bw, bh = tw + 90, lh * len(lines) + 60
    float_y = 6 * math.sin(t * 2.2)
    ctx.translate(cx, cy + float_y)
    ctx.scale(s, s)
    ctx.rotate(math.radians(-2.5))
    # bóng
    _rounded(ctx, -bw / 2 + 12, -bh / 2 + 14, bw, bh, 34)
    ctx.set_source_rgba(0, 0, 0, 0.22)
    ctx.fill()
    _rounded(ctx, -bw / 2, -bh / 2, bw, bh, 34)
    ctx.set_source_rgb(1, 1, 1)
    ctx.fill_preserve()
    ctx.set_source_rgb(0.07, 0.07, 0.07)
    ctx.set_line_width(7)
    ctx.stroke()
    # vạch màu nhấn
    _rounded(ctx, -bw / 2 + 30, bh / 2 - 26, bw - 60, 10, 5)
    ctx.set_source_rgb(*accent)
    ctx.fill()
    ctx.set_source_rgb(0.07, 0.07, 0.07)
    y = -bh / 2 + 30 + size * 0.92
    for l in lines:
        ext = ctx.text_extents(l)
        ctx.move_to(-ext.x_advance / 2, y)
        ctx.show_text(l)
        y += lh
    ctx.restore()


def _soft_spot(ctx, x, y):
    """Quầng sáng trắng mờ phía sau nhân vật để nổi trên nền."""
    g = cairo.RadialGradient(x, y - 260, 40, x, y - 260, 430)
    g.add_color_stop_rgba(0, 1, 1, 1, 0.75)
    g.add_color_stop_rgba(1, 1, 1, 1, 0)
    ctx.set_source(g)
    ctx.paint()


ACCENTS = [(1.0, 0.78, 0.1), (0.2, 0.6, 1.0), (1.0, 0.4, 0.45), (0.3, 0.8, 0.5), (0.65, 0.45, 1.0)]


def render_video(scenes, durations, backgrounds, voice_wav, out_mp4, style="doodle",
                 subs=None, music=None, cwd=None):
    total = sum(durations)
    nframes = int(total * FPS)
    mouth = mouth_envelope(voice_wav, nframes)
    bgs = [_load_bg(b) for b in backgrounds]
    starts, acc = [], 0.0
    for d in durations:
        starts.append(acc)
        acc += d

    vf = f"subtitles={subs.name}" if subs else "null"
    cmd = ["ffmpeg", "-y", "-loglevel", "error",
           "-f", "rawvideo", "-pix_fmt", "bgra", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
           "-i", str(Path(voice_wav).resolve())]
    if music:
        cmd += ["-stream_loop", "-1", "-i", str(music), "-filter_complex",
                f"[0:v]{vf}[v];[2:a]volume=0.10[m];[1:a][m]amix=inputs=2:duration=first:normalize=0[a]",
                "-map", "[v]", "-map", "[a]"]
    else:
        cmd += ["-filter_complex", f"[0:v]{vf}[v]", "-map", "[v]", "-map", "1:a"]
    cmd += ["-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k", "-shortest", "-movflags", "+faststart", str(Path(out_mp4).resolve())]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, cwd=cwd)

    surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, W, H)
    ctx = cairo.Context(surf)
    blinker = Blinker(7)
    prev_pose = None
    for f in range(nframes):
        t = f / FPS
        i = max(j for j, s0 in enumerate(starts) if s0 <= t + 1e-9)
        sc, ts, dur = scenes[i], t - starts[i], durations[i]
        side = sc.get("side", "left")
        char_x = L["char_x"][0 if side == "left" else 1]
        card_x, card_y = L["card"][0 if side == "left" else 1]

        # nền + chuyển cảnh mờ dần
        ctx.set_source_rgb(1, 1, 1)
        ctx.paint()
        _paint_bg(ctx, bgs[i], ts, dur, 1 if i % 2 == 0 else -1)
        if i > 0 and ts < XFADE:
            ctx.push_group()
            _paint_bg(ctx, bgs[i - 1], durations[i - 1] + ts, durations[i - 1], 1 if (i - 1) % 2 == 0 else -1)
            ctx.pop_group_to_source()
            ctx.paint_with_alpha(1 - _ease(ts / XFADE))

        # nhân vật
        action = sc.get("action", "talk")
        x = char_x
        if action == "walk" or (i == 0 and ts < 1.6):
            # đi vào khung hình ở đầu video / cảnh "walk"
            k = _ease(min(1.0, ts / 1.6))
            start_x = -200 if side == "left" else W + 200
            x = start_x + (char_x - start_x) * k
            pose = pose_at("walk", ts * 1.2) if k < 1 else pose_at("talk", ts)
        else:
            pose = pose_at(action, ts, seed=i)
        # chuyển tư thế mượt giữa hai cảnh
        if i > 0 and ts < 0.4 and prev_pose is not None:
            pose = blend(prev_pose, pose, _ease(ts / 0.4))
        if ts >= 0.4 or i == 0:
            last_pose = pose
        if dur - ts <= 1 / FPS + 1e-6:
            prev_pose = last_pose
        m = mouth[f] if f < len(mouth) else 0.0
        pose["bob"] -= m * 4  # nhún nhẹ theo nhịp nói
        pose["tilt"] += m * 3 * math.sin(t * 6)

        _soft_spot(ctx, x, GROUND)
        draw_character(ctx, _mirror(pose) if side == "right" else pose, x, GROUND, L["scale"], style,
                       {"expression": sc.get("expression", "happy"), "mouth": m, "blink": blinker.value(t)})

        _keyword_card(ctx, sc.get("keyword", ""), card_x, card_y, ts, ACCENTS[i % len(ACCENTS)])

        # mờ dần ở đầu và cuối video
        edge = min(t, total - t)
        if edge < 0.4:
            ctx.set_source_rgba(0, 0, 0, 1 - edge / 0.4)
            ctx.paint()
        surf.flush()
        proc.stdin.write(bytes(surf.get_data()))
        if f % (FPS * 10) == 0:
            print(f"[render] {t:.0f}/{total:.0f}s")
    proc.stdin.close()
    if proc.wait() != 0:
        raise SystemExit("ffmpeg lỗi khi dựng video")


def _mirror(pose):
    """Đổi tay trái/phải để nhân vật đứng bên phải vẫn chỉ vào giữa màn hình."""
    p = dict(pose)
    for a, b in (("ls", "rs"), ("le", "re"), ("lh", "rh"), ("lk", "rk"), ("lpoint", "rpoint")):
        p[a], p[b] = pose[b], pose[a]
    p["lean"], p["tilt"], p["gx"] = -pose["lean"], -pose["tilt"], -pose["gx"]
    return p


def render_still(background, out_png, style="doodle", side="left"):
    """Khung hình cho thumbnail: nền + nhân vật tư thế hào hứng, cỡ lớn."""
    surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, W, H)
    ctx = cairo.Context(surf)
    _paint_bg(ctx, _load_bg(background), 0, 1, 1)
    sx, sscale, sdy = L["still"]
    x = sx if side == "left" else W - sx
    _soft_spot(ctx, x, GROUND + sdy)
    pose = pose_at("point_up", 0.2)
    draw_character(ctx, pose, x, GROUND + sdy, sscale, style, {"expression": "excited", "mouth": 0.7})
    surf.write_to_png(str(out_png))
    return out_png


def preview_frames(scenes, backgrounds, out_dir, style="doodle"):
    """Vẽ nhanh 1 khung hình đại diện cho mỗi cảnh (không cần dựng cả video) để kiểm tra bố cục.

    Trả về danh sách file PNG, mỗi file là cảnh lúc thẻ chữ đã hiện đầy đủ.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, W, H)
    ctx = cairo.Context(surf)
    cache, files = {}, []
    for i, (sc, bg) in enumerate(zip(scenes, backgrounds)):
        if bg not in cache:
            cache[bg] = _load_bg(bg)
        side = sc.get("side", "left")
        x = L["char_x"][0 if side == "left" else 1]
        card_x, card_y = L["card"][0 if side == "left" else 1]
        ctx.set_source_rgb(1, 1, 1)
        ctx.paint()
        _paint_bg(ctx, cache[bg], 1.5, 6, 1 if i % 2 == 0 else -1)
        _soft_spot(ctx, x, GROUND)
        pose = pose_at(sc.get("action", "talk"), 1.2, seed=i)
        draw_character(ctx, _mirror(pose) if side == "right" else pose, x, GROUND, L["scale"], style,
                       {"expression": sc.get("expression", "happy"), "mouth": 0.5})
        _keyword_card(ctx, sc.get("keyword", ""), card_x, card_y, 1.5, ACCENTS[i % len(ACCENTS)])
        ctx.save()
        ctx.select_font_face(FONT, cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
        ctx.set_font_size(44)
        ctx.set_source_rgba(0, 0, 0, 0.75)
        ctx.move_to(130, 60)
        ctx.show_text(f"#{i + 1} {sc.get('action')} / {sc.get('expression')}")
        ctx.restore()
        f = out_dir / f"scene_{i + 1:02d}.png"
        surf.write_to_png(str(f))
        files.append(f)
    return files
