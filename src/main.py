"""Tạo video hoạt hình người que từ một chủ đề.

Ví dụ:
    python src/main.py --topic "Vì sao bầu trời màu xanh" --duration 60 --aspect 16:9 --language vi
    python src/main.py --topic "3 mẹo ngủ ngon" --duration 45 --aspect 9:16      # YouTube Shorts
"""
import argparse
import json
import random
import re
import subprocess
import time
import unicodedata
from pathlib import Path

import scene_video
from images import generate_background, make_thumbnail
from langs import LANGS, font_for, lang_info, voice_for
from render import PAD, write_subtitles
from scene_video import render_still, render_video
from script_gen import generate_script
from tts import synthesize

ROOT = Path(__file__).resolve().parent.parent
MAX_BACKGROUNDS = 20  # video dài dùng chung nền cho vài cảnh liền nhau (đỡ chờ API ảnh free)


def slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.replace("đ", "d").replace("Đ", "D"))
    text = text.encode("ascii", "ignore").decode()
    return re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()[:60] or f"video-{int(time.time())}"


def scenes_for(duration: int) -> int:
    """Số cảnh theo độ dài: video ngắn đổi cảnh nhanh (~7s), video dài ~12s mỗi cảnh."""
    per = 7 if duration <= 60 else (9 if duration <= 180 else 12)
    return max(3, min(60, round(duration / per)))


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--topic", help="Chủ đề video")
    p.add_argument("--language", default="vi", choices=sorted(LANGS), help="Ngôn ngữ lời dẫn")
    p.add_argument("--aspect", default="16:9", choices=["16:9", "9:16", "1:1"],
                   help="16:9 ngang (YouTube/laptop), 9:16 dọc (Shorts/TikTok/Reels), 1:1 vuông")
    p.add_argument("--duration", type=int, default=60, help="Độ dài mong muốn (giây)")
    p.add_argument("--scenes", type=int, default=0, help="Số cảnh (0 = tự tính theo độ dài)")
    p.add_argument("--voice", default="nu", help="nu | nam | tên giọng Edge TTS")
    p.add_argument("--rate", default="+5%", help="Tốc độ đọc, ví dụ +10%")
    p.add_argument("--style", default="doodle", help="doodle (nét đen) | shirt (áo xanh, nền màu)")
    p.add_argument("--subtitles", default="on", choices=["on", "off"])
    p.add_argument("--notes", default="", help="Yêu cầu thêm cho kịch bản, ví dụ: hài hước, cho trẻ em")
    p.add_argument("--model", default="auto", help="auto = tự chọn model Gemini mới nhất")
    p.add_argument("--script-file", help="Dùng kịch bản JSON có sẵn thay vì gọi Gemini")
    p.add_argument("--out", default="output")
    p.add_argument("--offline", action="store_true", help="Chỉ để test: không gọi mạng")
    a = p.parse_args()

    font, font_path = font_for(a.language)
    scene_video.configure(a.aspect, a.language, font)
    size = scene_video.L["size"]
    vertical = size[1] > size[0]
    n_scenes = a.scenes or scenes_for(a.duration)
    print(f"[config] {a.language} | {a.aspect} {size[0]}x{size[1]} | ~{a.duration}s, {n_scenes} cảnh | font {font}")

    if a.script_file:
        script = json.loads(Path(a.script_file).read_text(encoding="utf-8"))
    elif a.topic:
        script = generate_script(a.topic, n_scenes, a.model, lang_info(a.language)[0],
                                 a.duration, vertical, a.notes)
    else:
        p.error("Cần --topic hoặc --script-file")

    out = Path(a.out)
    work = out / "work"
    work.mkdir(parents=True, exist_ok=True)
    seed = random.randint(1, 10**6)
    voice = voice_for(a.language, a.voice)

    scenes = script["scenes"]
    n_bg = min(len(scenes), MAX_BACKGROUNDS)
    bg_files = {}
    durations, wavs, bgs = [], [], []
    for i, scene in enumerate(scenes, 1):
        print(f"--- Cảnh {i}/{len(scenes)}: {scene.get('action')} / {scene.get('keyword')}")
        k = (i - 1) * n_bg // len(scenes)
        if k not in bg_files:
            bg_files[k] = generate_background(scene.get("background_prompt", ""), work / f"bg_{k:02d}.png",
                                              seed + k, a.style, a.offline, size)
        bgs.append(bg_files[k])
        mp3 = work / f"voice_{i:02d}.mp3"
        adur = synthesize(scene["narration"], mp3, voice, a.rate, a.offline)
        dur = round(adur + PAD, 2)
        wav = work / f"voice_{i:02d}.wav"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(mp3), "-af", "apad",
                        "-t", f"{dur:.2f}", "-ar", "44100", "-ac", "2", str(wav)], check=True)
        durations.append(dur)
        wavs.append(wav)

    (work / "voice.txt").write_text("".join(f"file '{w.name}'\n" for w in wavs))
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
                    "-i", "voice.txt", "-c", "copy", "voice.wav"], check=True, cwd=work)

    subs = None
    if a.subtitles == "on":
        subs = work / "subs.ass"
        write_subtitles(scenes, durations, subs, size, font, a.language)
    music = sorted((ROOT / "music").glob("*.mp3"))
    name = slugify(script["title"]) + ("-shorts" if vertical else "")
    video = out / f"{name}.mp4"
    render_video(scenes, durations, bgs, work / "voice.wav", video, a.style,
                 subs=subs, music=random.choice(music).resolve() if music else None, cwd=work)
    still = render_still(bgs[0], work / "thumb_frame.png", a.style)
    make_thumbnail(still, script["title"], out / f"{name}_thumbnail.jpg", scene_video.L["thumb"],
                   font_path, a.language in scene_video.NO_SPACE_LANGS)
    script["settings"] = {k: v for k, v in vars(a).items() if k not in ("script_file", "out", "offline")}
    if vertical and "#Shorts" not in script.get("description", ""):
        script["description"] = script.get("description", "") + "\n\n#Shorts"
    (out / f"{name}.json").write_text(json.dumps(script, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"XONG: {video} ({sum(durations):.0f} giây)")


if __name__ == "__main__":
    main()
