"""Âm thanh hiệu ứng tự tạo (không cần file bản quyền): whoosh, pop, ding, thud, swoosh nhỏ."""
import math
import random
import wave
from array import array

SR = 44100


def _env(n, attack, decay_pow=2.0):
    a = max(1, int(n * attack))
    return [min(1.0, i / a) * (1 - i / n) ** decay_pow for i in range(n)]


def _whoosh(dur=0.45, seed=1):
    rnd = random.Random(seed)
    n = int(SR * dur)
    out, lp = [], 0.0
    for i in range(n):
        k = i / n
        # nhiễu lọc thông thấp, tần số cắt tăng rồi giảm → tiếng gió lướt
        cut = 0.02 + 0.25 * math.sin(math.pi * k)
        lp += cut * (rnd.uniform(-1, 1) - lp)
        out.append(lp * math.sin(math.pi * k) ** 1.5 * 2.2)
    return out


def _pop(dur=0.12):
    n = int(SR * dur)
    out = []
    for i in range(n):
        t = i / SR
        f = 900 * (1 - i / n) + 300
        out.append(math.sin(2 * math.pi * f * t) * (1 - i / n) ** 3)
    return out


def _ding(dur=0.6):
    n = int(SR * dur)
    return [(math.sin(2 * math.pi * 1320 * i / SR) * 0.6 + math.sin(2 * math.pi * 1980 * i / SR) * 0.3)
            * math.exp(-6 * i / n) for i in range(n)]


def _thud(dur=0.25):
    n = int(SR * dur)
    return [math.sin(2 * math.pi * (110 - 60 * i / n) * i / SR) * (1 - i / n) ** 2 for i in range(n)]


def _riser(dur=0.8, seed=9):
    """Tiếng dâng lên (nhiễu + âm cao dần) dẫn vào một cú đập/burst."""
    rnd = random.Random(seed)
    n = int(SR * dur)
    out, lp, ph = [], 0.0, 0.0
    for i in range(n):
        k = i / n
        lp += (0.02 + 0.3 * k) * (rnd.uniform(-1, 1) - lp)
        ph += 2 * math.pi * (300 + 900 * k * k) / SR
        out.append((lp * 1.6 + 0.25 * math.sin(ph)) * k ** 2.2)
    return out


def _tick(dur=0.05):
    n = int(SR * dur)
    rnd = random.Random(3)
    return [rnd.uniform(-1, 1) * (1 - i / n) ** 4 for i in range(n)]


SOUNDS = {}


def sound(kind):
    if kind not in SOUNDS:
        SOUNDS[kind] = {"whoosh": _whoosh, "pop": _pop, "ding": _ding, "thud": _thud,
                        "tick": _tick, "riser": _riser}.get(kind, _pop)()
    return SOUNDS[kind]


def _pitched(x, ratio):
    """Đổi cao độ nhẹ (đọc nhanh/chậm hơn) để có bản thứ hai của cùng một tiếng."""
    m = int(len(x) / ratio)
    out = []
    for i in range(m):
        p = i * ratio
        j = int(p)
        f = p - j
        out.append(x[j] * (1 - f) + (x[j + 1] if j + 1 < len(x) else 0.0) * f)
    return out


def variant(kind, alt):
    key = (kind, alt)
    if key not in SOUNDS:
        SOUNDS[key] = _pitched(sound(kind), 1.12) if alt else sound(kind)
    return SOUNDS[key]


def build_track(events, total, out_wav, gain=0.35):
    """events: [(thời_điểm_giây, loại, âm_lượng 0..1)] → file wav mono.
    Chống "súng máy" khi một tiếng lặp liền nhau (video-shotcraft S2): xen kẽ 2 bản khác cao độ
    và giảm dần âm lượng theo bậc (1.0 → 0.6) trong cùng một chuỗi."""
    n = int(SR * (total + 1))
    buf = array("d", bytes(8 * n))
    last, run = {}, {}
    for t, kind, vol in sorted(events):
        gap = t - last.get(kind, -9)
        if gap < 0.12:  # tránh dồn quá nhiều tiếng cùng loại
            continue
        last[kind] = t
        run[kind] = run.get(kind, 0) + 1 if gap < 1.0 else 0
        k = run[kind]
        vol *= max(0.6, 1 - 0.1 * k)
        s = variant(kind, k % 2 == 1) if kind != "riser" else sound(kind)
        start = int(t * SR)
        for i, v in enumerate(s):
            j = start + i
            if j >= n:
                break
            buf[j] += v * vol * gain
    pcm = array("h", (max(-32767, min(32767, int(v * 32767))) for v in buf))
    with wave.open(str(out_wav), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())
    return out_wav
