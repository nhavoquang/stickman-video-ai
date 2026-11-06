"""Bước 2b + 3b: tạo chuyển động cho ảnh, ghép giọng đọc, phụ đề, nhạc nền bằng ffmpeg."""
import random
import subprocess
from pathlib import Path

FPS = 30
PAD = 0.4  # nghỉ ngắn cuối mỗi cảnh
FADE = 0.25

# Biểu thức zoompan cho từng kiểu chuyển động (on = số frame hiện tại, D = tổng frame).
MOTION_EXPR = {
    "zoom_in": ("1+0.15*on/{D}", "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"),
    "zoom_out": ("1.15-0.15*on/{D}", "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"),
    "pan_right": ("1.15", "(iw-iw/zoom)*on/{D}", "ih/2-(ih/zoom/2)"),
    "pan_left": ("1.15", "(iw-iw/zoom)*(1-on/{D})", "ih/2-(ih/zoom/2)"),
    "shake": ("1.1", "iw/2-(iw/zoom/2)+sin(on*1.3)*14", "ih/2-(ih/zoom/2)+cos(on*1.7)*10"),
}


def ff(args, cwd=None):
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *args], check=True, cwd=cwd)


def render_scene(image: Path, audio: Path, audio_dur: float, motion: str, out: Path) -> float:
    dur = audio_dur + PAD
    frames = int(dur * FPS) + 1
    z, x, y = (e.format(D=frames) for e in MOTION_EXPR.get(motion, MOTION_EXPR["zoom_in"]))
    vf = (
        "scale=2880:1620:force_original_aspect_ratio=increase,crop=2880:1620,"
        f"zoompan=z='{z}':x='{x}':y='{y}':d={frames}:s=1920x1080:fps={FPS},"
        f"fade=t=in:st=0:d={FADE},fade=t=out:st={dur - FADE:.2f}:d={FADE},format=yuv420p"
    )
    ff(["-i", str(image), "-i", str(audio), "-filter_complex", f"[0:v]{vf}[v]",
        "-map", "[v]", "-map", "1:a", "-af", "apad", "-t", f"{dur:.2f}",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-r", str(FPS),
        "-c:a", "aac", "-ar", "44100", "-ac", "2", "-b:a", "160k", str(out)])
    return dur


def write_subtitles(scenes: list, durations: list, out: Path) -> None:
    """Chia lời dẫn thành các đoạn ngắn, căn thời gian theo độ dài chữ."""
    lines = [
        "[Script Info]", "ScriptType: v4.00+", "PlayResX: 1920", "PlayResY: 1080", "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, OutlineColour, BackColour, Bold, "
        "BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV",
        "Style: Default,DejaVu Sans,64,&H00FFFFFF,&H00000000,&H80000000,1,1,5,2,2,80,80,70",
        "", "[Events]",
        "Format: Layer, Start, End, Style, Text",
    ]
    t = 0.0
    for scene, dur in zip(scenes, durations):
        speech = dur - PAD
        chunks = _chunks(scene["narration"])
        total = sum(len(c) for c in chunks)
        start = t
        for c in chunks:
            end = start + speech * len(c) / total
            lines.append(f"Dialogue: 0,{_ts(start)},{_ts(end)},Default,{c}")
            start = end
        t += dur
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _chunks(text: str, max_words: int = 8) -> list:
    words = text.split()
    return [" ".join(words[i:i + max_words]) for i in range(0, len(words), max_words)]


def _ts(sec: float) -> str:
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{int(h)}:{int(m):02d}:{s:05.2f}"


def assemble(clips: list, subs: Path, music_dir: Path, out: Path, work: Path) -> None:
    concat = work / "clips.txt"
    concat.write_text("".join(f"file '{c.name}'\n" for c in clips))
    ff(["-f", "concat", "-safe", "0", "-i", "clips.txt", "-c", "copy", "joined.mp4"], cwd=work)

    music = sorted(music_dir.glob("*.mp3")) if music_dir.exists() else []
    args = ["-i", "joined.mp4"]
    vf = f"subtitles={subs.name}"
    if music:
        track = random.choice(music).resolve()
        print(f"[render] nhạc nền: {track.name}")
        args += ["-stream_loop", "-1", "-i", str(track), "-filter_complex",
                 f"[0:v]{vf}[v];[1:a]volume=0.12[m];[0:a][m]amix=inputs=2:duration=first:normalize=0[a]",
                 "-map", "[v]", "-map", "[a]"]
    else:
        args += ["-vf", vf, "-c:a", "copy"]
    args += ["-c:v", "libx264", "-preset", "medium", "-crf", "20", "-movflags", "+faststart",
             str(out.resolve())]
    if music:
        args[-1:-1] = ["-c:a", "aac", "-b:a", "192k"]
    ff(args, cwd=work)
