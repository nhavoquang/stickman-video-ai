"""Ngôn ngữ hỗ trợ: tên gọi cho Gemini, giọng Edge TTS (nữ, nam) và font hiển thị."""
import subprocess

LANGS = {
    "vi": ("tiếng Việt", "vi-VN-HoaiMyNeural", "vi-VN-NamMinhNeural", "Noto Sans"),
    "en": ("English", "en-US-AvaNeural", "en-US-GuyNeural", "Noto Sans"),
    "ja": ("日本語 (Japanese)", "ja-JP-NanamiNeural", "ja-JP-KeitaNeural", "Noto Sans CJK JP"),
    "ko": ("한국어 (Korean)", "ko-KR-SunHiNeural", "ko-KR-InJoonNeural", "Noto Sans CJK KR"),
    "zh": ("简体中文 (Simplified Chinese)", "zh-CN-XiaoxiaoNeural", "zh-CN-YunxiNeural", "Noto Sans CJK SC"),
    "th": ("ภาษาไทย (Thai)", "th-TH-PremwadeeNeural", "th-TH-NiwatNeural", "Noto Sans Thai"),
    "id": ("Bahasa Indonesia", "id-ID-GadisNeural", "id-ID-ArdiNeural", "Noto Sans"),
    "es": ("Español", "es-ES-ElviraNeural", "es-ES-AlvaroNeural", "Noto Sans"),
    "fr": ("Français", "fr-FR-DeniseNeural", "fr-FR-HenriNeural", "Noto Sans"),
    "de": ("Deutsch", "de-DE-KatjaNeural", "de-DE-ConradNeural", "Noto Sans"),
    "pt": ("Português (Brasil)", "pt-BR-FranciscaNeural", "pt-BR-AntonioNeural", "Noto Sans"),
    "hi": ("हिन्दी (Hindi)", "hi-IN-SwaraNeural", "hi-IN-MadhurNeural", "Noto Sans Devanagari"),
}


def lang_info(code):
    return LANGS.get(code, LANGS["vi"])


def voice_for(code, voice):
    """voice = nu | nam | tên giọng Edge TTS đầy đủ."""
    _, female, male, _ = lang_info(code)
    if voice in ("nu", "female", ""):
        return female
    if voice in ("nam", "male"):
        return male
    return voice


def font_for(code):
    """Trả về (tên font, đường dẫn file đậm). Không có Noto thì dùng DejaVu Sans."""
    family = lang_info(code)[3]
    for fam in (family, "DejaVu Sans"):
        try:
            r = subprocess.run(["fc-match", "-f", "%{family}|%{file}", f"{fam}:bold"],
                               capture_output=True, text=True, check=True)
            got, path = r.stdout.split("|", 1)
            if fam.lower() in got.lower():
                return fam, path
        except (OSError, subprocess.CalledProcessError, ValueError):
            pass
    return "DejaVu Sans", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
