"""Kiểm tra video sau khi dựng (từng khung, 30 fps): thông số, loudness, khung đen/trắng, đoạn đứng hình,
khung nhảy giật, và ảnh tổng hợp mỗi 2 giây (60 khung, có số khung) để người/Claude xem lại.

Dựa trên templates/scripts/short_qa.py của github.com/mromidev/claude-animated-shorts (MIT License).
Dùng: python src/qa.py video.mp4 thư_mục_ra [planned.json]
  planned.json: {"planned": [[a, b], ...]}  các khung cố ý (chớp trắng, chuyển cảnh) được bỏ qua.
"""
import json
import os
import subprocess
import sys

import numpy as np
from PIL import Image, ImageDraw


def _run(*a):
    return subprocess.run(a, capture_output=True, text=True)


def check(vid, out, planned_ranges=(), sheets=True):
    """Trả về (danh sách dòng báo cáo, dict cảnh báo). Ghi report.md (+ sheet_*.jpg) vào out."""
    os.makedirs(out, exist_ok=True)
    planned = set()
    for a, b in planned_ranges:
        planned.update(range(int(a) - 1, int(b) + 2))
    R, warn = [], {}
    pr = json.loads(_run("ffprobe", "-v", "error", "-show_entries",
                         "stream=codec_type,codec_name,width,height,r_frame_rate,nb_frames,sample_rate,channels"
                         ":format=duration", "-of", "json", str(vid)).stdout)
    v = next(s for s in pr["streams"] if s["codec_type"] == "video")
    au = [s for s in pr["streams"] if s["codec_type"] == "audio"]
    R.append(f"SPECS {v['width']}x{v['height']} {v['r_frame_rate']} fps, {float(pr['format']['duration']):.2f} s; audio: "
             + (", ".join(f"{s['codec_name']} {s['sample_rate']} Hz {s['channels']}ch" for s in au) or "KHÔNG CÓ"))
    if not au:
        warn["audio"] = "không có tiếng"
    else:
        e = _run("ffmpeg", "-i", str(vid), "-map", "0:a:0", "-af", "ebur128=peak=true", "-f", "null", "-").stderr
        tail = e[e.rfind("Summary:"):]
        lines = [l.strip() for l in tail.splitlines() if l.strip().startswith(("I:", "LRA:", "Peak:"))]
        R.append("LOUDNESS " + " | ".join(lines))
        try:
            i_lufs = float(next(l for l in lines if l.startswith("I:")).split()[1])
            if abs(i_lufs + 14) > 1.5:
                warn["loudness"] = f"{i_lufs} LUFS (chuẩn YouTube -14)"
        except (StopIteration, ValueError, IndexError):
            pass
        e = _run("ffmpeg", "-i", str(vid), "-map", "0:a:0", "-af", "silencedetect=n=-45dB:d=0.4",
                 "-f", "null", "-").stderr
        sil = [l.split("] ")[-1] for l in e.splitlines() if "silence_end" in l]
        R.append("SILENCES ≥0.4s " + ("; ".join(sil) or "none"))
        if sil:
            warn["silence"] = f"{len(sil)} đoạn im lặng ≥ 0,4 s"

    W, H = (180, 320) if int(v["height"]) > int(v["width"]) else (320, 180)
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(vid), "-vf", f"scale={W}:{H}:flags=area",
                          "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True).stdout
    F = np.frombuffer(raw, np.uint8).reshape(-1, H, W, 3)
    n = len(F)
    luma = (F.astype(np.float32) / 255) @ np.array([0.2126, 0.7152, 0.0722], np.float32)
    mean = luma.reshape(n, -1).mean(1)
    diff = np.array([np.abs(F[i + 1].astype(np.int16) - F[i]).mean() for i in range(n - 1)])
    med = np.array([np.median(diff[max(0, i - 8):i + 9]) for i in range(len(diff))])
    pops = [i + 1 for i in range(len(diff)) if diff[i] > 3 * med[i] + 1.0 and (i + 1) not in planned]
    black = [i for i in range(n) if mean[i] < 0.04 and i not in planned]
    white = [i for i in range(n) if mean[i] > 0.93 and i not in planned]
    frozen, rs = [], None
    for i in range(len(diff)):
        if diff[i] < 0.02:
            rs = i if rs is None else rs
        else:
            if rs is not None and i - rs >= 12:
                frozen.append((rs, i))
            rs = None
    if rs is not None and len(diff) - rs >= 12:
        frozen.append((rs, len(diff)))
    held = float((diff < 0.3).mean() * 100) if len(diff) else 0
    R.append(f"FRAMES {n}; đen {black[:20]}; trắng ngoài dự kiến {white[:20]}; đứng hình ≥12 khung {frozen[:20]}")
    R.append(f"POPS (khung nhảy giật > 3× trung vị quanh nó): {pops[:40]}")
    R.append(f"MOTION diff trung bình {diff.mean():.2f}; khung gần như đứng yên {held:.0f}% (video mẫu ~10–30%)")
    for k, val, msg in (("black", black, "khung đen"), ("white", white, "khung trắng"),
                        ("frozen", frozen, "đoạn đứng hình"), ("pops", pops, "khung nhảy giật")):
        if val:
            warn[k] = f"{len(val)} {msg}: {val[:8]}"
    if held > 40:
        warn["static"] = f"{held:.0f}% khung đứng yên"

    if sheets:  # ảnh tổng hợp 2 giây / tấm, 10 × 6 khung, có số khung
        cw, ch = (108, 192) if H > W else (192, 108)
        for k in range(0, n, 60):
            S = Image.new("RGB", (cw * 10, ch * 6), "black")
            d = ImageDraw.Draw(S)
            for j in range(min(60, n - k)):
                x, y = (j % 10) * cw, (j // 10) * ch
                S.paste(Image.fromarray(F[k + j]).resize((cw, ch)), (x, y))
                d.rectangle([x, y, x + 34, y + 12], fill="black")
                d.text((x + 2, y + 1), str(k + j), fill="yellow")
            S.save(os.path.join(out, f"sheet_{k:04d}.jpg"), quality=82)
    R.append("\nCẢNH BÁO: " + ("; ".join(f"{k}: {v}" for k, v in warn.items()) if warn else "không có"))
    with open(os.path.join(out, "report.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(R) + "\n")
    with open(os.path.join(out, "report.json"), "w", encoding="utf-8") as f:
        json.dump(warn, f, ensure_ascii=False, indent=2)
    return R, warn


if __name__ == "__main__":
    meta = json.load(open(sys.argv[3])) if len(sys.argv) > 3 else {}
    lines, _ = check(sys.argv[1], sys.argv[2], meta.get("planned", []))
    print("\n".join(lines))
