"""Tạo video hoạt hình người que từ một chủ đề.

Ví dụ:
    python src/main.py --topic "Vì sao bầu trời màu xanh" --scenes 8 --voice nu
"""
import argparse
import json
import random
import re
import unicodedata
from pathlib import Path

from images import generate_image, make_thumbnail
from render import assemble, render_scene, write_subtitles
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

    clips, durations = [], []
    for i, scene in enumerate(script["scenes"], 1):
        print(f"--- Cảnh {i}/{len(script['scenes'])}")
        img = generate_image(scene["image_prompt"], work / f"img_{i:02d}.png", seed + i, a.offline)
        audio = work / f"voice_{i:02d}.mp3"
        adur = synthesize(scene["narration"], audio, a.voice, a.rate, a.offline)
        clip = work / f"clip_{i:02d}.mp4"
        durations.append(render_scene(img, audio, adur, scene["motion"], clip))
        clips.append(clip)

    write_subtitles(script["scenes"], durations, work / "subs.ass")
    name = slugify(script["title"])
    video = out / f"{name}.mp4"
    assemble(clips, work / "subs.ass", ROOT / "music", video, work)
    make_thumbnail(work / "img_01.png", script["title"], out / f"{name}_thumbnail.jpg")
    (out / f"{name}.json").write_text(json.dumps(script, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"XONG: {video} ({sum(durations):.0f} giây)")


if __name__ == "__main__":
    main()
