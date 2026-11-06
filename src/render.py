"""Phụ đề ASS cho video."""
from pathlib import Path

PAD = 0.5  # nghỉ ngắn cuối mỗi cảnh


def write_subtitles(scenes: list, durations: list, out: Path) -> None:
    """Chia lời dẫn thành các đoạn ngắn, căn thời gian theo độ dài chữ."""
    lines = [
        "[Script Info]", "ScriptType: v4.00+", "PlayResX: 1920", "PlayResY: 1080", "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, OutlineColour, BackColour, Bold, "
        "BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV",
        "Style: Default,DejaVu Sans,58,&H00FFFFFF,&H00000000,&H64000000,1,1,5,1,2,120,120,40",
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
