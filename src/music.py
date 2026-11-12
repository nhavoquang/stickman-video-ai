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
    #           bpm   progression mặc định (root, kind)                            swing  drums
    "upbeat":  (112, [("C", "maj"), ("G", "maj"), ("A", "min"), ("F", "maj")], 0.0, "pop"),
    "chill":   (86, [("F", "maj7"), ("E", "min7"), ("D", "min7"), ("C", "maj7")], 0.12, "lofi"),
    "mystery": (84, [("A", "min"), ("F", "maj"), ("D", "min"), ("E", "maj")], 0.0, "soft"),
    "epic":    (96, [("D", "min"), ("A#", "maj"), ("F", "maj"), ("C", "maj")], 0.0, "big"),
}
# Kho vòng hợp âm theo bậc (bậc tính bằng nửa cung từ chủ âm) — mỗi video bốc ngẫu nhiên theo hạt giống riêng
PROGS = {
    "upbeat": [[(0, "maj"), (7, "maj"), (9, "min"), (5, "maj")], [(0, "maj"), (5, "maj"), (7, "maj"), (5, "maj")],
               [(0, "maj"), (9, "min"), (5, "maj"), (7, "maj")], [(5, "maj"), (7, "maj"), (4, "min"), (9, "min")],
               [(0, "maj"), (4, "min"), (5, "maj"), (7, "maj")]],
    "chill": [[(5, "maj7"), (4, "min7"), (2, "min7"), (0, "maj7")], [(2, "min7"), (7, "maj"), (0, "maj7"), (9, "min7")],
              [(0, "maj7"), (9, "min7"), (2, "min7"), (7, "maj")], [(4, "min7"), (9, "min7"), (2, "min7"), (7, "maj")]],
    "mystery": [[(9, "min"), (5, "maj"), (2, "min"), (4, "maj")], [(9, "min"), (7, "maj"), (5, "maj"), (4, "maj")],
                [(9, "min"), (2, "min"), (9, "min"), (4, "maj")], [(9, "min"), (0, "maj"), (5, "maj"), (4, "maj")]],
    "epic": [[(2, "min"), (10, "maj"), (5, "maj"), (0, "maj")], [(2, "min"), (0, "maj"), (10, "maj"), (0, "maj")],
             [(2, "min"), (5, "maj"), (0, "maj"), (10, "maj")], [(10, "maj"), (0, "maj"), (2, "min"), (2, "min")]],
}
# Kiểu rải hợp âm (chỉ số nốt trong hợp âm, 8 nốt / ô nhịp; 3 = quãng tám của nốt gốc)
ARPS = [[0, 1, 2, 3, 2, 1, 0, 1], [0, 2, 1, 3, 0, 2, 1, 2], [3, 2, 1, 0, 1, 2, 3, 2],
        [0, 1, 0, 2, 0, 1, 0, 3], [0, 2, 3, 2, 1, 2, 3, 1], [2, 1, 0, 1, 3, 1, 0, 2]]
PENTA = [0, 2, 4, 7, 9]  # thang ngũ cung cho giai điệu
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
    if i < 0:  # bắt đầu trước 0 (lưới nhịp lệch pha): bỏ phần đầu
        x, i = x[-i:], 0
    if i >= len(buf) or len(x) == 0:
        return
    m = min(len(x), len(buf) - i)
    buf[i:i + m] += x[:m]


def build(total: float, out: Path, mood="upbeat", seed=7, downbeat_at=0.0) -> Path:
    """Nhạc nền tự tạo, KHÁC NHAU cho mỗi video: hạt giống (seed, lấy từ tiêu đề) chọn giọng (tông), tốc độ,
    vòng hợp âm, kiểu rải, giai điệu, độ sáng tiếng đàn và biến thể trống. Trong một bài cũng đổi theo đoạn
    (8 ô nhịp đổi kiểu rải, có ô nghỉ trống), để không nghe như một vòng 4 ô lặp mãi.
    downbeat_at: thời điểm (giây) rơi đúng phách mạnh đầu ô nhịp (vd. lúc chớp trắng sau hook);
    trước thời điểm đó chưa có trống (phần mở đầu nhẹ)."""
    bpm0, prog0, swing, drums = MOODS.get(mood, MOODS["upbeat"])
    rng = np.random.default_rng(seed)
    bpm = bpm0 * float(rng.uniform(0.93, 1.08))
    beat = 60 / bpm
    bar = beat * 4
    tonic = 48 + int(rng.integers(-5, 7))  # đổi tông
    progs = PROGS.get(mood, PROGS["upbeat"])
    prog_a = progs[int(rng.integers(len(progs)))]
    prog_b = progs[int(rng.integers(len(progs)))]
    arp_a, arp_b = (ARPS[int(k)] for k in rng.choice(len(ARPS), 2, replace=False))
    bright = float(rng.uniform(0.2, 0.55))
    hat_on = bool(rng.random() < 0.75)
    motif = [int(x) for x in rng.choice(len(PENTA), 8)]          # giai điệu 2 ô nhịp
    rhythm = [bool(x) for x in rng.random(8) < 0.55]
    n = int((total + 2) * SR)
    pad = np.zeros(n)
    arp = np.zeros(n)
    mel = np.zeros(n)
    dr = np.zeros(n)
    kick, hat, snare = _kick(), _hat(seed=seed % 97 + 3), _snare(seed=seed % 89 + 5)
    t = (downbeat_at % bar) - bar if downbeat_at else 0.0
    b = 0
    pluck_cache = {}
    while t < total + 1:
        section = (b // 8) % 2                        # A/B đổi mỗi 8 ô nhịp
        prog = prog_a if section == 0 else prog_b
        pat = arp_a if section == 0 else arp_b
        deg, kind = prog[b % len(prog)]
        base = tonic + deg
        notes = [base + i for i in CHORD[kind]]
        _add(pad, _pad([hz(m) for m in notes] + [hz(base - 12)], bar + 0.25), t)
        seq = notes[:3] + [notes[0] + 12]
        for i in range(8):
            m = seq[pat[i] % 4] + 12
            if rng.random() < 0.1:
                m += 12
            key = (m, i % 3)
            if key not in pluck_cache:
                pluck_cache[key] = _pluck(hz(m), beat * 1.5, bright, seed=m * 7 + i % 3 + seed)
            st = t + i * beat / 2 + (swing * beat / 2 if i % 2 else 0)
            _add(arp, pluck_cache[key] * (0.8 if i % 2 else 1.0), st)
        # giai điệu ngũ cung: chỉ ở đoạn B và nửa sau đoạn A, nhẹ nhàng
        if section == 1 or (b % 8) >= 4:
            for i in range(4):
                k = (b % 2) * 4 + i
                if rhythm[k]:
                    m = tonic + 24 + PENTA[motif[k]] + (12 if (b // 16) % 2 else 0) - 12
                    key = ("mel", m)
                    if key not in pluck_cache:
                        pluck_cache[key] = _pluck(hz(m), beat * 1.8, min(0.9, bright + 0.3), seed=m + seed)
                    _add(mel, pluck_cache[key], t + i * beat)
        started = t >= (downbeat_at - 1e-3 if downbeat_at else 0)
        rest_bar = (b % 8 == 7) and rng.random() < 0.5   # ô nghỉ trống trước đoạn mới
        for q in range(4):  # trống
            bt = t + q * beat
            if not started or (rest_bar and q >= 2):
                continue
            if drums in ("pop", "big", "lofi"):
                if q in (0, 2) or (drums == "pop" and q == 3 and b % 2):
                    _add(dr, kick * (1.2 if drums == "big" else 1.0), bt)
                if q in (1, 3):
                    _add(dr, snare * (0.55 if drums == "lofi" else 0.7), bt)
                if hat_on:
                    for h in (0, 0.5):
                        _add(dr, hat * (0.6 if h else 0.9), bt + h * beat + (swing * beat / 2 if h else 0))
            elif drums == "soft" and q == 0:
                _add(dr, kick * 0.6, bt)
        t += bar
        b += 1
    arp = arp + mel * 0.8
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
