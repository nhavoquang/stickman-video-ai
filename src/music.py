"""Nhạc nền tự tạo (không bản quyền, miễn phí): hợp âm pad + arpeggio gảy dây + trống nhẹ.

mood: upbeat (vui, nhanh), chill (thư giãn), mystery (bí ẩn, tò mò), epic (hào hùng).
Nếu thư mục music/ có file .mp3 thì dùng file đó thay vì nhạc tự tạo.
"""
import wave
from pathlib import Path

import numpy as np

SR = 44100
NOTE = {"C": 0, "C#": 1, "D": 2, "D#": 3, "E": 4, "F": 5, "F#": 6, "G": 7, "G#": 8, "A": 9, "A#": 10, "B": 11}

MOODS = {
    #           bpm   progression (root, kind)                                   swing  drums
    "upbeat":  (112, [("C", "maj"), ("G", "maj"), ("A", "min"), ("F", "maj")], 0.0, "pop"),
    "chill":   (86, [("F", "maj7"), ("E", "min7"), ("D", "min7"), ("C", "maj7")], 0.12, "lofi"),
    "mystery": (84, [("A", "min"), ("F", "maj"), ("D", "min"), ("E", "maj")], 0.0, "soft"),
    "epic":    (96, [("D", "min"), ("A#", "maj"), ("F", "maj"), ("C", "maj")], 0.0, "big"),
}
CHORD = {"maj": [0, 4, 7], "min": [0, 3, 7], "maj7": [0, 4, 7, 11], "min7": [0, 3, 7, 10]}


def hz(midi):
    return 440.0 * 2 ** ((midi - 69) / 12)


def _pluck(freq, dur, bright=0.5, seed=0):
    """Karplus-Strong: tiếng gảy dây tự nhiên."""
    n = int(dur * SR)
    p = max(2, int(SR / freq))
    rng = np.random.default_rng(seed)
    buf = rng.uniform(-1, 1, p)
    out = np.empty(n)
    a = 0.5 + 0.49 * bright
    for i in range(n):
        j = i % p
        v = buf[j]
        out[i] = v
        buf[j] = (a * v + (1 - a) * buf[j - 1]) * 0.998
    return out * np.exp(-np.linspace(0, 4, n))


def _pad(freqs, dur):
    t = np.arange(int(dur * SR)) / SR
    s = np.zeros_like(t)
    for f in freqs:
        for k, amp in ((1, 1.0), (2, 0.35), (3, 0.15)):
            s += amp * np.sin(2 * np.pi * f * k * t + 0.3 * np.sin(2 * np.pi * 0.2 * t)) * 0.5
            s += amp * np.sin(2 * np.pi * f * k * 1.003 * t) * 0.5  # hơi lệch: dày, ấm
    env = np.minimum(1, t / 0.35) * np.minimum(1, (dur - t) / 0.3)
    return s * env / (len(freqs) * 2)


def _kick(dur=0.35):
    t = np.arange(int(dur * SR)) / SR
    f = 50 + 90 * np.exp(-t * 30)
    return np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 9)


def _hat(dur=0.06, seed=3):
    rng = np.random.default_rng(seed)
    n = int(dur * SR)
    x = rng.uniform(-1, 1, n)
    x = np.diff(x, prepend=0)  # lọc thông cao đơn giản
    return x * np.exp(-np.linspace(0, 8, n)) * 0.22


def _snare(dur=0.2, seed=5):
    rng = np.random.default_rng(seed)
    n = int(dur * SR)
    t = np.arange(n) / SR
    return (rng.uniform(-1, 1, n) * 0.6 + np.sin(2 * np.pi * 190 * t) * 0.5) * np.exp(-t * 18)


def _add(buf, x, start):
    i = int(start * SR)
    if i >= len(buf):
        return
    m = min(len(x), len(buf) - i)
    buf[i:i + m] += x[:m]


def build(total: float, out: Path, mood="upbeat", seed=7) -> Path:
    bpm, prog, swing, drums = MOODS.get(mood, MOODS["upbeat"])
    beat = 60 / bpm
    bar = beat * 4
    n = int((total + 2) * SR)
    pad = np.zeros(n)
    arp = np.zeros(n)
    dr = np.zeros(n)
    rng = np.random.default_rng(seed)
    kick, hat, snare = _kick(), _hat(), _snare()
    t, b = 0.0, 0
    pluck_cache = {}
    while t < total + 1:
        root, kind = prog[b % len(prog)]
        base = 48 + NOTE[root]
        notes = [base + i for i in CHORD[kind]]
        _add(pad, _pad([hz(m) for m in notes] + [hz(base - 12)], bar + 0.25), t)
        # arpeggio 8 nốt/ô nhịp, lên xuống, thỉnh thoảng nhảy quãng tám
        seq = notes + [notes[0] + 12] + notes[::-1][:3] + [notes[1] + 12]
        for i in range(8):
            m = seq[i % len(seq)] + 12
            if rng.random() < 0.15:
                m += 12
            key = (m, i % 3)
            if key not in pluck_cache:
                pluck_cache[key] = _pluck(hz(m), beat * 1.5, 0.35, seed=m * 7 + i % 3)
            st = t + i * beat / 2 + (swing * beat / 2 if i % 2 else 0)
            _add(arp, pluck_cache[key] * (0.8 if i % 2 else 1.0), st)
        for q in range(4):  # trống
            bt = t + q * beat
            if drums in ("pop", "big", "lofi"):
                if q in (0, 2) or (drums == "pop" and q == 3 and b % 2):
                    _add(dr, kick * (1.2 if drums == "big" else 1.0), bt)
                if q in (1, 3):
                    _add(dr, snare * (0.55 if drums == "lofi" else 0.7), bt)
                for h in (0, 0.5):
                    _add(dr, hat * (0.6 if h else 0.9), bt + h * beat + (swing * beat / 2 if h else 0))
            elif drums == "soft" and q == 0:
                _add(dr, kick * 0.6, bt)
        t += bar
        b += 1
    mix = pad * 0.6 + arp * 0.3 + dr * 0.26
    mix = mix[: int((total + 1) * SR)]
    fade = int(1.5 * SR)
    mix[:int(0.4 * SR)] *= np.linspace(0, 1, int(0.4 * SR))
    mix[-fade:] *= np.linspace(1, 0, fade)
    mix = mix / (np.abs(mix).max() + 1e-9) * 0.8
    pcm = (mix * 32767).astype(np.int16)
    raw = out.with_suffix(".raw.wav")
    with wave.open(str(raw), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())
    # làm ấm (cắt bớt tần số cao chói) + chút vang cho có không gian
    import subprocess
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(raw), "-af",
                    "lowpass=f=5200,highpass=f=40,aecho=0.8:0.6:70|140:0.22|0.12,"
                    "acompressor=threshold=0.25:ratio=3,alimiter=limit=0.9", str(out)], check=True)
    raw.unlink(missing_ok=True)
    return out


if __name__ == "__main__":
    import sys
    build(float(sys.argv[2]) if len(sys.argv) > 2 else 30, Path(sys.argv[3] if len(sys.argv) > 3 else "music.wav"),
          sys.argv[1] if len(sys.argv) > 1 else "upbeat")
