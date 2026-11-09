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


def _tick(dur=0.05):
    n = int(SR * dur)
    rnd = random.Random(3)
    return [rnd.uniform(-1, 1) * (1 - i / n) ** 4 for i in range(n)]


SOUNDS = {}


def sound(kind):
    if kind not in SOUNDS:
        SOUNDS[kind] = {"whoosh": _whoosh, "pop": _pop, "ding": _ding, "thud": _thud,
                        "tick": _tick}.get(kind, _pop)()
    return SOUNDS[kind]


def build_track(events, total, out_wav, gain=0.35):
    """events: [(thời_điểm_giây, loại, âm_lượng 0..1)] → file wav mono."""
    n = int(SR * (total + 1))
    buf = array("d", bytes(8 * n))
    last = {}
    for t, kind, vol in sorted(events):
        if t - last.get(kind, -9) < 0.12:  # tránh dồn quá nhiều tiếng cùng loại
            continue
        last[kind] = t
        s = sound(kind)
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
