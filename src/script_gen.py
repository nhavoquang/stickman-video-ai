"""Bước 1: dùng Gemini (gói free) viết kịch bản video người que, chia cảnh, nhiều ngôn ngữ."""
import json
import os
import re
import time

import requests

API_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

PROMPT = """Bạn là biên kịch cho một kênh YouTube hoạt hình người que (stick figure).
Mỗi video có MỘT nhân vật người que dễ thương làm người dẫn chuyện, đứng nói chuyện với khán giả.
Viết kịch bản cho video về chủ đề: "{topic}".

NGÔN NGỮ: toàn bộ "title", "description", "tags", "narration", "keyword" phải viết bằng {language}.
Định dạng: {format_note}
Yêu cầu thêm của người dùng: {notes}

Yêu cầu:
- Đúng {scenes} cảnh, tổng thời lượng đọc khoảng {duration} giây.
  Mỗi cảnh có lời dẫn tự nhiên, đọc trong khoảng {scene_sec} giây (tiếng Việt/Anh ≈ {words} từ).
- Cảnh 1 là câu mở đầu gây tò mò (hook). Cảnh cuối kêu gọi like và đăng ký kênh.
- Nội dung phải có giá trị thật: thông tin đúng, có ví dụ cụ thể, không lan man.
- "background_prompt": TIẾNG ANH, mô tả cảnh NỀN minh hoạ nội dung (đồ vật, nơi chốn, sơ đồ đơn giản),
  TUYỆT ĐỐI không có người, không có chữ. Để trống khoảng giữa khung hình.
- "keyword": 2-5 từ nổi bật (cùng ngôn ngữ với lời dẫn) hiện trên màn hình (ý chính của cảnh).
- "action" của nhân vật, chọn một: {actions}.
  Gợi ý: wave cho chào hỏi/kết, think khi đặt câu hỏi, point/point_up khi giới thiệu thông tin,
  explain/talk khi giải thích, excited khi bất ngờ vui, surprised khi sốc, shrug khi "không biết",
  sad khi chuyện buồn, walk khi chuyển chủ đề. Đổi hành động giữa các cảnh cho sinh động.
- "expression": một trong happy, neutral, excited, surprised, sad, thinking, angry.
- "side": "left" hoặc "right" (vị trí nhân vật), thỉnh thoảng đổi bên.

Chỉ trả về JSON đúng dạng sau:
{{
  "title": "tiêu đề YouTube hấp dẫn, dưới 90 ký tự",
  "description": "mô tả YouTube 2-4 câu",
  "tags": ["tag1", "tag2", "tag3"],
  "scenes": [
    {{"narration": "...", "background_prompt": "...", "keyword": "...", "action": "wave",
      "expression": "happy", "side": "left"}}
  ]
}}"""

from character import NAMES as ACTIONS

EXPRESSIONS = {"happy", "neutral", "excited", "surprised", "sad", "thinking", "angry"}


def available_models(key: str) -> list:
    """Hỏi Google danh sách model đang có, ưu tiên bản flash ổn định mới nhất."""
    try:
        r = requests.get("https://generativelanguage.googleapis.com/v1beta/models",
                         params={"key": key, "pageSize": 200}, timeout=60)
        if r.status_code in (400, 401, 403):
            raise SystemExit(f"GEMINI_API_KEY không hợp lệ: HTTP {r.status_code} {r.text[:300]}")
        r.raise_for_status()
        names = [m["name"].split("/", 1)[1] for m in r.json().get("models", [])
                 if "generateContent" in m.get("supportedGenerationMethods", [])]
    except requests.RequestException as e:
        print(f"[script] không lấy được danh sách model: {e}")
        return []
    flash = [n for n in names if "flash" in n and not any(
        b in n for b in ("image", "tts", "live", "audio", "embedding", "thinking", "exp"))]

    def rank(n):
        ver = re.findall(r"gemini-(\d+(?:\.\d+)?)", n)
        return (float(ver[0]) if ver else 0, "preview" not in n, "lite" not in n, "latest" in n)

    flash.sort(key=rank, reverse=True)
    print(f"[script] model khả dụng: {flash[:6]}")
    return flash


def generate_script(topic: str, scenes: int, model: str, language: str = "tiếng Việt",
                    duration: int = 60, vertical: bool = False, notes: str = "") -> dict:
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not key:
        raise SystemExit("Thiếu GEMINI_API_KEY. Thêm nó vào GitHub Secrets.")

    body = {
        "contents": [{"parts": [{"text": PROMPT.format(
            topic=topic, scenes=scenes, actions=", ".join(ACTIONS), language=language,
            duration=duration, scene_sec=round(duration / scenes), words=round(duration / scenes * 2.6),
            notes=notes.strip() or "không có",
            format_note=("YouTube Shorts dọc, nhịp nhanh, câu ngắn, hook mạnh trong 2 giây đầu" if vertical
                         else "video YouTube ngang thông thường"))}]}],
        "generationConfig": {"responseMimeType": "application/json", "temperature": 0.9},
    }
    models = ([model] if model and model != "auto" else []) + available_models(key)
    models += ["gemini-flash-latest", "gemini-flash-lite-latest"]
    models = list(dict.fromkeys(models))
    errors = []
    for m in models:
        for attempt in range(2):
            try:
                r = requests.post(API_URL.format(model=m), params={"key": key}, json=body, timeout=75)
                if r.status_code == 404:
                    errors.append(f"{m}: không tồn tại")
                    break
                if r.status_code in (429, 500, 503):
                    errors.append(f"{m}: HTTP {r.status_code} {r.text[:200]}")
                    print(f"[script] {errors[-1]}")
                    time.sleep(8)
                    continue
                if not r.ok:
                    errors.append(f"{m}: HTTP {r.status_code} {r.text[:300]}")
                    print(f"[script] {errors[-1]}")
                    break
                text = r.json()["candidates"][0]["content"]["parts"][0]["text"]
                data = _clean(json.loads(text))
                print(f"[script] {m}: {len(data['scenes'])} cảnh — {data['title']}")
                return data
            except requests.Timeout as e:  # model quá tải: chuyển ngay sang model khác
                errors.append(f"{m}: {e}")
                print(f"[script] {errors[-1]}")
                break
            except (requests.RequestException, KeyError, IndexError, ValueError) as e:
                errors.append(f"{m}: {e}")
                print(f"[script] {errors[-1]}")
                time.sleep(5)
    raise SystemExit("Gemini lỗi:\n" + "\n".join(errors))


def _clean(data: dict) -> dict:
    scenes = [s for s in data.get("scenes", []) if s.get("narration", "").strip()]
    if not scenes:
        raise ValueError("Kịch bản không có cảnh nào")
    for s in scenes:
        s["narration"] = s["narration"].strip()
        s["background_prompt"] = s.get("background_prompt") or s.get("image_prompt") or "a cozy simple room"
        s["keyword"] = (s.get("keyword") or "").strip()[:60]
        if s.get("action") not in ACTIONS:
            s["action"] = "talk"
        if s.get("expression") not in EXPRESSIONS:
            s["expression"] = "happy"
        if s.get("side") not in ("left", "right"):
            s["side"] = "left"
    data["scenes"] = scenes
    data.setdefault("title", "Video")
    data.setdefault("description", "")
    data.setdefault("tags", [])
    return data
