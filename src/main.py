"""Tạo video hoạt hình người que từ một chủ đề.

Ví dụ:
    python src/main.py --topic "Vì sao bầu trời màu xanh" --scenes 8 --voice nu
"""
import argparse
import json
import random
import re
import subprocess
import unicodedata
from pathlib import Path

from images import generate_background, make_thumbnail
from render import PAD, write_subtitles
from scene_video import render_still, render_video
from script_gen import generate_script
from tts import synthesize

ROOT = Path(__file__).resolve().parent.parent


def slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.replace("đ", "d").replace("Đ", "D"))
    text = text.encode("ascii", "ignore").decode()
    return re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()[:60] or "video"


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--topic", help="Chủ đề video")
    p.add_argument("--scenes", type=int, default=8)
    p.add_argument("--voice", default="nu", help="nu | nam | tên giọng Edge TTS")
    p.add_argument("--rate", default="+5%", help="Tốc độ đọc, ví dụ +10%")
    p.add_argument("--style", default="doodle", help="doodle (nét đen) | shirt (áo xanh, nền màu)")
    p.add_argument("--model", default="auto", help="auto = tự chọn model Gemini mới nhất")
    p.add_argument("--script-file", help="Dùng kịch bản JSON có sẵn thay vì gọi Gemini")
    p.add_argument("--out", default="output")
    p.add_argument("--offline", action="store_true", help="Chỉ để test: không gọi mạng")
    a = p.parse_args()

    if a.script_file:
        script = json.loads(Path(a.script_file).read_text(encoding="utf-8"))
    elif a.topic:
        script = generate_script(a.topic, a.scenes, a.model)
    else:
        p.error("Cần --topic hoặc --script-file")

    out = Path(a.out)
    work = out / "work"
    work.mkdir(parents=True, exist_ok=True)
    seed = random.randint(1, 10**6)

    scenes = script["scenes"]
    durations, wavs, bgs = [], [], []
    for i, scene in enumerate(scenes, 1):
        print(f"--- Cảnh {i}/{len(scenes)}: {scene.get('action')} / {scene.get('keyword')}")
        bg = generate_background(scene.get("background_prompt", ""), work / f"bg_{i:02d}.png",
                                 seed + i, a.style, a.offline)
        bgs.append(bg)
        mp3 = work / f"voice_{i:02d}.mp3"
        adur = synthesize(scene["narration"], mp3, a.voice, a.rate, a.offline)
        dur = round(adur + PAD, 2)
        wav = work / f"voice_{i:02d}.wav"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(mp3), "-af", "apad",
                        "-t", f"{dur:.2f}", "-ar", "44100", "-ac", "2", str(wav)], check=True)
        durations.append(dur)
        wavs.append(wav)

    (work / "voice.txt").write_text("".join(f"file '{w.name}'\n" for w in wavs))
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
                    "-i", "voice.txt", "-c", "copy", "voice.wav"], check=True, cwd=work)

    write_subtitles(scenes, durations, work / "subs.ass")
    music = sorted((ROOT / "music").glob("*.mp3"))
    name = slugify(script["title"])
    video = out / f"{name}.mp4"
    render_video(scenes, durations, bgs, work / "voice.wav", video, a.style,
                 subs=work / "subs.ass", music=random.choice(music).resolve() if music else None, cwd=work)
    still = render_still(bgs[0], work / "thumb_frame.png", a.style)
    make_thumbnail(still, script["title"], out / f"{name}_thumbnail.jpg")
    (out / f"{name}.json").write_text(json.dumps(script, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"XONG: {video} ({sum(durations):.0f} giây)")


if __name__ == "__main__":
    main()
