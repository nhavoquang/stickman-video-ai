"""Tạo video hoạt hình người que từ một chủ đề.

Ví dụ:
    python src/main.py --topic "Vì sao bầu trời màu xanh" --duration 60 --aspect 16:9 --language vi
    python src/main.py --topic "3 mẹo ngủ ngon" --duration 45 --aspect 9:16      # YouTube Shorts
"""
import argparse
import hashlib
import json
import random
import re
import shutil
import subprocess
import time
import unicodedata
from pathlib import Path

import scene_video
from images import contact_sheets, generate_background, make_thumbnail
from langs import LANGS, font_for, lang_info, voice_for
from render import PAD, write_subtitles
from scene_video import preview_frames, render_still, render_video
from character import NAMES as ACTIONS
from script_gen import EXPRESSIONS, _clean, generate_script
from tts import synthesize

ROOT = Path(__file__).resolve().parent.parent
MAX_BACKGROUNDS = 20  # video dài dùng chung nền cho vài cảnh liền nhau (đỡ chờ API ảnh free)


def slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.replace("đ", "d").replace("Đ", "D"))
    text = text.encode("ascii", "ignore").decode()
    return re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()[:60] or f"video-{int(time.time())}"


def h(*parts) -> str:
    return hashlib.sha1("|".join(map(str, parts)).encode()).hexdigest()[:10]


def scenes_for(duration: int) -> int:
    """Số cảnh theo độ dài: video ngắn đổi cảnh nhanh (~7s), video dài ~12s mỗi cảnh."""
    per = 7 if duration <= 60 else (9 if duration <= 180 else 12)
    return max(3, min(60, round(duration / per)))


def vertical_of(aspect):
    return aspect == "9:16"


def run_motion(a, n_scenes, size, vertical, font, font_path):
    """Quy trình dựng chuyển động: kịch bản → tài nguyên AI → giọng đọc + mốc từng từ → dựng."""
    import motion
    import publish
    import motion_script
    from assets import make_cutout, make_stage
    from tts import audio_duration, synthesize_words

    per = a.duration / n_scenes
    plan = {"scenes": n_scenes, "seconds_per_scene": round(per, 1), "words_per_scene_latin": round(per * 2.6),
            "language": lang_info(a.language)[0], "aspect": a.aspect, "vertical": vertical,
            "duration": a.duration}
    if a.print_plan:
        print(json.dumps(plan, ensure_ascii=False, indent=2))
        return
    if a.script_file:
        film = motion_script.clean(json.loads(Path(a.script_file).read_text(encoding="utf-8")))
    elif a.topic:
        film = motion_script.generate(a.topic, plan, a.model, a.notes)
    else:
        raise SystemExit("Cần --topic hoặc --script-file")

    out = Path(a.out)
    work = out / "work"
    adir = work / "assets"
    adir.mkdir(parents=True, exist_ok=True)
    (out / "script.json").write_text(json.dumps(film, ensure_ascii=False, indent=2), encoding="utf-8")

    # 1. tài nguyên hình (có cache theo prompt)
    assets = {}
    style = film["art_style"]
    for key, kind, prompt in motion_script.asset_jobs(film):
        if kind == "stage":
            assets[key] = make_stage(prompt, style, adir, size, a.offline)
        else:
            assets[key] = make_cutout(prompt, style, adir, kind, a.offline, label=key)

    # 2. giọng đọc + mốc thời gian từng từ
    voice = voice_for(a.language, a.voice)
    timings, wavs = [], []
    for i, sc in enumerate(film["scenes"], 1):
        vkey = h(sc["narration"], voice, a.rate, a.offline, "w")
        mp3 = work / f"voice_{vkey}.mp3"
        tfile = work / f"voice_{vkey}.times.json"
        if mp3.exists() and tfile.exists():
            adur, wt = audio_duration(mp3), [tuple(x) for x in json.loads(tfile.read_text())]
        else:
            adur, wt = synthesize_words(sc["narration"], mp3, voice, a.rate, a.offline)
            tfile.write_text(json.dumps(wt))
        dur = round(adur + 0.25, 2)
        wav = work / f"voice_{vkey}.wav"
        if not wav.exists():
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(mp3), "-af", "apad",
                            "-t", f"{dur:.2f}", "-ar", "44100", "-ac", "2", str(wav)], check=True)
        timings.append((dur, wt))
        wavs.append(wav)
        print(f"--- Cảnh {i}/{len(film['scenes'])}: {dur:.1f}s, {len(sc['events'])} sự kiện")
    (work / "voice.txt").write_text("".join(f"file '{w.name}'\n" for w in wavs))
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
                    "-i", "voice.txt", "-c", "copy", "voice.wav"], check=True, cwd=work)

    # 3. ảnh xem trước để duyệt
    review = out / "review"
    shutil.rmtree(review, ignore_errors=True)
    frames = motion.render(film, timings, assets, work / "voice.wav", None, preview_dir=review / "frames",
                           preview_only=True)
    sheets = contact_sheets(frames, review / "scenes", per_sheet=12)
    imgs = [v for k, v in assets.items()]
    asset_sheets = contact_sheets([Path(x) for x in imgs], review / "assets", per_sheet=16, thumb_w=360)
    total = sum(d for d, _ in timings)
    report = {"total_seconds": round(total, 1), "target_seconds": a.duration,
              "events": sum(len(s["events"]) for s in film["scenes"]),
              "events_per_second": round(sum(len(s["events"]) for s in film["scenes"]) / max(total, 1), 2),
              "scenes": [{"n": i + 1, "seconds": d, "stage": s["stage"], "events": len(s["events"])}
                         for i, (s, (d, _)) in enumerate(zip(film["scenes"], timings))],
              "assets": {k: str(v) for k, v in assets.items()},
              "scene_sheets": [str(x) for x in sheets], "asset_sheets": [str(x) for x in asset_sheets]}
    (review / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[review] {len(frames)} khung xem trước, {len(assets)} tài nguyên, {total:.1f}s, "
          f"{report['events_per_second']} sự kiện/giây")
    if a.stage == "assets":
        return

    # 4. dựng video + thumbnail
    music = sorted((ROOT / "music").glob("*.mp3"))
    name = slugify(film["title"]) + ("-shorts" if vertical else "")
    video = out / f"{name}.mp4"
    motion.render(film, timings, assets, work / "voice.wav", video,
                  music=random.choice(music).resolve() if music else None, cwd=work)
    thumb_src = frames[1] if len(frames) > 1 else frames[0]
    thumb = out / f"{name}_thumbnail.jpg"
    try:
        publish.design_thumbnail(film, assets, thumb, font_path,
                                 a.language in scene_video.NO_SPACE_LANGS, fallback_frame=thumb_src)
    except Exception as e:  # thumbnail thiết kế lỗi thì dùng kiểu cũ (khung hình + chữ)
        print(f"[thumb] lỗi {e}, dùng thumbnail đơn giản")
        make_thumbnail(thumb_src, film["title"], thumb, (1280, 720),
                       font_path, a.language in scene_video.NO_SPACE_LANGS)
    settings = {k: v for k, v in vars(a).items() if k not in ("script_file", "out", "offline")}
    meta = {"title": film["title"], "description": publish.description_text(film, vertical),
            "tags": publish.tags_list(film), "settings": settings}
    (out / f"{name}.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    yt = publish.package(out, film, video, thumb, vertical, a.language, settings)
    print(f"XONG: {video} ({total:.0f} giây) | gói đăng YouTube: {yt}")


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
    p.add_argument("--style", default="motion",
                   help="motion (dựng chuyển động, mặc định) | doodle / shirt (người que cũ)")
    p.add_argument("--subtitles", default="on", choices=["on", "off"])
    p.add_argument("--notes", default="", help="Yêu cầu thêm cho kịch bản, ví dụ: hài hước, cho trẻ em")
    p.add_argument("--model", default="auto", help="auto = tự chọn model Gemini mới nhất")
    p.add_argument("--script-file", help="Dùng kịch bản JSON có sẵn thay vì gọi Gemini")
    p.add_argument("--out", default="output")
    p.add_argument("--offline", action="store_true", help="Chỉ để test: không gọi mạng")
    p.add_argument("--stage", default="all", choices=["all", "assets"],
                   help="assets = chỉ tạo ảnh nền + giọng đọc + ảnh xem trước (để duyệt), all = dựng video")
    p.add_argument("--print-plan", action="store_true", help="In số cảnh, số từ mỗi cảnh... rồi thoát")
    p.add_argument("--renderer", default=None, choices=["motion", "classic"],
                   help="motion = dựng chuyển động chuyên nghiệp (mặc định), classic = bản người que cũ")
    a = p.parse_args()
    if a.renderer is None:
        a.renderer = "classic" if a.style in ("doodle", "shirt") else "motion"

    font, font_path = font_for(a.language)
    scene_video.configure(a.aspect, a.language, font)
    size = scene_video.L["size"]
    vertical = size[1] > size[0]
    if a.script_file and a.renderer == "motion":
        try:
            first = json.loads(Path(a.script_file).read_text(encoding="utf-8"))["scenes"][0]
            if "events" not in first:
                a.renderer = "classic"  # kịch bản kiểu cũ
        except (OSError, ValueError, KeyError, IndexError):
            pass
    if a.renderer == "classic" and a.style not in ("doodle", "shirt"):
        a.style = "doodle"
    if a.renderer == "motion":
        n_scenes = a.scenes or max(3, round(a.duration / (4.5 if vertical_of(a.aspect) else 5.5)))
    else:
        n_scenes = a.scenes or scenes_for(a.duration)
    print(f"[config] {a.language} | {a.aspect} {size[0]}x{size[1]} | ~{a.duration}s, {n_scenes} cảnh | font {font}")

    if a.renderer == "motion":
        return run_motion(a, n_scenes, size, vertical, font, font_path)

    if a.print_plan:
        per = a.duration / n_scenes
        print(json.dumps({
            "scenes": n_scenes, "seconds_per_scene": round(per, 1),
            "words_per_scene_latin": round(per * 2.6), "language": lang_info(a.language)[0],
            "aspect": a.aspect, "vertical": vertical, "actions": ACTIONS,
            "expressions": sorted(EXPRESSIONS), "sides": ["left", "right"],
            "keyword_max_chars": 28 if vertical or a.aspect == "1:1" else 34,
        }, ensure_ascii=False, indent=2))
        return

    if a.script_file:
        script = _clean(json.loads(Path(a.script_file).read_text(encoding="utf-8")))
    elif a.topic:
        script = generate_script(a.topic, n_scenes, a.model, lang_info(a.language)[0],
                                 a.duration, vertical, a.notes)
    else:
        p.error("Cần --topic hoặc --script-file")

    out = Path(a.out)
    work = out / "work"
    work.mkdir(parents=True, exist_ok=True)
    voice = voice_for(a.language, a.voice)

    scenes = script["scenes"]
    n_bg = min(len(scenes), MAX_BACKGROUNDS)
    bg_files = {}
    # Có cache: chạy lại chỉ tạo phần bị thay đổi (sửa prompt nền / lời dẫn) hoặc file đã bị xoá.
    durations, wavs, bgs = [], [], []
    for i, scene in enumerate(scenes, 1):
        print(f"--- Cảnh {i}/{len(scenes)}: {scene.get('action')} / {scene.get('keyword')}")
        k = (i - 1) * n_bg // len(scenes)
        if k not in bg_files:
            prompt = scene.get("background_prompt", "")
            key = h(prompt, a.style, size, scene.get("bg_seed", 0))
            f = work / f"bg_{key}.png"
            if not f.exists():
                generate_background(prompt, f, int(key[:6], 16), a.style, a.offline, size)
            bg_files[k] = f
        bgs.append(bg_files[k])
        vkey = h(scene["narration"], voice, a.rate, a.offline)
        mp3 = work / f"voice_{vkey}.mp3"
        if mp3.exists():
            from tts import audio_duration
            adur = audio_duration(mp3)
        else:
            adur = synthesize(scene["narration"], mp3, voice, a.rate, a.offline)
        dur = round(adur + PAD, 2)
        wav = work / f"voice_{vkey}.wav"
        if not wav.exists():
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(mp3), "-af", "apad",
                            "-t", f"{dur:.2f}", "-ar", "44100", "-ac", "2", str(wav)], check=True)
        durations.append(dur)
        wavs.append(wav)

    review = out / "review"
    shutil.rmtree(review, ignore_errors=True)
    frames = preview_frames(scenes, bgs, review / "frames", a.style)
    sheets = contact_sheets(frames, review / "scenes")
    uniq = list(dict.fromkeys(bgs))
    bg_sheets = contact_sheets(uniq, review / "backgrounds")
    report = {
        "total_seconds": round(sum(durations), 1), "target_seconds": a.duration,
        "scenes": [{"n": i + 1, "seconds": d, "keyword": s_.get("keyword", ""),
                    "background": bgs[i].name, "action": s_.get("action")}
                   for i, (s_, d) in enumerate(zip(scenes, durations))],
        "scene_sheets": [str(x) for x in sheets], "background_sheets": [str(x) for x in bg_sheets],
    }
    (review / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[review] {len(sheets)} tấm xem trước cảnh, {len(bg_sheets)} tấm nền, tổng {report['total_seconds']}s")
    if a.stage == "assets":
        print(f"[review] xem {review}/report.json")
        return

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
