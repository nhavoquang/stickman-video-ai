"""Bước 3a: giọng đọc miễn phí bằng Edge TTS (nhiều ngôn ngữ)."""
import asyncio
import json
import subprocess
from pathlib import Path



def synthesize(text: str, out: Path, voice: str, rate: str = "+5%", offline: bool = False) -> float:
    if offline:
        # Chỉ để test: tạo âm thanh im lặng dài theo số từ.
        dur = max(2.5, len(text.split()) * 0.32, len(text) * 0.1)
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                        "sine=frequency=180:sample_rate=24000,tremolo=f=4:d=0.95,volume=0.3", "-t", f"{dur:.2f}", str(out)], check=True)
        return audio_duration(out)

    import edge_tts

    for attempt in range(5):
        try:
            asyncio.run(edge_tts.Communicate(text, voice, rate=rate).save(str(out)))
            return audio_duration(out)
        except Exception as e:  # mạng chập chờn hoặc tên giọng không còn
            print(f"[tts] {voice} lỗi {e}, thử lại")
            if attempt == 2:
                voice = _same_locale_voice(voice) or voice
    raise SystemExit("Edge TTS lỗi liên tục")


def _same_locale_voice(voice):
    """Nếu giọng bị đổi tên, lấy giọng khác cùng ngôn ngữ."""
    import edge_tts

    locale = "-".join(voice.split("-")[:2])
    try:
        voices = asyncio.run(edge_tts.list_voices())
    except Exception:
        return None
    gender = next((v["Gender"] for v in voices if v["ShortName"] == voice), None)
    same = [v["ShortName"] for v in voices if v["Locale"] == locale and v["ShortName"] != voice
            and (gender is None or v["Gender"] == gender)]
    print(f"[tts] dùng giọng thay thế: {same[:1]}")
    return same[0] if same else None


def audio_duration(path: Path) -> float:
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                        "-of", "csv=p=0", str(path)], capture_output=True, text=True, check=True)
    return float(r.stdout.strip())


def synthesize_words(text: str, out: Path, voice: str, rate: str = "+5%", offline: bool = False):
    """Như synthesize nhưng trả thêm thời điểm từng từ: (thời lượng, [(bắt_đầu, kết_thúc), ...]).

    Danh sách thời điểm khớp với text.split() (mỗi phần tử là 1 từ tách bằng dấu cách).
    """
    words = text.split()
    meta = out.with_suffix(".words.jsonl")
    bounds = []
    if offline:
        dur = synthesize(text, out, voice, rate, offline=True)
    else:
        import edge_tts

        dur = None
        for attempt in range(5):
            try:
                asyncio.run(edge_tts.Communicate(text, voice, rate=rate, boundary="WordBoundary")
                            .save(str(out), str(meta)))
                dur = audio_duration(out)
                break
            except Exception as e:
                print(f"[tts] {voice} lỗi {e}, thử lại")
                if attempt == 2:
                    voice = _same_locale_voice(voice) or voice
        if dur is None:
            raise SystemExit("Edge TTS lỗi liên tục")
        if meta.exists():
            for line in meta.read_text(encoding="utf-8").splitlines():
                try:
                    m = json.loads(line)
                except ValueError:
                    continue
                if m.get("type") == "WordBoundary":
                    s = m["offset"] / 1e7
                    bounds.append((s, s + m["duration"] / 1e7, m.get("text", "")))
    return dur, align_words(words, bounds, dur)


def _norm(w):
    return "".join(ch for ch in w.lower() if ch.isalnum())


def align_words(words, bounds, dur):
    """Ghép mốc thời gian TTS vào từng từ của lời dẫn; thiếu thì nội suy theo độ dài chữ."""
    times = [None] * len(words)
    j = 0
    for i, w in enumerate(words):
        nw = _norm(w)
        for k in range(j, min(j + 4, len(bounds))):
            if _norm(bounds[k][2]) and (_norm(bounds[k][2]) in nw or nw in _norm(bounds[k][2])):
                times[i] = (bounds[k][0], bounds[k][1])
                j = k + 1
                break
    # nội suy chỗ thiếu theo số ký tự
    total = sum(len(w) + 1 for w in words) or 1
    acc = 0.0
    speech = dur * 0.97
    for i, w in enumerate(words):
        if times[i] is None:
            s = speech * acc / total
            times[i] = (s, s + speech * (len(w) + 1) / total)
        acc += len(w) + 1
    # đảm bảo tăng dần
    for i in range(1, len(times)):
        if times[i][0] < times[i - 1][0]:
            times[i] = (times[i - 1][0], max(times[i - 1][0], times[i][1]))
    return times
