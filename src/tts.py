"""Bước 3a: giọng đọc miễn phí bằng Edge TTS (nhiều ngôn ngữ)."""
import asyncio
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
