"""Phụ đề ASS cho video."""
from pathlib import Path

PAD = 0.5  # nghỉ ngắn cuối mỗi cảnh


def write_subtitles(scenes: list, durations: list, out: Path, size=(1920, 1080),
                    font="DejaVu Sans", lang="vi") -> None:
    """Chia lời dẫn thành các đoạn ngắn, căn thời gian theo độ dài chữ."""
    vertical = size[1] > size[0]
    fs = 62 if vertical else (50 if size[0] == size[1] else 58)
    margin_v = 170 if vertical else 36  # dọc: chừa chỗ cho giao diện Shorts
    margin_h = 70 if size[0] <= 1080 else 120
    max_words = 5 if size[0] <= 1080 else 8
    lines = [
        "[Script Info]", "ScriptType: v4.00+", f"PlayResX: {size[0]}", f"PlayResY: {size[1]}",
        "WrapStyle: 0", "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, OutlineColour, BackColour, Bold, "
        "BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV",
        f"Style: Default,{font},{fs},&H00FFFFFF,&H00000000,&H64000000,1,1,5,1,2,{margin_h},{margin_h},{margin_v}",
        "", "[Events]",
        "Format: Layer, Start, End, Style, Text",
    ]
    t = 0.0
    for scene, dur in zip(scenes, durations):
        speech = dur - PAD
        chunks = _chunks(scene["narration"], max_words, lang)
        total = sum(len(c) for c in chunks)
        start = t
        for c in chunks:
            end = start + speech * len(c) / total
            lines.append(f"Dialogue: 0,{_ts(start)},{_ts(end)},Default,{c}")
            start = end
        t += dur
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _chunks(text: str, max_words: int = 8, lang: str = "vi") -> list:
    if lang in ("zh", "ja", "th"):  # không có dấu cách: chia theo số ký tự
        n = max_words * 3
        return [text[i:i + n] for i in range(0, len(text), n)] or [text]
    words = text.split()
    return [" ".join(words[i:i + max_words]) for i in range(0, len(words), max_words)]


def _ts(sec: float) -> str:
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{int(h)}:{int(m):02d}:{s:05.2f}"
