"""Nhân vật người que vẽ bằng vector (cairo), có khung xương để tạo chuyển động mượt.

Quy ước góc (độ): tay/chân 0 = buông thẳng xuống, dương = giơ ra phía ngoài.
"l" = bên trái màn hình, "r" = bên phải màn hình (nhân vật nhìn thẳng vào người xem).
"""
import math
import random

# ---------------------------------------------------------------- tư thế ---

BASE = dict(
    lean=0.0, tilt=0.0, bob=0.0,  # nghiêng người, nghiêng đầu, nhún (px)
    ls=18.0, le=8.0, rs=18.0, re=8.0,  # vai/khuỷu trái, phải
    lh=10.0, lk=0.0, rh=10.0, rk=0.0,  # hông/gối trái, phải
    lpoint=0.0, rpoint=0.0,  # 1 = bàn tay chỉ ngón trỏ
    gx=0.0, gy=0.0,  # hướng mắt nhìn (-1..1)
)


def P(**kw):
    p = dict(BASE)
    p.update(kw)
    return p


# Mỗi hành động là chuỗi keyframe lặp lại: (thời gian giây, tư thế).
ACTIONS = {
    "idle": [(0, P()), (1.6, P(ls=22, rs=22, bob=-4, tilt=3)), (3.2, P())],
    "talk": [
        (0, P(ls=35, le=55, rs=20, re=10)),
        (0.9, P(ls=20, le=10, rs=40, re=60, tilt=-4, bob=-3)),
        (1.8, P(ls=45, le=70, rs=45, re=70, tilt=3)),
        (2.7, P(ls=35, le=55, rs=20, re=10)),
    ],
    "explain": [
        (0, P(ls=20, rs=60, re=50, lean=-2)),
        (0.8, P(ls=24, rs=75, re=35, tilt=-5, bob=-3)),
        (1.6, P(ls=20, rs=60, re=50, lean=-2)),
    ],
    "wave": [
        (0, P(rs=150, re=25, tilt=-5)),
        (0.3, P(rs=150, re=-25, tilt=-3, bob=-2)),
        (0.6, P(rs=150, re=25, tilt=-5)),
    ],
    "point": [
        (0, P(rs=100, re=0, rpoint=1, lean=4, gx=0.8, tilt=-4)),
        (1.0, P(rs=106, re=-4, rpoint=1, lean=5, gx=0.8, tilt=-6, bob=-3)),
        (2.0, P(rs=100, re=0, rpoint=1, lean=4, gx=0.8, tilt=-4)),
    ],
    "point_up": [
        (0, P(rs=135, re=25, rpoint=1, tilt=-6, gy=-0.8, gx=0.4)),
        (0.9, P(rs=130, re=32, rpoint=1, tilt=-8, gy=-0.8, gx=0.4, bob=-4)),
        (1.8, P(rs=135, re=25, rpoint=1, tilt=-6, gy=-0.8, gx=0.4)),
    ],
    "think": [
        (0, P(rs=40, re=150, rpoint=1, ls=30, le=95, tilt=10, gx=-0.6, gy=-0.9)),
        (1.5, P(rs=42, re=148, rpoint=1, ls=30, le=95, tilt=14, gx=-0.7, gy=-0.9, bob=-2)),
        (3.0, P(rs=40, re=150, rpoint=1, ls=30, le=95, tilt=10, gx=-0.6, gy=-0.9)),
    ],
    "excited": [
        (0, P(ls=150, le=15, rs=150, re=15, bob=0, lh=14, rh=14)),
        (0.25, P(ls=160, le=-10, rs=160, re=-10, bob=-45, lh=25, lk=-30, rh=25, rk=-30)),
        (0.5, P(ls=150, le=15, rs=150, re=15, bob=0, lh=14, rh=14)),
    ],
    "shrug": [
        (0, P(ls=35, le=80, rs=35, re=80, tilt=8)),
        (0.7, P(ls=45, le=95, rs=45, re=95, tilt=12, bob=-8)),
        (1.4, P(ls=35, le=80, rs=35, re=80, tilt=8)),
    ],
    "sad": [
        (0, P(ls=6, rs=6, tilt=12, lean=4, gy=0.8, bob=6)),
        (2.0, P(ls=8, rs=8, tilt=16, lean=5, gy=0.8, bob=8)),
        (4.0, P(ls=6, rs=6, tilt=12, lean=4, gy=0.8, bob=6)),
    ],
    "surprised": [
        (0, P(ls=140, le=-60, rs=140, re=-60, bob=-6, lh=16, rh=16)),
        (0.4, P(ls=145, le=-65, rs=145, re=-65, bob=-10, lh=16, rh=16, tilt=3)),
        (0.8, P(ls=140, le=-60, rs=140, re=-60, bob=-6, lh=16, rh=16)),
    ],
    "walk": [
        (0, P(lh=6, rh=6, ls=10, rs=30, le=20, re=30)),
        (0.25, P(lh=30, lk=-60, rh=4, ls=20, rs=20, bob=-10)),
        (0.5, P(lh=6, rh=6, ls=30, rs=10, le=30, re=20)),
        (0.75, P(rh=30, rk=-60, lh=4, ls=20, rs=20, bob=-10)),
        (1.0, P(lh=6, rh=6, ls=10, rs=30, le=20, re=30)),
    ],
}
NAMES = sorted(ACTIONS)


def _ease(t):
    return 0.5 - 0.5 * math.cos(math.pi * t)


def blend(a, b, k):
    return {key: a[key] + (b[key] - a[key]) * k for key in a}


def pose_at(action, t, seed=0):
    keys = ACTIONS.get(action, ACTIONS["idle"])
    period = keys[-1][0]
    t = t % period
    for (t0, p0), (t1, p1) in zip(keys, keys[1:]):
        if t0 <= t <= t1:
            k = _ease((t - t0) / (t1 - t0))
            pose = blend(p0, p1, k)
            break
    else:
        pose = dict(keys[0][1])
    # thở nhẹ, luôn có để nhân vật không bị "đơ"
    pose["bob"] += 2.5 * math.sin(t * 2.4 + seed)
    pose["tilt"] += 1.5 * math.sin(t * 1.3 + seed)
    return pose


# ---------------------------------------------------------------- vẽ ---

STYLES = {
    # giống hình mẫu nét đen cổ điển: đầu tròn trắng, tay chân nét đen, bàn tay/giày tròn
    "doodle": dict(limb="#111111", outline="#111111", fill="#FFFFFF", shirt=None, lw=10),
    # giống hình mẫu áo xanh: tay chân trắng viền đen, áo phông màu
    "shirt": dict(limb="#FFFFFF", outline="#111111", fill="#FFFFFF", shirt="#2F80ED", lw=12),
}

L_TORSO, L_UP, L_LO, L_TH, L_SH, HEAD_R = 150, 82, 78, 98, 96, 72


def _hex(c):
    c = c.lstrip("#")
    return tuple(int(c[i:i + 2], 16) / 255 for i in (0, 2, 4))


def _dir(angle_deg, side):
    a = math.radians(angle_deg)
    return (side * math.sin(a), math.cos(a))


def _limb(ctx, st, pts, width):
    """Vẽ một chi gồm nhiều điểm; kiểu shirt có viền đen bao ngoài."""
    ctx.set_line_cap(1)  # ROUND
    ctx.set_line_join(1)
    passes = [(st["outline"], width + 8), (st["limb"], width)] if st["limb"] != st["outline"] else [(st["limb"], width)]
    for color, w in passes:
        ctx.set_source_rgb(*_hex(color))
        ctx.set_line_width(w)
        ctx.move_to(*pts[0])
        for p in pts[1:]:
            ctx.line_to(*p)
        ctx.stroke()


def _circle(ctx, st, x, y, r, lw=7):
    ctx.arc(x, y, r, 0, 2 * math.pi)
    ctx.set_source_rgb(*_hex(st["fill"]))
    ctx.fill_preserve()
    ctx.set_source_rgb(*_hex(st["outline"]))
    ctx.set_line_width(lw)
    ctx.stroke()


def _hand(ctx, st, elbow, wrist, point):
    dx, dy = wrist[0] - elbow[0], wrist[1] - elbow[1]
    n = math.hypot(dx, dy) or 1
    ux, uy = dx / n, dy / n
    cx, cy = wrist[0] + ux * 6, wrist[1] + uy * 6
    if point > 0.5:
        _limb(ctx, st, [(cx, cy), (cx + ux * 34, cy + uy * 34)], 9)
    _circle(ctx, st, cx, cy, 17, 6)


def _foot(ctx, st, knee, ankle, side):
    ctx.save()
    ctx.translate(ankle[0] + side * 12, ankle[1] + 6)
    ctx.scale(1.0, 0.62)
    ctx.arc(0, 0, 26, 0, 2 * math.pi)
    ctx.restore()
    ctx.set_source_rgb(*_hex(st["fill"]))
    ctx.fill_preserve()
    ctx.set_source_rgb(*_hex(st["outline"]))
    ctx.set_line_width(6)
    ctx.stroke()


def draw_character(ctx, pose, x, y, scale=1.0, style="doodle", face=None):
    """Vẽ nhân vật, (x, y) là vị trí bàn chân trên mặt đất."""
    st = STYLES.get(style, STYLES["doodle"])
    face = face or {}
    p = pose
    ctx.save()
    ctx.translate(x, y)
    ctx.scale(scale, scale)

    # bóng dưới chân
    lift = max(0.0, -p["bob"])
    ctx.save()
    ctx.scale(1, 0.18)
    ctx.arc(0, 10 / 0.18, 110 - lift * 0.8, 0, 2 * math.pi)
    ctx.restore()
    ctx.set_source_rgba(0, 0, 0, 0.16)
    ctx.fill()

    hip = (0.0, -(L_TH + L_SH + 18) + p["bob"])
    a = math.radians(p["lean"])
    neck = (hip[0] + math.sin(a) * L_TORSO, hip[1] - math.cos(a) * L_TORSO)
    shoulder = (neck[0] - math.sin(a) * 16, neck[1] + math.cos(a) * 16)
    if st["shirt"]:  # áo: vai nằm ở hai góc trên của áo
        down = 26
        base = (neck[0] - math.sin(a) * down, neck[1] + math.cos(a) * down)
        off = (math.cos(a) * 36, math.sin(a) * 36)
        sh_l, sh_r = (base[0] - off[0], base[1] - off[1]), (base[0] + off[0], base[1] + off[1])
    else:
        sh_l = sh_r = shoulder

    def chain(origin, a1, a2, l1, l2, side):
        d1 = _dir(a1, side)
        j1 = (origin[0] + d1[0] * l1, origin[1] + d1[1] * l1)
        d2 = _dir(a1 + a2, side)
        j2 = (j1[0] + d2[0] * l2, j1[1] + d2[1] * l2)
        return j1, j2

    lk, la = chain(hip, p["lh"], p["lk"], L_TH, L_SH, -1)
    rk, ra = chain(hip, p["rh"], p["rk"], L_TH, L_SH, 1)
    le, lw = chain(sh_l, p["ls"] - p["lean"], p["le"], L_UP, L_LO, -1)
    re, rw = chain(sh_r, p["rs"] + p["lean"], p["re"], L_UP, L_LO, 1)

    lwid = st["lw"]
    # chân
    for knee, ankle, side in ((lk, la, -1), (rk, ra, 1)):
        _limb(ctx, st, [hip, knee, ankle], lwid)
        _foot(ctx, st, knee, ankle, side)

    # thân
    if st["shirt"]:
        _torso_shirt(ctx, st, hip, neck, a)
    else:
        _limb(ctx, st, [hip, neck], lwid)

    # tay
    for sh, el, wr, pt in ((sh_l, le, lw, p["lpoint"]), (sh_r, re, rw, p["rpoint"])):
        _limb(ctx, st, [sh, el, wr], lwid - 1)
        _hand(ctx, st, el, wr, pt)
        if st["shirt"]:  # tay áo ngắn
            mx, my = sh[0] + (el[0] - sh[0]) * 0.42, sh[1] + (el[1] - sh[1]) * 0.42
            _limb(ctx, dict(st, limb=st["shirt"]), [sh, (mx, my)], 28)

    # đầu
    ht = math.radians(p["tilt"] + p["lean"])
    head = (neck[0] + math.sin(ht) * (HEAD_R - 4), neck[1] - math.cos(ht) * (HEAD_R - 4))
    _head(ctx, st, head, p, face)
    ctx.restore()


def _torso_shirt(ctx, st, hip, neck, a):
    ctx.save()
    ctx.translate(*hip)
    ctx.rotate(a)
    h = L_TORSO + 14
    w_top, w_bot = 92, 78
    ctx.move_to(-w_bot / 2, 14)
    ctx.line_to(-w_top / 2, -h + 22)
    ctx.curve_to(-w_top / 2, -h, -w_top / 2 + 10, -h, -w_top / 2 + 22, -h)
    ctx.line_to(w_top / 2 - 22, -h)
    ctx.curve_to(w_top / 2 - 10, -h, w_top / 2, -h, w_top / 2, -h + 22)
    ctx.line_to(w_bot / 2, 14)
    ctx.close_path()
    ctx.set_source_rgb(*_hex(st["shirt"]))
    ctx.fill_preserve()
    ctx.set_source_rgb(*_hex(st["outline"]))
    ctx.set_line_width(6)
    ctx.stroke()
    ctx.restore()


EXPR = {
    # (độ cong miệng -1..1, nhướng mày, góc mày)
    "happy": (0.8, 0, 0),
    "neutral": (0.25, 0, 0),
    "excited": (1.0, -6, 0),
    "surprised": (0.0, -12, 0),
    "sad": (-0.7, 0, -14),
    "thinking": (0.0, -4, 10),
    "angry": (-0.4, 4, 18),
}


def _head(ctx, st, c, p, face):
    x, y = c
    ctx.save()
    ctx.translate(x, y)
    ctx.rotate(math.radians(p["tilt"]))
    _circle(ctx, st, 0, 0, HEAD_R, 8)

    # tóc: vài nét xoăn trên đỉnh đầu
    ctx.set_source_rgb(*_hex(st["outline"]))
    ctx.set_line_width(6)
    ctx.set_line_cap(1)
    for dx, h in ((-10, 30), (4, 38), (18, 28)):
        ctx.move_to(dx, -HEAD_R + 2)
        ctx.curve_to(dx - 4, -HEAD_R - h * 0.5, dx + 10, -HEAD_R - h * 0.8, dx + 8, -HEAD_R - h)
        ctx.stroke()

    expr = EXPR.get(face.get("expression", "happy"), EXPR["happy"])
    curve, brow_y, brow_a = expr
    blink = face.get("blink", 0.0)
    gx, gy = p["gx"] * 7, p["gy"] * 6
    eye_h = 13 * (1 - 0.9 * blink)
    if face.get("expression") == "surprised":
        eye_h *= 1.25

    for side in (-1, 1):
        ex, ey = side * 25 + gx, -10 + gy
        ctx.save()
        ctx.translate(ex, ey)
        ctx.scale(1, max(eye_h, 1.2) / 9)
        ctx.arc(0, 0, 9, 0, 2 * math.pi)
        ctx.restore()
        ctx.set_source_rgb(0.07, 0.07, 0.07)
        ctx.fill()
        if blink < 0.5:
            ctx.arc(ex + 3, ey - 4, 3, 0, 2 * math.pi)
            ctx.set_source_rgb(1, 1, 1)
            ctx.fill()
        # lông mày
        if brow_y or brow_a:
            ctx.set_source_rgb(0.07, 0.07, 0.07)
            ctx.set_line_width(5)
            by = -34 + brow_y
            ctx.move_to(side * 14, by + side * 0 + (brow_a * 0.3))
            ctx.line_to(side * 36, by - brow_a * 0.3)
            ctx.stroke()

    # má hồng
    for side in (-1, 1):
        ctx.save()
        ctx.translate(side * 44, 14)
        ctx.scale(1, 0.6)
        ctx.arc(0, 0, 11, 0, 2 * math.pi)
        ctx.restore()
        ctx.set_source_rgba(1, 0.45, 0.5, 0.35)
        ctx.fill()

    # miệng: mở theo âm lượng giọng đọc
    mo = face.get("mouth", 0.0)
    ctx.set_source_rgb(0.07, 0.07, 0.07)
    if face.get("expression") == "surprised":
        ctx.save()
        ctx.translate(0, 28)
        ctx.scale(1, 1.2 + mo * 0.4)
        ctx.arc(0, 0, 10, 0, 2 * math.pi)
        ctx.restore()
        ctx.fill()
    elif mo > 0.12:
        w = 22 + 6 * curve
        hgt = 6 + 22 * mo
        top = 22 - 4 * curve
        ctx.move_to(-w, top)
        ctx.curve_to(-w, top + hgt * 1.3, w, top + hgt * 1.3, w, top)
        ctx.curve_to(w * 0.5, top + 3 * curve, -w * 0.5, top + 3 * curve, -w, top)
        ctx.fill_preserve()
        ctx.set_line_width(4)
        ctx.stroke()
        # lưỡi
        ctx.save()
        ctx.translate(0, top + hgt * 0.85)
        ctx.scale(1, 0.5)
        ctx.arc(0, 0, w * 0.45, 0, 2 * math.pi)
        ctx.restore()
        ctx.set_source_rgb(0.95, 0.4, 0.45)
        ctx.fill()
    else:
        ctx.set_line_width(5.5)
        ctx.move_to(-20, 26 - 6 * curve)
        ctx.curve_to(-8, 26 + 14 * curve, 8, 26 + 14 * curve, 20, 26 - 6 * curve)
        ctx.stroke()
    ctx.restore()


class Blinker:
    """Chớp mắt ngẫu nhiên mỗi 2-4 giây."""

    def __init__(self, seed=1):
        self.rnd = random.Random(seed)
        self.next = 1.0

    def value(self, t):
        if t > self.next + 0.18:
            self.next = t + self.rnd.uniform(2.0, 4.2)
        d = t - self.next
        if 0 <= d <= 0.18:
            return math.sin(math.pi * d / 0.18)
        return 0.0
