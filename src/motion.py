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

FPS = 30
EV_DUR = {"camera": 0.9, "move": 0.8, "enter": 0.45, "exit": 0.4, "action": 0.6, "expr": 0.25,
          "arrow": 0.5, "line": 1.1, "highlight": 0.6, "label": 0.35, "burst": 0.9, "flow": 3.0}
SFX_FOR = {"enter": "pop", "exit": "whoosh", "expr": "pop", "burst": "ding", "label": "tick",
           "highlight": "tick", "arrow": "whoosh", "line": "whoosh", "stage": "whoosh", "shake": "thud"}


# ------------------------------------------------------------------ easing ---

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
            p = Path(path)
            if blur or p.suffix.lower() != ".png":
                im = Image.open(p).convert("RGBA")
                if blur:
                    im = im.filter(ImageFilter.GaussianBlur(blur))
                tmp = p.with_name(p.stem + f"_b{blur}.png")
                im.save(tmp)
                p = tmp
            self.cache[key] = cairo.ImageSurface.create_from_png(str(p))
        return self.cache[key]


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
        self.events.sort(key=lambda e: (e[0], 0 if e[2].get("do") == "stage" else 1))
        self._build_tracks()

    def _build_tracks(self):
        """Mỗi đối tượng: danh sách sự kiện theo thời gian. Đổi sân khấu thì xoá sân khấu cũ."""
        self.objects = {}   # oid -> dict(kind, events[], born, died)
        self.stage_changes = []
        self.cameras = []   # (t, x, y, zoom, dur)
        self.shakes = []
        self.overlays = []  # arrow/line/highlight/label/burst: (t, ev, end_t)
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
            elif do in ("enter", "move", "exit", "action", "expr"):
                oid = f'{ev.get("id")}#{gen}'
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
          "dx": 0.0, "dy": 0.0, "flip": False, "expr": None, "blur": 0.0}
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
                st["rot"] += math.sin(k / d * math.pi) * (6 if tx > x0 else -6)
                st["blur"] = max(st["blur"], math.sin(k / d * math.pi) * 0.6)
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
            d = float(ev.get("dur", EV_DUR["action"]))
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
                    st["dy"] -= 0.16 * w
                    st["sy"] *= 1 + 0.12 * math.sin(p * math.pi * 2)
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

    # -- camera
    def _view(self, sid, t, offset=(0, 0)):
        surf = self.img.get(self.stage_surf[sid], blur=6 if self.dof.get(sid) else 0)
        sw, sh = surf.get_width(), surf.get_height()
        cx, cy, z = self.f.camera_at(t)
        zmin = max(self.W / sw, self.H / sh) * 1.001
        z = max(z, zmin)
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
        for _, oid, o, st in objs:
            self._draw_obj(ctx, o, st, t, sw, sh)
        for (te, ev, tend, g) in self.f.overlays:
            if te <= t < tend:
                self._draw_overlay(ctx, ev, t - te, tend - t, sw, sh, view[5])
        ctx.restore()
        return view

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
        # thở / nhún khi đang nói
        seed = (hash(o["id"]) % 100) / 10
        breathe = 1 + 0.014 * math.sin(t * 2.6 + seed)
        si = next((i for i, (a, b, _) in enumerate(self.f.scene_spans) if a <= t < b), 0)
        talk = 0.0
        if self.speakers[si] == o["id"]:
            f = int(t * FPS)
            talk = self.env[f] if f < len(self.env) else 0
        sx = st["sx"] * (1 - 0.025 * talk)
        sy = st["sy"] * breathe * (1 + 0.05 * talk)
        x = st["x"] * sw + st["dx"] * self.W
        y = st["y"] * sh + st["dy"] * self.H
        # quá nhỏ hoặc trong suốt (đầu hiệu ứng pop/cuối exit): bỏ qua, tránh ma trận suy biến làm cairo lỗi
        if st["alpha"] <= 0.01 or abs(s * sx) * iw < 1 or abs(s * sy) * ih < 1:
            return
        if not all(map(math.isfinite, (x, y, sx, sy, s, st["rot"]))):
            return
        self._paint_obj(ctx, surf, iw, ih, s, sx, sy, x, y, st, t, seed)

    def _paint_obj(self, ctx, surf, iw, ih, s, sx, sy, x, y, st, t, seed):
        sway = 1.2 * math.sin(t * 1.7 + seed)
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
        ctx.rotate(math.radians(st["rot"] + sway))
        ctx.scale(s * sx * (-1 if st["flip"] else 1), s * sy)
        ax, ay = abs(s * sx), abs(s * sy)
        scale_ok = min(ax, ay) / max(ax, ay) > 0.15  # co méo quá mức (spin/squash)
        n = 3 if st["blur"] > 0.2 else 1  # mờ chuyển động khi lướt nhanh
        for k in range(n):
            off = (k - (n - 1) / 2) * st["blur"] * 40 / max(s, 0.01) * (1 if not st["flip"] else -1)
            ctx.set_source_surface(surf, -iw / 2 + off, -ih)
            # FILTER_GOOD với tỉ lệ co méo cực đoan làm cairo "out of memory" (lỗi run 42577402563)
            ctx.get_source().set_filter(cairo.FILTER_GOOD if scale_ok else cairo.FILTER_BILINEAR)
            ctx.paint_with_alpha(st["alpha"] / n * (1.6 if n > 1 else 1))
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
                ctx.scale(size, size)
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
        ctx.scale(s, s)
        ctx.rotate(math.radians(float(ev.get("rot", -3 if style == "tag" else 0))))
        slant = cairo.FONT_SLANT_ITALIC if style == "map" else cairo.FONT_SLANT_NORMAL
        ctx.select_font_face(SV.FONT if style != "map" else "DejaVu Serif", slant, cairo.FONT_WEIGHT_BOLD)
        ctx.set_font_size(size)
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
    def captions(self, ctx, t):
        groups = self._groups()
        g = next((g for g in groups if g[0] <= t < g[1]), None)
        if not g:
            return
        start, end, words, cur_idx = g[0], g[1], g[2], g[3]
        cur = next((i for i, (a, b, w) in enumerate(words) if a <= t < b), None)
        vertical = self.H > self.W
        size = (64 if vertical else 58) * (self.W / 1080 if vertical else self.H / 1080)
        y = self.H * (0.74 if vertical else 0.87)
        p = (t - start) / 0.12
        s = 0.8 + 0.2 * back(p, 2.5) if p < 1 else 1.0
        ctx.save()
        ctx.select_font_face(SV.FONT, cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
        ctx.set_font_size(size)
        sep = "" if SV.LANG in SV.NO_SPACE_LANGS else " "
        parts = [w for _, _, w in words]
        widths = [ctx.text_extents(w + sep).x_advance for w in parts]
        total = sum(widths)
        ctx.translate(self.W / 2, y)
        ctx.scale(s, s)
        x = -total / 2
        for i, (w, wd) in enumerate(zip(parts, widths)):
            ctx.move_to(x, 0)
            ctx.text_path(w)
            ctx.set_source_rgba(0, 0, 0, 0.9)
            ctx.set_line_width(size * 0.2)
            ctx.set_line_join(cairo.LINE_JOIN_ROUND)
            ctx.stroke_preserve()
            ctx.set_source_rgb(*((1, 0.86, 0.1) if i == cur else (1, 1, 1)))
            ctx.fill()
            x += wd
        ctx.restore()

    def _groups(self):
        if hasattr(self, "_g"):
            return self._g
        out, cur = [], []
        maxw = 3 if self.H > self.W else 4
        for a, b, w, si in self.f.words:
            cur.append((a, b, w))
            chars = sum(len(x[2]) for x in cur)
            if len(cur) >= maxw or chars > 16 or w[-1:] in ",.!?;:…" :
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

    film = Film(film_json, timings, assets)
    W, H = SV.W, SV.H
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
    inputs = ["-i", str(Path(voice_wav).resolve()), "-i", str(sfx_wav.resolve())]
    mix = "[1:a]volume=1.0[v];[2:a]volume=0.9[s];[v][s]amix=inputs=2:duration=first:normalize=0"
    if music:
        inputs += ["-stream_loop", "-1", "-i", str(music)]
        mix = ("[1:a]volume=1.0[v];[2:a]volume=0.9[s];[3:a]volume=0.10[m];"
               "[v][s][m]amix=inputs=3:duration=first:normalize=0")
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "bgra",
           "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-", *inputs,
           "-filter_complex", f"[0:v]{vf}[vo];{mix}[a]", "-map", "[vo]", "-map", "[a]",
           "-c:v", "libx264", "-preset", "medium", "-crf", "19", "-pix_fmt", "yuv420p",
           "-c:a", "aac", "-b:a", "192k", "-shortest", "-movflags", "+faststart",
           str(Path(out_mp4).resolve())]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, cwd=cwd)
    prev = None
    for fi in range(nframes):
        t = fi / FPS
        ctx.save()
        ctx.set_source_rgb(0, 0, 0)
        ctx.paint()
        # camera lướt nhanh → trộn 3 khung phụ để có mờ chuyển động
        cam = film.camera_at(t)
        fast = prev is not None and (abs(cam[0] - prev[0]) + abs(cam[1] - prev[1])) * 1.5 + abs(cam[2] - prev[2]) * 0.4 > 0.012
        if fast:
            for i, dt in enumerate((0.0, -0.33 / FPS, -0.66 / FPS)):
                ctx.push_group()
                r.frame(ctx, max(0.0, t + dt))
                ctx.pop_group_to_source()
                ctx.paint_with_alpha(1 / (i + 1))
        else:
            r.frame(ctx, t)
        ctx.restore()
        prev = cam
        surf.flush()
        proc.stdin.write(bytes(surf.get_data()))
        if fi % (FPS * 10) == 0:
            print(f"[motion] {t:.0f}/{film.total:.0f}s")
    proc.stdin.close()
    if proc.wait() != 0:
        raise SystemExit("ffmpeg lỗi khi dựng video")
    return out_mp4
