"""Bước 3a: giọng đọc tiếng Việt miễn phí bằng Edge TTS."""
import asyncio
import subprocess
from pathlib import Path

VOICES = {"nu": "vi-VN-HoaiMyNeural", "nam": "vi-VN-NamMinhNeural"}


def synthesize(text: str, out: Path, voice: str, rate: str = "+5%", offline: bool = False) -> float:
    if offline:
        # Chỉ để test: tạo âm thanh im lặng dài theo số từ.
        dur = max(2.5, len(text.split()) * 0.32)
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                        "anullsrc=r=24000:cl=mono", "-t", f"{dur:.2f}", str(out)], check=True)
        return audio_duration(out)

    import edge_tts

    voice = VOICES.get(voice, voice)
    for attempt in range(4):
        try:
            asyncio.run(edge_tts.Communicate(text, voice, rate=rate).save(str(out)))
            return audio_duration(out)
        except Exception as e:  # mạng chập chờn, thử lại
            print(f"[tts] lỗi {e}, thử lại")
    raise SystemExit("Edge TTS lỗi liên tục")


def audio_duration(path: Path) -> float:
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                        "-of", "csv=p=0", str(path)], capture_output=True, text=True, check=True)
    return float(r.stdout.strip())
