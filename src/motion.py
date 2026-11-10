"""Bộ dựng chuyển động (motion graphics) kiểu video Shorts chuyên nghiệp.

Ý tưởng: một "sân khấu" rộng, camera lướt/zoom liên tục; diễn viên và đạo cụ là ảnh cắt nền
xuất hiện, nảy, trượt, bay theo đường; mũi tên, nhãn, vòng tròn, đường sáng tự vẽ dần;
mọi thứ khớp với thời điểm từng từ trong giọng đọc. Xem prompts/motion_spec.md.
"""
import math
import random
import subprocess
from pathlib import Path

import cairo
from PIL import Image, ImageFilter

import scene_video as SV  # dùng chung W, H, FONT, LANG, tokens()
import face as FACE

FPS = 30
CAPTION_FONT = None  # font đậm nhất cho phụ đề (đặt trong render)
EV_DUR = {"camera": 0.9, "move": 0.8, "enter": 0.45, "exit": 0.4, "action": 0.6, "expr": 0.25,
          "arrow": 0.5, "line": 1.1, "highlight": 0.6, "label": 0.35, "burst": 0.9, "flow": 3.0}
SFX_FOR = {"enter": "pop", "exit": "whoosh", "expr": "pop", "burst": "ding", "label": "tick",
           "highlight": "tick", "arrow": "whoosh", "line": "whoosh", "stage": "whoosh", "shake": "thud"}


# ------------------------------------------------------------------ easing ---

def _sc(ctx, x, y=None):
    """ctx.scale an toàn: tỉ lệ 0 (lúc hiệu ứng pop bắt đầu) làm cairo lỗi 'invalid matrix'."""
    y = x if y is None else y
    x = x if abs(x) > 1e-3 else (1e-3 if x >= 0 else -1e-3)
    y = y if abs(y) > 1e-3 else (1e-3 if y >= 0 else -1e-3)
    ctx.scale(x, y)


def clamp(v, a=0.0, b=1.0):
    return max(a, min(b, v))


def ease_io(t):
    t = clamp(t)
    return 4 * t ** 3 if t < 0.5 else 1 - (-2 * t + 2) ** 3 / 2


def ease_out(t):
    return 1 - (1 - clamp(t)) ** 3


def back(t, s=1.9):
    t = clamp(t) - 1
    return 1 + (s + 1) * t ** 3 + s * t ** 2


def elastic(t):
    t = clamp(t)
    if t in (0, 1):
        return t
    return 2 ** (-10 * t) * math.sin((t * 10 - 0.75) * (2 * math.pi) / 3) + 1


# ------------------------------------------------------------------ tài nguyên ---

class Images:
    def __init__(self):
        self.cache = {}

    def get(self, path, blur=0):
        key = (str(path), blur)
        if key not in self.cache:
            self.cache[key] = to_surface(path, blur)
        return self.cache[key]


def to_surface(path, blur=0):
    """Đọc ảnh bằng PIL rồi chuyển thẳng sang cairo trong bộ nhớ (không ghi file tạm:
    tránh lỗi libpng khi một tiến trình khác đang ghi cùng file)."""
    for attempt in range(3):
        try:
            im = Image.open(path)
            im.load()
            break
        except OSError:
            if attempt == 2:
                raise
            import time
            time.sleep(2)
    im = im.convert("RGBA")
    if blur:
        im = im.filter(ImageFilter.GaussianBlur(blur))
    # cairo ARGB32 = BGRA, alpha nhân sẵn (premultiplied)
    r, g, b, a = im.split()
    from PIL import ImageChops
    r, g, b = (ImageChops.multiply(c, a) for c in (r, g, b))
    data = bytearray(Image.merge("RGBA", (b, g, r, a)).tobytes())
    w, h = im.size
    stride = cairo.ImageSurface.format_stride_for_width(cairo.FORMAT_ARGB32, w)
    if stride != w * 4:
        rows = [bytes(data[y * w * 4:(y + 1) * w * 4]).ljust(stride, b"\0") for y in range(h)]
        data = bytearray(b"".join(rows))
    return cairo.ImageSurface.create_for_data(data, cairo.FORMAT_ARGB32, w, h, stride)


# ------------------------------------------------------------------ timeline ---

class Film:
    """Biên dịch kịch bản chuyển động thành dòng thời gian tuyệt đối."""

    def __init__(self, film, timings, assets):
        self.film = film
        self.assets = assets  # {"stage:<id>": path, "<id>": path, "<id>:<expr>": path}
        self.events = []      # (t, scene_index, event)
        self.scene_spans = []
        self.words = []       # (start, end, word, scene_index)
        t0 = 0.0
        for si, (sc, (dur, wtimes)) in enumerate(zip(film["scenes"], timings)):
            self.scene_spans.append((t0, t0 + dur, sc.get("stage")))
            words = sc["narration"].split()
            for w, (a, b) in zip(words, wtimes):
                self.words.append((t0 + a, t0 + b, w, si))
            # đổi sân khấu ở đầu cảnh
            if si == 0 or sc.get("stage") != film["scenes"][si - 1].get("stage"):
                self.events.append((t0, si, {"do": "stage", "id": sc.get("stage"),
                                             "transition": sc.get("transition", "whip")}))
            for ev in sc.get("events", []):
                at = ev.get("at", 0)
                try:
                    at = float(at)
                except (TypeError, ValueError):
                    at = 0.0
                i = int(clamp(math.floor(at), 0, max(0, len(wtimes) - 1)))
                frac = at - math.floor(at)
                if wtimes:
                    a, b = wtimes[i]
                    t = a + (b - a) * frac
                else:
                    t = 0
                self.events.append((t0 + max(0.0, t) + float(ev.get("delay", 0)), si, ev))
            t0 += dur
        self.total = t0
        self._emphasis()
        self.events.sort(key=lambda e: (e[0], 0 if e[2].get("do") == "stage" else 1))
        self._build_tracks()

    def _emphasis(self):
        """Từ khoá được nhấn: số liệu, từ trong scene['emphasis'], CHỮ HOA. Mỗi từ khoá có cú zoom nhẹ."""
        import re
        import unicodedata
        def norm(w):
            w = unicodedata.normalize("NFC", w.lower())
            return re.sub(r"[^\w%$€£¥]+", "", w)
        self.emph = set()
        self.punches = []
        for i, (a, b, w, si) in enumerate(self.words):
            sc = self.film["scenes"][si]
            keys = {norm(x) for k in sc.get("emphasis", []) for x in str(k).split()}
            raw = w.strip(".,!?;:…\"'()")
            if (norm(w) and norm(w) in keys) or re.search(r"\d", w) or \
                    (len(raw) >= 2 and raw.isupper() and raw.isalpha()):
                self.emph.add(i)
                if not self.punches or a - self.punches[-1] > 1.2:
                    self.punches.append(a)

    def punch_at(self, t):
        """0..1: độ 'giật' camera ngắn ngay khi nói từ khoá."""
        best = 0.0
        for tp in self.punches:
            d = t - tp
            if 0 <= d < 0.45:
                best = max(best, math.exp(-d * 9) * (1 - math.exp(-d * 60)))
        return best

    def _build_tracks(self):
        """Mỗi đối tượng: danh sách sự kiện theo thời gian. Đổi sân khấu thì xoá sân khấu cũ."""
        self.objects = {}   # oid -> dict(kind, events[], born, died)
        self.stage_changes = []
        self.cameras = []   # (t, x, y, zoom, dur)
        self.shakes = []
        self.overlays = []  # arrow/line/highlight/label/burst: (t, ev, end_t)
        self.reactions = []  # (t, oid, icon): biểu tượng cảm xúc trên đầu nhân vật
        gen = 0
        for t, si, ev in self.events:
            do = ev.get("do")
            if do == "stage":
                self.stage_changes.append((t, ev.get("id"), ev.get("transition", "whip")))
                gen += 1
                for o in self.objects.values():
                    if o["died"] is None:
                        o["died"] = t
                # góc máy mặc định khi vào sân khấu mới
                self.cameras.append((t, 0.5, 0.55, 1.0, 0.01))
                continue
            if do == "camera":
                self.cameras.append((t, float(ev.get("x", 0.5)), float(ev.get("y", 0.5)),
                                     float(ev.get("zoom", 1.0)), float(ev.get("dur", EV_DUR["camera"]))))
            elif do == "shake":
                self.shakes.append((t, float(ev.get("strength", 1.0))))
            elif do in ("arrow", "line", "highlight", "label", "burst", "flow"):
                hold = float(ev.get("hold", 2.6 if do != "burst" else 1.0))
                self.overlays.append((t, ev, t + hold, gen))
            elif do == "react":
                self.reactions.append((t, f'{ev.get("id")}#{gen}', str(ev.get("icon", "!"))))
            elif do in ("enter", "move", "exit", "action", "expr"):
                oid = f'{ev.get("id")}#{gen}'
                icon = react_for(ev.get("expr", "")) if do in ("expr", "enter") and ev.get("expr") else None
                if icon and ev.get("react", True) is not False:
                    self.reactions.append((t + (0.25 if do == "enter" else 0.05), oid, icon))
                if do == "enter" or oid not in self.objects:
                    if do != "enter":
                        continue  # chưa vào sân khấu thì bỏ qua
                    self.objects[oid] = {"id": ev.get("id"), "events": [], "born": t, "died": None}
                o = self.objects[oid]
                o["events"].append((t, ev))
                if do == "exit":
                    o["died"] = t + EV_DUR["exit"]
        for o in self.objects.values():
            if o["died"] is None:
                o["died"] = self.total + 1
        # nhãn/mũi tên của sân khấu cũ biến mất khi đổi cảnh
        changes = [c[0] for c in self.stage_changes]
        fixed = []
        for t, ev, end, g in self.overlays:
            nxt = [c for c in changes if c > t + 1e-6]
            fixed.append((t, ev, min(end, nxt[0]) if nxt else end, g))
        self.overlays = fixed

    # ---------------- trạng thái tại thời điểm t
    def stage_at(self, t):
        cur, prev, tchange, trans = None, None, -9, "whip"
        for tc, sid, tr in self.stage_changes:
            if tc <= t + 1e-9:
                prev, cur, tchange, trans = cur, sid, tc, tr
        return cur, prev, tchange, trans

    def camera_at(self, t):
        cams = [c for c in self.cameras if c[0] <= t + 1e-9]
        if not cams:
            return 0.5, 0.55, 1.0
        # bắt đầu từ góc máy của lần đổi sân khấu gần nhất
        st = max([c[0] for c in self.stage_changes if c[0] <= t + 1e-9] or [0])
        cams = [c for c in cams if c[0] >= st - 1e-9]
        x, y, z = cams[0][1], cams[0][2], cams[0][3]
        for (tc, cx, cy, cz, d) in cams[1:]:
            k = ease_io((t - tc) / max(d, 0.01))
            x, y, z = x + (cx - x) * k, y + (cy - y) * k, z + (cz - z) * k
        # trôi nhẹ liên tục (không bao giờ đứng yên)
        z *= 1 + 0.018 * math.sin((t - st) * 0.35) + 0.012 * (t - st) / 6
        x += 0.006 * math.sin((t - st) * 0.27)
        return x, y, z


def obj_state(o, t, film_assets):
    """Vị trí, cỡ, góc, độ mờ, ảnh của một đối tượng tại thời điểm t."""
    st = {"x": 0.5, "y": 0.7, "size": 0.4, "rot": 0.0, "alpha": 1.0, "sx": 1.0, "sy": 1.0,
          "dx": 0.0, "dy": 0.0, "flip": False, "expr": None, "blur": 0.0, "lean": 0.0}
    for te, ev in o["events"]:
        if te > t:
            break
        do, k = ev.get("do"), t - te
        if do == "enter":
            st["x"], st["y"] = float(ev.get("x", 0.5)), float(ev.get("y", 0.7))
            st["size"] = float(ev.get("size", 0.4))
            st["flip"] = bool(ev.get("flip", False))
            st["expr"] = ev.get("expr")
            anim = ev.get("anim", "pop")
            d = EV_DUR["enter"] * (1.4 if anim in ("drop", "slide_left", "slide_right", "rise") else 1)
            p = k / d
            if p < 1:
                if anim == "pop":
                    s = back(p, 2.4)
                    st["sx"] = st["sy"] = max(0.0, s)
                elif anim == "fade":
                    st["alpha"] = clamp(p)
                elif anim in ("slide_left", "slide_right"):
                    sign = -1 if anim == "slide_left" else 1
                    st["dx"] = sign * 0.9 * (1 - back(p, 1.2))
                    st["blur"] = (1 - p) * 1.0
                elif anim == "drop":
                    e = clamp(p / 0.7)
                    st["dy"] = -1.0 * (1 - e * e)
                    if p > 0.7:  # chạm đất: bẹp rồi nảy
                        q = (p - 0.7) / 0.3
                        sq = math.sin(q * math.pi) * 0.22
                        st["sx"], st["sy"] = 1 + sq, 1 - sq
                elif anim == "rise":
                    st["dy"] = 0.6 * (1 - back(p, 1.4))
        elif do == "move":
            d = float(ev.get("dur", EV_DUR["move"]))
            p = ease_io(k / d)
            tx, ty = ev.get("to", [st["x"], st["y"]])
            x0, y0 = st["x"], st["y"]
            st["x"], st["y"] = x0 + (tx - x0) * p, y0 + (ty - y0) * p
            if ev.get("path") == "arc" and p < 1:
                st["y"] -= math.sin(p * math.pi) * float(ev.get("height", 0.12))
            if 0 < k < d:
                q = k / d
                dirn = 1 if tx > x0 else -1
                st["lean"] += dirn * 0.16 * math.sin(q * math.pi)  # nghiêng người theo hướng đi
                st["blur"] = max(st["blur"], math.sin(q * math.pi) * 0.45)
                if ev.get("path") != "arc":  # bước nhún: nảy lên rồi bẹp khi chạm đất
                    steps = max(2, round(d * 3.2))
                    hop = abs(math.sin(math.pi * steps * q))
                    st["dy"] -= 0.022 * hop
                    st["sy"] *= 1 - 0.07 * (1 - hop) + 0.04 * hop
                    st["sx"] *= 1 + 0.05 * (1 - hop)
            if "flip" in ev:
                st["flip"] = bool(ev["flip"])
        elif do == "exit":
            p = k / EV_DUR["exit"]
            anim = ev.get("anim", "pop")
            if anim == "pop":
                st["sx"] = st["sy"] = max(0.0, 1 - back(p, 1.5))
            elif anim == "fade":
                st["alpha"] = clamp(1 - p)
            elif anim in ("slide_left", "slide_right"):
                st["dx"] = (-1 if anim == "slide_left" else 1) * ease_out(p) * 1.0
                st["blur"] = clamp(p)
            elif anim == "fall":
                st["dy"] = 1.2 * p * p
                st["rot"] += 40 * p
        elif do == "action":
            anim = ev.get("anim", "bounce")
            d = float(ev.get("dur", EV_DUR["action"] * (1.4 if anim == "jump" else 1)))
            p = k / d
            if anim == "grow":
                st["size"] *= 1 + 0.35 * ease_out(p)
            elif anim == "shrink":
                st["size"] *= 1 - 0.3 * ease_out(p)
            elif p < 1:
                w = math.sin(p * math.pi)
                if anim == "bounce":
                    st["dy"] -= 0.05 * abs(math.sin(p * math.pi * 2))
                    st["sy"] *= 1 + 0.06 * math.sin(p * math.pi * 4)
                elif anim == "jump":
                    if p < 0.18:  # lấy đà: ngồi xuống
                        c = math.sin(p / 0.18 * math.pi / 2)
                        st["sy"] *= 1 - 0.16 * c
                        st["sx"] *= 1 + 0.10 * c
                    elif p < 0.82:  # bay: kéo dài người
                        q = (p - 0.18) / 0.64
                        st["dy"] -= 0.17 * math.sin(q * math.pi)
                        st["sy"] *= 1 + 0.12 * math.cos(q * math.pi) * (1 if q < 0.5 else 0.3)
                        st["sx"] *= 1 - 0.06 * math.cos(q * math.pi) * (1 if q < 0.5 else 0.3)
                    else:  # chạm đất: bẹp rồi đàn hồi
                        q = (p - 0.82) / 0.18
                        c = math.sin(q * math.pi)
                        st["sy"] *= 1 - 0.14 * c
                        st["sx"] *= 1 + 0.10 * c
                elif anim == "shake":
                    st["dx"] += 0.012 * math.sin(p * 60) * (1 - p)
                elif anim == "spin":
                    st["rot"] += 360 * ease_io(p)
                elif anim == "nod":
                    st["rot"] += 7 * math.sin(p * math.pi * 3)
                elif anim == "wiggle":
                    st["rot"] += 10 * math.sin(p * math.pi * 5) * (1 - p)
                elif anim == "pulse":
                    s = 1 + 0.18 * w
                    st["sx"] *= s
                    st["sy"] *= s
                elif anim == "tremble":
                    st["dx"] += 0.004 * math.sin(p * 90)
        elif do == "expr":
            st["expr"] = ev.get("expr")
            p = k / EV_DUR["expr"]
            if p < 1:
                sq = math.sin(p * math.pi) * 0.12
                st["sx"] *= 1 + sq
                st["sy"] *= 1 - sq
    return st


# ------------------------------------------------------------------ vẽ ---


REACT_KEYS = (("!", ("shock", "surpris", "scare", "wow", "amaz", "gasp", "fear")),
              ("?", ("confus", "think", "wonder", "curious", "doubt", "puzzl")),
              ("idea", ("idea", "realiz", "smart", "genius", "eureka")),
              ("heart", ("love", "adore", "cute", "kiss")),
              ("anger", ("angry", "mad", "furious", "annoy")),
              ("sweat", ("sad", "cry", "worr", "tired", "nervous", "embarrass", "awkward", "sick")),
              ("sparkle", ("happy", "excit", "laugh", "joy", "proud", "cheer", "smile")),
              ("stars", ("dizzy", "confused2")))


def react_for(expr):
    e = str(expr).lower()
    for icon, keys in REACT_KEYS:
        if any(k in e for k in keys):
            return icon
    return None


def draw_reaction(ctx, icon, k, x, top, hh):
    """Biểu tượng cảm xúc kiểu hoạt hình phía trên đầu, bật ra rồi nhún nhẹ, mờ dần."""
    r = max(14.0, hh * 0.085)
    pop = back(clamp(k / 0.22), 3.0)
    fade = clamp((1.6 - k) / 0.3)
    if pop <= 0.01 or fade <= 0:
        return
    bob = math.sin(k * 7) * r * 0.12
    ctx.save()
    ctx.translate(x + r * 0.6, top - r * 0.9 + bob)
    _sc(ctx, pop, pop)
    ctx.rotate(math.radians(8 * math.sin(k * 5)))
    ink = (0.1, 0.08, 0.12)
    lw = r * 0.16

    def outline_fill(col):
        ctx.set_source_rgba(*ink, fade)
        ctx.set_line_width(lw)
        ctx.set_line_join(cairo.LINE_JOIN_ROUND)
        ctx.stroke_preserve()
        ctx.set_source_rgba(*col, fade)
        ctx.fill()

    if icon == "!":
        for dx, h in ((-0.35, 1.0), (0.45, 0.8)):
            ctx.save()
            ctx.translate(dx * r, 0)
            ctx.rotate(math.radians(-12 if dx < 0 else 12))
            ctx.move_to(-0.22 * r, -1.3 * r * h)
            ctx.line_to(0.22 * r, -1.3 * r * h)
            ctx.line_to(0.12 * r, 0.2 * r)
            ctx.line_to(-0.12 * r, 0.2 * r)
            ctx.close_path()
            outline_fill((1, 0.25, 0.25))
            ctx.arc(0, 0.62 * r, 0.2 * r, 0, 2 * math.pi)
            outline_fill((1, 0.25, 0.25))
            ctx.restore()
    elif icon == "?":
        ctx.select_font_face("DejaVu Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
        ctx.set_font_size(max(0.5, r * 2.4))
        ext = ctx.text_extents("?")
        ctx.move_to(-ext.width / 2 - ext.x_bearing, ext.height / 2)
        ctx.text_path("?")
        outline_fill((0.35, 0.65, 1))
    elif icon == "heart":
        for j, (dx, dy, sc) in enumerate(((0, 0, 1), (0.9, -0.8, 0.55))):
            ctx.save()
            ctx.translate(dx * r, dy * r + math.sin(k * 6 + j) * r * 0.1)
            _sc(ctx, sc, sc)
            ctx.move_to(0, r * 0.7)
            ctx.curve_to(-r * 1.3, -r * 0.2, -r * 0.6, -r * 1.2, 0, -r * 0.45)
            ctx.curve_to(r * 0.6, -r * 1.2, r * 1.3, -r * 0.2, 0, r * 0.7)
            outline_fill((1, 0.3, 0.45))
            ctx.restore()
    elif icon == "idea":
        ctx.arc(0, -r * 0.3, r * 0.75, math.pi * 0.8, math.pi * 2.2)
        ctx.line_to(r * 0.35, r * 0.65)
        ctx.line_to(-r * 0.35, r * 0.65)
        ctx.close_path()
        outline_fill((1, 0.9, 0.25))
        ctx.rectangle(-r * 0.32, r * 0.7, r * 0.64, r * 0.3)
        outline_fill((0.7, 0.7, 0.75))
        for a in range(-2, 3):
            ang = -math.pi / 2 + a * 0.55
            ctx.move_to(math.cos(ang) * r * 1.05, -r * 0.3 + math.sin(ang) * r * 1.05)
            ctx.line_to(math.cos(ang) * r * 1.45, -r * 0.3 + math.sin(ang) * r * 1.45)
        ctx.set_source_rgba(1, 0.8, 0.1, fade)
        ctx.set_line_width(lw * 1.1)
        ctx.set_line_cap(cairo.LINE_CAP_ROUND)
        ctx.stroke()
    elif icon == "anger":
        for q in range(4):
            ctx.save()
            ctx.rotate(q * math.pi / 2)
            ctx.move_to(r * 0.2, -r * 0.2)
            ctx.curve_to(r * 0.3, -r * 0.6, r * 0.6, -r * 0.6, r * 0.75, -r * 0.75)
            ctx.set_source_rgba(0.9, 0.1, 0.15, fade)
            ctx.set_line_width(lw * 1.6)
            ctx.set_line_cap(cairo.LINE_CAP_ROUND)
            ctx.stroke()
            ctx.restore()
    elif icon == "sweat":
        drop = (k * 0.6) % 1.0
        ctx.translate(r * 0.2, drop * r * 0.8)
        ctx.move_to(0, -r)
        ctx.curve_to(r * 0.7, -r * 0.1, r * 0.6, r * 0.6, 0, r * 0.6)
        ctx.curve_to(-r * 0.6, r * 0.6, -r * 0.7, -r * 0.1, 0, -r)
        outline_fill((0.55, 0.85, 1))
    elif icon in ("sparkle", "stars"):
        for j, (dx, dy, sc) in enumerate(((0, 0, 1), (-1.1, 0.5, 0.55), (1.0, 0.6, 0.5))):
            ctx.save()
            ctx.translate(dx * r, dy * r)
            ctx.rotate(k * (2 if icon == "stars" else 0.6) + j)
            sc *= 0.8 + 0.2 * math.sin(k * 9 + j * 2)
            ctx.move_to(0, -r * sc)
            for i in range(1, 8):
                rr = r * sc if i % 2 == 0 else r * sc * 0.36
                a = -math.pi / 2 + i * math.pi / 4
                ctx.line_to(math.cos(a) * rr, math.sin(a) * rr)
            ctx.close_path()
            outline_fill((1, 0.85, 0.2))
            ctx.restore()
    ctx.restore()

# ------------------------------------------------------------------ face ---

def h_on_screen(s, sy, ih):
    return abs(s * sy) * ih


def _vowel(word):
    """Nhóm khẩu hình theo nguyên âm chính của từ: a (mở to), o (tròn), e (dẹt), m (khép môi)."""
    import unicodedata
    w = unicodedata.normalize("NFD", word.lower())
    w = "".join(ch for ch in w if unicodedata.category(ch) != "Mn").replace("đ", "d")
    vs = [ch for ch in w if ch in "aeiouy"]
    if not vs:
        return "m"
    main = vs[len(vs) // 2] if len(vs) > 2 else vs[-1] if len(vs) == 2 and vs[0] in "iuy" else vs[0]
    return {"a": "a", "o": "o", "u": "o", "e": "e", "i": "e", "y": "e"}[main]


MOODS = (("o", ("shock", "surpris", "scare", "wow", "fear", "amaz", "gasp")),
         ("frown", ("sad", "cry", "worr", "angry", "mad", "upset", "tired", "sick", "disappoint")),
         ("grin", ("happy", "laugh", "excit", "joy", "proud", "cheer", "love", "smile")),
         ("flat", ("think", "confus", "bored", "serious", "doubt", "sleep")))


def _mood(expr):
    for m, keys in MOODS:
        if any(k in expr for k in keys):
            return m
    return "smile"


def draw_face(ctx, fc, iw, ih, t, seed, talk, word, expr):
    """Vẽ miệng nhép theo giọng (và chớp mắt) lên ảnh nhân vật, toạ độ theo pixel ảnh."""
    skin = _hex(fc.get("skin", "#F2C9A0"))
    ink = (0.16, 0.08, 0.08)
    mx, my = fc["mouth"][0] * iw, fc["mouth"][1] * ih
    mw = max(6.0, float(fc.get("mouth_width", 0.12)) * iw)
    mood = _mood(expr)
    # --- chớp mắt mỗi ~3-5 giây
    eyes = fc.get("eyes") or []
    period = 3.4 + (seed % 1.7)
    ph = (t + seed) % period
    blink = math.sin(ph / 0.16 * math.pi) if ph < 0.16 else 0.0
    if blink > 0.05 and len(eyes) == 2:
        for ex, ey, er in eyes:
            ex, ey, er = ex * iw, ey * ih, max(3.0, er * iw)
            ctx.save()
            ctx.arc(ex, ey, er * 1.25, 0, 2 * math.pi)
            ctx.clip()
            lid = ey - er * 1.3 + er * 2.5 * blink
            ctx.rectangle(ex - er * 1.4, ey - er * 1.4, er * 2.8, lid - (ey - er * 1.4))
            ctx.set_source_rgb(*skin)
            ctx.fill()
            ctx.restore()
            if blink > 0.6:
                ctx.set_source_rgb(*ink)
                ctx.set_line_width(max(1.5, er * 0.28))
                ctx.set_line_cap(cairo.LINE_CAP_ROUND)
                ctx.move_to(ex - er, lid - er * 0.1)
                ctx.curve_to(ex - er * 0.4, lid + er * 0.35, ex + er * 0.4, lid + er * 0.35, ex + er, lid - er * 0.1)
                ctx.stroke()
    if fc.get("mouth_open"):
        return  # ảnh gốc vẽ miệng há to (có răng/lưỡi): giữ nguyên, che đi sẽ lộ vết
    # --- xoá miệng gốc (nếu có) bằng màu da, mép mềm
    if fc.get("has_mouth", True):
        rx = mw * 0.6
        ry = max(float(fc.get("mouth_h", 0)) * ih * 0.75, mw * 0.28)
        ctx.save()
        ctx.translate(mx, my)
        _sc(ctx, 1, ry / rx)
        g = cairo.RadialGradient(0, 0, rx * 1.0, 0, 0, rx * 1.25)
        g.add_color_stop_rgba(0, *skin, 1)
        g.add_color_stop_rgba(1, *skin, 0)
        ctx.set_source(g)
        ctx.arc(0, 0, rx * 1.25, 0, 2 * math.pi)
        ctx.fill()
        ctx.restore()
    # --- hình miệng
    op = clamp(talk * 1.25)
    if op < 0.12 and mood in ("o",):
        op = 0.45
    v = _vowel(word) if op >= 0.12 else "m"
    if mood == "o" and op < 0.5:
        v = "o"
    lw = max(1.5, mw * 0.085)
    ctx.save()
    ctx.translate(mx, my)
    ctx.set_line_join(cairo.LINE_JOIN_ROUND)
    ctx.set_line_cap(cairo.LINE_CAP_ROUND)
    if v == "m" or op < 0.12:
        # môi khép: cười / mếu / thẳng
        curve = {"smile": 0.28, "grin": 0.4, "frown": -0.3, "flat": 0.04, "o": 0.1}[mood]
        half = mw * (0.5 if mood != "grin" else 0.58)
        if mood == "grin":  # cười tươi miệng mở hình bán nguyệt
            ctx.move_to(-half, -mw * 0.05)
            ctx.curve_to(-half * 0.6, mw * 0.55, half * 0.6, mw * 0.55, half, -mw * 0.05)
            ctx.close_path()
            _fill_mouth(ctx, mw, ink, teeth=True)
        else:
            ctx.move_to(-half, -curve * mw * 0.3)
            ctx.curve_to(-half * 0.4, curve * mw * 0.55, half * 0.4, curve * mw * 0.55, half, -curve * mw * 0.3)
            ctx.set_source_rgb(*ink)
            ctx.set_line_width(lw)
            ctx.stroke()
    else:
        # mở theo nguyên âm, độ mở theo âm lượng
        wf, hf = {"a": (0.95, 0.75), "o": (0.55, 0.8), "e": (1.05, 0.38)}[v]
        if mood == "frown":
            hf *= 0.8
        hw = mw * 0.5 * wf * (0.85 + 0.15 * op)
        hh = mw * hf * (0.25 + 0.75 * op)
        top = -hh * 0.35
        bot = hh * 0.65
        smile = mw * (0.08 if mood in ("smile", "grin") else -0.06 if mood == "frown" else 0)
        ctx.move_to(-hw, -smile)
        ctx.curve_to(-hw * 0.7, top - smile * 0.3, hw * 0.7, top - smile * 0.3, hw, -smile)
        ctx.curve_to(hw * 0.8, bot, -hw * 0.8, bot, -hw, -smile)
        ctx.close_path()
        _fill_mouth(ctx, mw, ink, teeth=v in ("a", "e") and op > 0.35)
    ctx.restore()


def _fill_mouth(ctx, mw, ink, teeth):
    path = ctx.copy_path()
    ctx.set_source_rgb(0.36, 0.08, 0.12)
    ctx.fill_preserve()
    ctx.save()
    ctx.clip()
    x0, y0, x1, y1 = ctx.clip_extents()
    ctx.set_source_rgb(0.98, 0.45, 0.5)  # lưỡi
    ctx.save()
    ctx.translate((x0 + x1) / 2, y1)
    ctx.scale(1, 0.55)
    ctx.arc(0, 0, (x1 - x0) * 0.36, 0, 2 * math.pi)
    ctx.restore()
    ctx.fill()
    if teeth:
        ctx.set_source_rgb(1, 1, 1)
        ctx.rectangle(x0, y0, x1 - x0, (y1 - y0) * 0.22)
        ctx.fill()
    ctx.restore()
    ctx.new_path()
    ctx.append_path(path)
    ctx.set_source_rgb(*ink)
    ctx.set_line_width(max(1.5, mw * 0.08))
    ctx.stroke()


def _rounded(ctx, x, y, w, h, r):
    ctx.new_sub_path()
    ctx.arc(x + w - r, y + r, r, -math.pi / 2, 0)
    ctx.arc(x + w - r, y + h - r, r, 0, math.pi / 2)
    ctx.arc(x + r, y + h - r, r, math.pi / 2, math.pi)
    ctx.arc(x + r, y + r, r, math.pi, 3 * math.pi / 2)
    ctx.close_path()


def _hex(c, default=(1, 1, 1)):
    try:
        c = c.lstrip("#")
        return tuple(int(c[i:i + 2], 16) / 255 for i in (0, 2, 4))
    except (AttributeError, ValueError, IndexError):
        return default


class Renderer:
    def __init__(self, film: Film, assets, envelope):
        self.f = film
        self.assets = assets
        self.img = Images()
        self.env = envelope
        self.W, self.H = SV.W, SV.H
        self.stage_surf = {}
        for k, p in assets.items():
            if k.startswith("stage:"):
                self.stage_surf[k[6:]] = p
        self.dof = {s.get("id"): bool(s.get("dof")) for s in film.film.get("stages", [])}
        self.speakers = [sc.get("speaker") for sc in film.film["scenes"]]
        self._cur_view = None
        self.cast = {c.get("id"): c for c in film.film.get("cast", [])}
        self.faces = {}
        self.word_starts = [w[0] for w in film.words]

    # -- camera
    def _view(self, sid, t, offset=(0, 0)):
        surf = self.img.get(self.stage_surf[sid], blur=6 if self.dof.get(sid) else 0)
        sw, sh = surf.get_width(), surf.get_height()
        cx, cy, z = self.f.camera_at(t)
        zmin = max(self.W / sw, self.H / sh) * 1.001
        z = max(z, zmin) * (1 + 0.075 * self.f.punch_at(t))
        vw, vh = self.W / z, self.H / z
        px = clamp(cx * sw, vw / 2, sw - vw / 2) + offset[0] * vw
        py = clamp(cy * sh, vh / 2, sh - vh / 2) + offset[1] * vh
        # rung camera
        for ts, s in self.f.shakes:
            if 0 <= t - ts < 0.45:
                a = (1 - (t - ts) / 0.45) * 14 * s / z
                px += a * math.sin(t * 90)
                py += a * math.cos(t * 77)
        return surf, sw, sh, px, py, z

    def _apply_cam(self, ctx, view):
        surf, sw, sh, px, py, z = view
        ctx.translate(self.W / 2, self.H / 2)
        ctx.scale(z, z)
        ctx.translate(-px, -py)

    def draw_world(self, ctx, sid, t, offset=(0, 0)):
        if sid not in self.stage_surf:
            ctx.set_source_rgb(0.95, 0.95, 0.93)
            ctx.paint()
            return None
        view = self._view(sid, t, offset)
        self._cur_view = view
        surf, sw, sh = view[0], view[1], view[2]
        ctx.save()
        self._apply_cam(ctx, view)
        ctx.set_source_surface(surf, 0, 0)
        ctx.get_source().set_filter(cairo.FILTER_GOOD)
        ctx.paint()
        # đối tượng thuộc sân khấu này, sắp theo chiều sâu (y)
        objs = []
        for oid, o in self.f.objects.items():
            if o["born"] - 1e-6 <= t < o["died"]:
                st = obj_state(o, t, self.assets)
                objs.append((st["y"], oid, o, st))
        objs.sort(key=lambda a: a[0])
        tops = {}
        for _, oid, o, st in objs:
            top = self._draw_obj(ctx, o, st, t, sw, sh)
            if top:
                tops[oid] = top
        for (tr, oid, icon) in self.f.reactions:
            if 0 <= t - tr < 1.6 and oid in tops:
                draw_reaction(ctx, icon, t - tr, *tops[oid])
        for (te, ev, tend, g) in self.f.overlays:
            if te <= t < tend:
                self._draw_overlay(ctx, ev, t - te, tend - t, sw, sh, view[5])
        ctx.restore()
        return view

    def _face(self, oid, key):
        if key not in self.faces:
            c = self.cast.get(oid)
            info = None
            if c is not None:
                ov = (c.get("faces") or {}).get(key.split(":", 1)[1] if ":" in key else "base")
                try:
                    info = FACE.locate(self.assets[key], ov)
                except Exception as e:  # không có mặt cũng không sao, chỉ không nhép miệng
                    print(f"[face] {key}: {e}")
                if info and not info.get("face"):
                    info = None
            self.faces[key] = info
        return self.faces[key]

    def _word_at(self, t, si):
        import bisect
        i = bisect.bisect_right(self.word_starts, t) - 1
        if i >= 0:
            a, b, w, wsi = self.f.words[i]
            if wsi == si and t < b + 0.08:
                return w
        return ""

    def _draw_obj(self, ctx, o, st, t, sw, sh):
        key = o["id"]
        if st["expr"] and f'{key}:{st["expr"]}' in self.assets:
            key = f'{key}:{st["expr"]}'
        if key not in self.assets:
            return
        surf = self.img.get(self.assets[key])
        iw, ih = surf.get_width(), surf.get_height()
        h_px = st["size"] * sh  # cao theo tỉ lệ chiều cao sân khấu
        s = h_px / ih
        seed = (hash(o["id"]) % 100) / 10
        breathe = 1 + 0.014 * math.sin(t * 2.6 + seed)
        si = next((i for i, (a, b, _) in enumerate(self.f.scene_spans) if a <= t < b), 0)
        talk, word = 0.0, ""
        if self.speakers[si] == o["id"]:
            f = int(t * FPS)
            talk = self.env[f] if f < len(self.env) else 0
            word = self._word_at(t, si)
        sx = st["sx"] * (1 - 0.02 * talk)
        sy = st["sy"] * breathe * (1 + 0.035 * talk)
        # lắc lư nhẹ quanh bàn chân (sống động, không cứng đơ) + gật gù theo nhịp nói
        lean = st["lean"] + 0.022 * math.sin(t * 1.5 + seed) + 0.03 * talk * math.sin(t * 9 + seed)
        x = st["x"] * sw + st["dx"] * self.W
        y = st["y"] * sh + st["dy"] * self.H
        # quá nhỏ hoặc trong suốt (đầu hiệu ứng pop/cuối exit): bỏ qua, tránh ma trận suy biến làm cairo lỗi
        if st["alpha"] <= 0.01 or abs(s * sx) * iw < 1 or abs(s * sy) * ih < 1:
            return
        if not all(map(math.isfinite, (x, y, sx, sy, s, st["rot"], lean))):
            return
        fc = self._face(o["id"], key)
        mood = (st["expr"] or "").lower()
        self._paint_obj(ctx, surf, iw, ih, s, sx, sy, x, y, st, t, seed, lean, fc, talk, word, mood)
        hh = h_px * sy
        return (x - lean * hh * 0.8 + iw * s * 0.18, y - hh, hh)

    def _paint_obj(self, ctx, surf, iw, ih, s, sx, sy, x, y, st, t, seed, lean=0.0, fc=None,
                   talk=0.0, word="", mood=""):
        ctx.save()
        # bóng đổ dưới chân
        ctx.save()
        ctx.translate(x, y + 4)
        ctx.scale(1, 0.22)
        ctx.arc(0, 0, iw * s * 0.32 * max(0.2, sx), 0, 2 * math.pi)
        ctx.restore()
        ctx.set_source_rgba(0, 0, 0, 0.22 * st["alpha"])
        ctx.fill()
        ctx.translate(x, y)
        ctx.rotate(math.radians(st["rot"]))
        ctx.transform(cairo.Matrix(1, 0, -lean, 1, 0, 0))  # nghiêng phần trên, giữ chân đứng yên
        _sc(ctx, s * sx * (-1 if st["flip"] else 1), s * sy)
        ax, ay = abs(s * sx), abs(s * sy)
        scale_ok = min(ax, ay) / max(ax, ay) > 0.15  # co méo quá mức (spin/squash)
        n = 3 if st["blur"] > 0.2 else 1  # mờ chuyển động khi lướt nhanh
        for k in range(n):
            off = (k - (n - 1) / 2) * st["blur"] * 40 / max(s, 0.01) * (1 if not st["flip"] else -1)
            ctx.set_source_surface(surf, -iw / 2 + off, -ih)
            # FILTER_GOOD với tỉ lệ co méo cực đoan làm cairo "out of memory" (lỗi run 42577402563)
            ctx.get_source().set_filter(cairo.FILTER_GOOD if scale_ok else cairo.FILTER_BILINEAR)
            ctx.paint_with_alpha(st["alpha"] / n * (1.6 if n > 1 else 1))
        if fc and n == 1 and st["alpha"] > 0.6 and h_on_screen(s, sy, ih) > 60:
            ctx.translate(-iw / 2, -ih)
            draw_face(ctx, fc, iw, ih, t, seed, talk, word, mood)
        ctx.restore()

    def _draw_overlay(self, ctx, ev, k, left, sw, sh, z):
        do = ev.get("do")
        fade = clamp(left / 0.3)
        col = _hex(ev.get("color", "#FFFFFF"))
        if do == "arrow":
            (x0, y0), (x1, y1) = ev.get("from", [0.3, 0.5]), ev.get("to", [0.5, 0.5])
            x0, y0, x1, y1 = x0 * sw, y0 * sh, x1 * sw, y1 * sh
            p = ease_out(k / EV_DUR["arrow"])
            bob = 10 * math.sin(k * 6) / z
            ang = math.atan2(y1 - y0, x1 - x0)
            ex, ey = x0 + (x1 - x0) * p + math.cos(ang) * bob, y0 + (y1 - y0) * p + math.sin(ang) * bob
            sx_, sy_ = x0 + math.cos(ang) * bob, y0 + math.sin(ang) * bob
            w = 16 / z * float(ev.get("width", 1))
            for c, lw in (((0.08, 0.08, 0.08), w + 8 / z), (col, w)):
                ctx.set_source_rgba(*c, fade)
                ctx.set_line_width(lw)
                ctx.set_line_cap(cairo.LINE_CAP_ROUND)
                ctx.move_to(sx_, sy_)
                ctx.line_to(ex, ey)
                ctx.stroke()
                hl = 3.2 * w
                ctx.move_to(ex + math.cos(ang) * hl * 0.6, ey + math.sin(ang) * hl * 0.6)
                ctx.line_to(ex + math.cos(ang + 2.5) * hl, ey + math.sin(ang + 2.5) * hl)
                ctx.line_to(ex + math.cos(ang - 2.5) * hl, ey + math.sin(ang - 2.5) * hl)
                ctx.close_path()
                ctx.fill()
        elif do == "line":
            pts = [(a * sw, b * sh) for a, b in ev.get("points", [])]
            if len(pts) < 2:
                return
            p = ease_io(k / float(ev.get("dur", EV_DUR["line"])))
            segs = list(zip(pts, pts[1:]))
            lens = [math.dist(a, b) for a, b in segs]
            total, target = sum(lens), sum(lens) * p
            path, acc = [pts[0]], 0.0
            for (a, b), L in zip(segs, lens):
                if acc + L <= target:
                    path.append(b)
                    acc += L
                else:
                    r = (target - acc) / L if L else 0
                    path.append((a[0] + (b[0] - a[0]) * r, a[1] + (b[1] - a[1]) * r))
                    break
            w = float(ev.get("width", 1)) * 10 / z
            layers = [(col, w * 3.2, 0.18), (col, w * 2, 0.35), ((1, 1, 1), w * 0.8, 1)] if ev.get("glow", True) \
                else [((0.08, 0.08, 0.08), w + 6 / z, 1), (col, w, 1)]
            if ev.get("dashed"):
                ctx.set_dash([w * 2.5, w * 1.8])
            for c, lw, a in layers:
                ctx.set_source_rgba(*c, a * fade)
                ctx.set_line_width(lw)
                ctx.set_line_cap(cairo.LINE_CAP_ROUND)
                ctx.set_line_join(cairo.LINE_JOIN_ROUND)
                ctx.move_to(*path[0])
                for q in path[1:]:
                    ctx.line_to(*q)
                ctx.stroke()
            ctx.set_dash([])
        elif do == "highlight":
            x, y = ev.get("x", 0.5) * sw, ev.get("y", 0.5) * sh
            r = float(ev.get("r", 0.12)) * self.H
            p = ease_out(k / EV_DUR["highlight"])
            ctx.save()
            ctx.translate(x, y)
            ctx.scale(1.25, 1)
            ctx.new_path()
            ctx.arc(0, 0, r, -math.pi / 2, -math.pi / 2 + 2 * math.pi * 1.05 * p)
            ctx.restore()
            c = _hex(ev.get("color", "#FFD400"))
            ctx.set_source_rgba(*c, fade)
            ctx.set_line_width(9 / z)
            ctx.set_line_cap(cairo.LINE_CAP_ROUND)
            ctx.stroke()
        elif do == "label":
            self._label(ctx, ev, k, fade, sw, sh, z)
        elif do == "burst":
            x, y = ev.get("x", 0.5) * sw, ev.get("y", 0.5) * sh
            rnd = random.Random(int(x * 7 + y * 13))
            p = k / EV_DUR["burst"]
            if p >= 1:
                return
            kind = ev.get("kind", "sparkle")
            palette = [(1, 0.83, 0.1), (1, 0.4, 0.45), (0.3, 0.7, 1), (0.4, 0.85, 0.5), (1, 1, 1)]
            for i in range(26):
                a = rnd.uniform(0, 2 * math.pi)
                sp = rnd.uniform(0.6, 1.0) * 0.16 * self.H
                d = ease_out(p) * sp
                gx = x + math.cos(a) * d
                gy = y + math.sin(a) * d + (p * p * 0.08 * self.H if kind == "confetti" else 0)
                ctx.set_source_rgba(*rnd.choice(palette), 1 - p)
                if kind == "confetti":
                    ctx.save()
                    ctx.translate(gx, gy)
                    ctx.rotate(a + p * 8)
                    ctx.rectangle(-7 / z, -4 / z, 14 / z, 8 / z)
                    ctx.restore()
                else:
                    ctx.arc(gx, gy, (7 * (1 - p) + 2) / z, 0, 2 * math.pi)
                ctx.fill()
        elif do == "flow":
            # nhiều bản sao một đạo cụ trôi theo đường (thùng hàng trên sông, xe trên đường...)
            pts = [(a * sw, b * sh) for a, b in ev.get("points", [])]
            key = ev.get("id")
            if len(pts) < 2 or key not in self.assets:
                return
            surf = self.img.get(self.assets[key])
            n = int(ev.get("count", 5))
            size = float(ev.get("size", 0.05)) * sh / surf.get_height()
            segs = list(zip(pts, pts[1:]))
            lens = [math.dist(a, b) for a, b in segs]
            total = sum(lens)
            speed = float(ev.get("speed", 0.25))
            for i in range(n):
                u = (k * speed + i / n) % 1.0
                target, acc = u * total, 0
                for (a, b), L in zip(segs, lens):
                    if acc + L >= target:
                        r = (target - acc) / L if L else 0
                        px, py = a[0] + (b[0] - a[0]) * r, a[1] + (b[1] - a[1]) * r
                        break
                    acc += L
                a_in = clamp(k / 0.4) * clamp(min(u, 1 - u) / 0.08) * fade
                ctx.save()
                ctx.translate(px, py)
                _sc(ctx, size, size)
                ctx.set_source_surface(surf, -surf.get_width() / 2, -surf.get_height() / 2)
                ctx.paint_with_alpha(a_in)
                ctx.restore()

    def _label(self, ctx, ev, k, fade, sw, sh, z):
        text = str(ev.get("text", ""))
        if not text:
            return
        style = ev.get("style", "tag")
        x, y = ev.get("x", 0.5) * sw, ev.get("y", 0.4) * sh
        # giữ nhãn luôn nằm trong khung hình đang quay
        if self._cur_view:
            _, _, _, px, py, vz = self._cur_view
            vw, vh = self.W / vz, self.H / vz
            x = clamp(x, px - vw * 0.38, px + vw * 0.38)
            y = clamp(y, py - vh * 0.40, py + vh * 0.25)
        p = k / EV_DUR["label"]
        s = max(0.0, back(p, 2.2)) if p < 1 else 1.0
        size = float(ev.get("size", 1.0)) * (64 if style == "title" else 46) / z * (SV.H / 1080) ** 0.5
        ctx.save()
        ctx.translate(x, y)
        _sc(ctx, s, s)
        ctx.rotate(math.radians(float(ev.get("rot", -3 if style == "tag" else 0))))
        slant = cairo.FONT_SLANT_ITALIC if style == "map" else cairo.FONT_SLANT_NORMAL
        ctx.select_font_face(SV.FONT if style != "map" else "DejaVu Serif", slant, cairo.FONT_WEIGHT_BOLD)
        ctx.set_font_size(max(0.5, size))
        ext = ctx.text_extents(text)
        tw, th = ext.x_advance, size
        if style == "tag":
            bg = _hex(ev.get("bg", "#FFFFFF"))
            fg = _hex(ev.get("color", "#111111"), (0.07, 0.07, 0.07))
            _rounded(ctx, -tw / 2 - size * 0.45 + 6 / z, -th * 0.95 + 8 / z, tw + size * 0.9, th * 1.5, size * 0.4)
            ctx.set_source_rgba(0, 0, 0, 0.25 * fade)
            ctx.fill()
            _rounded(ctx, -tw / 2 - size * 0.45, -th * 0.95, tw + size * 0.9, th * 1.5, size * 0.4)
            ctx.set_source_rgba(*bg, fade)
            ctx.fill_preserve()
            ctx.set_source_rgba(0.07, 0.07, 0.07, fade)
            ctx.set_line_width(4 / z)
            ctx.stroke()
            ctx.set_source_rgba(*fg, fade)
            ctx.move_to(-tw / 2, th * 0.35)
            ctx.show_text(text)
        else:
            fg = _hex(ev.get("color", "#FFFFFF"))
            ctx.move_to(-tw / 2, th * 0.35)
            ctx.text_path(text)
            ctx.set_source_rgba(0.05, 0.05, 0.05, 0.85 * fade)
            ctx.set_line_width(size * 0.16)
            ctx.set_line_join(cairo.LINE_JOIN_ROUND)
            ctx.stroke_preserve()
            ctx.set_source_rgba(*fg, fade)
            ctx.fill()
        ctx.restore()

    # -- phụ đề 1-3 từ khớp giọng
    def ambience(self, ctx, t):
        """Hạt sáng trôi nhẹ (chiều sâu), viền tối (tập trung mắt), chớp sáng ở từ khoá."""
        if not hasattr(self, "_parts"):
            rnd = random.Random(11)
            self._parts = [(rnd.random(), rnd.random(), rnd.uniform(0.004, 0.014), rnd.uniform(0.2, 1.0),
                            rnd.uniform(0, 6.28)) for _ in range(26)]
            g = cairo.RadialGradient(self.W / 2, self.H * 0.45, min(self.W, self.H) * 0.35,
                                     self.W / 2, self.H * 0.45, max(self.W, self.H) * 0.8)
            g.add_color_stop_rgba(0, 0, 0, 0, 0)
            g.add_color_stop_rgba(1, 0.03, 0.02, 0.08, 0.42)
            self._vig = cairo.ImageSurface(cairo.FORMAT_ARGB32, self.W, self.H)
            c = cairo.Context(self._vig)
            c.set_source(g)
            c.paint()
            self._dot = cairo.ImageSurface(cairo.FORMAT_ARGB32, 64, 64)  # hạt sáng vẽ sẵn
            c = cairo.Context(self._dot)
            g = cairo.RadialGradient(32, 32, 0, 32, 32, 32)
            g.add_color_stop_rgba(0, 1, 0.97, 0.85, 1)
            g.add_color_stop_rgba(1, 1, 0.97, 0.85, 0)
            c.set_source(g)
            c.paint()
        cam = self.f.camera_at(t)
        D = max(self.W, self.H)
        for (px, py, r, depth, ph) in self._parts:
            x = ((px - cam[0] * 0.25 * depth + t * 0.006 * depth) % 1.0) * self.W
            y = ((py - t * 0.012 * depth + math.sin(t * 0.7 + ph) * 0.01) % 1.0) * self.H
            a = 0.10 + 0.08 * math.sin(t * 1.3 + ph)
            rr = r * D * (0.6 + depth)
            ctx.save()
            ctx.translate(x - rr, y - rr)
            _sc(ctx, rr / 32, rr / 32)
            ctx.set_source_surface(self._dot, 0, 0)
            ctx.paint_with_alpha(a)
            ctx.restore()
        ctx.set_source_surface(self._vig, 0, 0)
        ctx.paint()
        pk = self.f.punch_at(t)
        if pk > 0.02:
            ctx.set_source_rgba(1, 1, 1, 0.10 * pk)
            ctx.paint()

    def captions(self, ctx, t):
        """Phụ đề động: từng chữ bật ra đúng lúc nói, chữ đang đọc vàng, từ khoá to + màu nổi + nghiêng."""
        groups = self._groups()
        g = next((g for g in groups if g[0] - 0.05 <= t < g[1]), None)
        if not g:
            return
        words = g[2]
        vertical = self.H > self.W
        base = (74 if vertical else 62) * (self.W / 1080 if vertical else self.H / 1080)
        y = self.H * (0.73 if vertical else 0.86)
        sep = "" if SV.LANG in SV.NO_SPACE_LANGS else " "
        ctx.save()
        ctx.select_font_face(CAPTION_FONT or SV.FONT, cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
        sizes, widths = [], []
        for (a, b, w, wi) in words:
            fs = base * (1.32 if wi in self.f.emph else 1.0)
            ctx.set_font_size(max(0.5, fs))
            sizes.append(fs)
            widths.append(ctx.text_extents(w.upper()).x_advance + (fs * 0.42 if sep else fs * 0.08))
        total = sum(widths)
        maxw = self.W * 0.9
        k = min(1.0, maxw / max(total, 1))
        x = self.W / 2 - total * k / 2
        for (a, b, w, wi), fs, wd in zip(words, sizes, widths):
            if t < a - 0.03:  # chưa nói tới: chưa hiện
                x += wd * k
                continue
            p = (t - a + 0.03) / 0.16
            sc = (0.55 + 0.45 * back(clamp(p), 2.8)) if p < 1 else 1.0
            emph = wi in self.f.emph
            cur = a <= t < b + 0.05
            txt = w.upper()
            ctx.save()
            ctx.set_font_size(max(0.5, fs * k))
            ext = ctx.text_extents(txt)
            cx, cy = x + ext.x_advance / 2, y - (fs * k) * 0.35
            ctx.translate(cx, cy)
            ctx.rotate(math.radians(-4 if emph else 0))
            _sc(ctx, sc * (1.08 if cur else 1), sc * (1.08 if cur else 1))
            ctx.translate(-ext.x_advance / 2, (fs * k) * 0.35)
            # bóng đổ + viền dày
            ctx.move_to(fs * k * 0.05, fs * k * 0.07)
            ctx.text_path(txt)
            ctx.set_source_rgba(0, 0, 0, 0.55)
            ctx.set_line_width(fs * k * 0.24)
            ctx.set_line_join(cairo.LINE_JOIN_ROUND)
            ctx.stroke_preserve()
            ctx.fill()
            ctx.move_to(0, 0)
            ctx.text_path(txt)
            ctx.set_source_rgb(0.05, 0.04, 0.08)
            ctx.set_line_width(fs * k * 0.2)
            ctx.stroke_preserve()
            col = (0.36, 1.0, 0.45) if emph else (1, 0.86, 0.1) if cur else (1, 1, 1)
            ctx.set_source_rgb(*col)
            ctx.fill()
            ctx.restore()
            x += wd * k
        ctx.restore()

    def _groups(self):
        if hasattr(self, "_g"):
            return self._g
        out, cur = [], []
        maxw = 3 if self.H > self.W else 4
        for wi, (a, b, w, si) in enumerate(self.f.words):
            if cur and si != self.f.words[wi - 1][3]:  # không gộp chữ của 2 cảnh
                out.append(cur)
                cur = []
            cur.append((a, b, w, wi))
            chars = sum(len(x[2]) for x in cur)
            if len(cur) >= maxw or chars > 15 or w[-1:] in ",.!?;:…" or wi in self.f.emph:
                out.append(cur)
                cur = []
        if cur:
            out.append(cur)
        self._g = []
        for i, grp in enumerate(out):
            end = out[i + 1][0][0] if i + 1 < len(out) else grp[-1][1] + 0.4
            end = min(end, grp[-1][1] + 0.6)
            self._g.append((grp[0][0], end, grp, i))
        return self._g

    # -- một khung hình hoàn chỉnh
    def frame(self, ctx, t):
        sid, prev, tc, trans = self.f.stage_at(t)
        T = 0.32  # chuyển cảnh
        if prev and t - tc < T / 2 and trans != "cut":
            # nửa đầu: cảnh cũ lướt nhanh ra
            k = (t - tc) / (T / 2)
            if trans == "zoom":
                self._zoom_through(ctx, prev, tc - 1e-3, 1 + k * 0.6, 1 - k * 0.5)
            else:
                self._blurred(ctx, prev, tc - 1e-3, (ease_io(k) * 0.8, 0), 0.7)
        elif prev and t - tc < T and trans != "cut":
            k = (t - tc - T / 2) / (T / 2)
            if trans == "zoom":
                self._zoom_through(ctx, sid, t, 1.4 - 0.4 * ease_out(k), 0.5 + 0.5 * k)
            else:
                self._blurred(ctx, sid, t, (-(1 - ease_out(k)) * 0.8, 0), 0.7 * (1 - k))
        else:
            ctx.save()
            self.draw_world(ctx, sid, t)
            ctx.restore()
        self.ambience(ctx, t)
        self.captions(ctx, t)
        edge = min(t, self.f.total - t)
        if edge < 0.35:
            ctx.set_source_rgba(0, 0, 0, 1 - edge / 0.35)
            ctx.paint()

    def _blurred(self, ctx, sid, t, offset, amount):
        n = 5
        for i in range(n):
            o = (offset[0] + (i - n // 2) * 0.05 * amount, offset[1])
            ctx.push_group()
            self.draw_world(ctx, sid, t, o)
            ctx.pop_group_to_source()
            ctx.paint_with_alpha(1 / (i + 1))

    def _zoom_through(self, ctx, sid, t, zoom, alpha):
        ctx.push_group()
        self.draw_world(ctx, sid, t)
        ctx.pop_group_to_source()
        pat = ctx.get_source()
        m = cairo.Matrix()
        m.translate(self.W / 2, self.H / 2)
        m.scale(1 / zoom, 1 / zoom)
        m.translate(-self.W / 2, -self.H / 2)
        pat.set_matrix(m)
        ctx.paint_with_alpha(clamp(alpha))


def sfx_events(film: Film):
    ev = []
    for t, si, e in film.events:
        kind = SFX_FOR.get(e.get("do"))
        if e.get("do") == "enter":
            kind = {"drop": "thud", "slide_left": "whoosh", "slide_right": "whoosh"}.get(e.get("anim"), "pop")
        if e.get("do") == "camera":
            continue
        if kind and e.get("sfx", True) is not False:
            ev.append((t, e.get("sfx") if isinstance(e.get("sfx"), str) else kind,
                       0.55 if kind == "whoosh" else 0.8))
    for t, oid, icon in film.reactions:
        ev.append((t, "pop", 0.6))
    for t in film.punches:
        ev.append((t, "tick", 0.45))
    # whoosh cho những cú lướt camera lớn
    prev = None
    for (t, x, y, z, d) in film.cameras:
        if prev and (abs(x - prev[0]) + abs(y - prev[1]) > 0.25 or abs(z - prev[2]) > 0.5):
            ev.append((t, "whoosh", 0.5))
        prev = (x, y, z)
    return ev


def render(film_json, timings, assets, voice_wav, out_mp4, music=None, cwd=None, preview_dir=None,
           preview_only=False):
    """Dựng video (hoặc chỉ ảnh xem trước mỗi cảnh nếu preview_only)."""
    from scene_video import mouth_envelope
    import sfx

    global CAPTION_FONT
    film = Film(film_json, timings, assets)
    W, H = SV.W, SV.H
    fams = subprocess.run(["fc-list", ":", "family"], capture_output=True, text=True).stdout
    CAPTION_FONT = next((f"{SV.FONT} {w}" for w in ("Black", "ExtraBold") if f"{SV.FONT} {w}" in fams), None)
    nframes = int(film.total * FPS)
    env = mouth_envelope(voice_wav, nframes) if voice_wav and Path(voice_wav).exists() else [0] * nframes
    r = Renderer(film, assets, env)
    surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, W, H)
    ctx = cairo.Context(surf)

    if preview_dir:
        Path(preview_dir).mkdir(parents=True, exist_ok=True)
        files = []
        for i, (a, b, _) in enumerate(film.scene_spans):
            for j, frac in enumerate((0.3, 0.8)):
                t = a + (b - a) * frac
                ctx.save()
                ctx.set_source_rgb(0, 0, 0)
                ctx.paint()
                r.frame(ctx, t)
                ctx.restore()
                f = Path(preview_dir) / f"scene_{i + 1:02d}_{j + 1}.png"
                surf.write_to_png(str(f))
                files.append(f)
        if preview_only:
            return files

    work = Path(cwd or ".")
    sfx_wav = work / "sfx.wav"
    sfx.build_track(sfx_events(film), film.total, sfx_wav)
    vf = "null"
    if not music and film_json.get("music", "upbeat") != "none":
        import music as MUSIC
        music = work / "music.wav"
        MUSIC.build(film.total, music, film_json.get("music", "upbeat"))
    inputs = ["-i", str(Path(voice_wav).resolve()), "-i", str(sfx_wav.resolve())]
    mix = "[1:a]volume=1.0[v];[2:a]volume=0.9[s];[v][s]amix=inputs=2:duration=first:normalize=0"
    if music:
        inputs += ["-stream_loop", "-1", "-i", str(Path(music).resolve())]
        # nhạc nền tự nhỏ lại khi có lời (sidechain ducking)
        mix = ("[1:a]volume=1.0,asplit=2[v][vk];[2:a]volume=0.9[s];[3:a]volume=0.42[m0];"
               "[m0][vk]sidechaincompress=threshold=0.02:ratio=6:attack=15:release=350[m];"
               "[v][s][m]amix=inputs=3:duration=first:normalize=0")
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "bgra",
           "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-", *inputs,
           "-filter_complex", f"[0:v]{vf}[vo];{mix}[a]", "-map", "[vo]", "-map", "[a]",
           "-c:v", "libx264", "-preset", "medium", "-crf", "19", "-pix_fmt", "yuv420p",
           "-c:a", "aac", "-b:a", "192k", "-shortest", "-movflags", "+faststart",
           str(Path(out_mp4).resolve())]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, cwd=cwd)
    prev = None
    last_good = None
    errors = 0

    def draw(surf, t, fast):
        ctx = cairo.Context(surf)  # context mới mỗi khung: lỗi cairo (dính) không lan sang khung sau
        ctx.set_source_rgb(0, 0, 0)
        ctx.paint()
        if fast:  # camera lướt nhanh → trộn 3 khung phụ để có mờ chuyển động
            for i, dt in enumerate((0.0, -0.33 / FPS, -0.66 / FPS)):
                ctx.push_group()
                r.frame(ctx, max(0.0, t + dt))
                ctx.pop_group_to_source()
                ctx.paint_with_alpha(1 / (i + 1))
        else:
            r.frame(ctx, t)

    for fi in range(nframes):
        t = fi / FPS
        cam = film.camera_at(t)
        fast = prev is not None and (abs(cam[0] - prev[0]) + abs(cam[1] - prev[1])) * 1.5 + abs(cam[2] - prev[2]) * 0.4 > 0.012
        try:
            draw(surf, t, fast)
        except cairo.Error as e:
            # một khung lỗi không được làm hỏng cả video: thử lệch thời gian một chút, không được thì lặp khung trước
            errors += 1
            print(f"[motion] khung {t:.3f}s lỗi cairo: {e} -> thử lại")
            surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, W, H)
            try:
                draw(surf, t + 0.004, False)
            except cairo.Error:
                surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, W, H)
                if last_good is not None:
                    surf.get_data()[:] = last_good
            if errors > 300:
                raise
        prev = cam
        surf.flush()
        last_good = bytes(surf.get_data())
        proc.stdin.write(last_good)
        if fi % (FPS * 10) == 0:
            print(f"[motion] {t:.0f}/{film.total:.0f}s")
    proc.stdin.close()
    if proc.wait() != 0:
        raise SystemExit("ffmpeg lỗi khi dựng video")
    return out_mp4
