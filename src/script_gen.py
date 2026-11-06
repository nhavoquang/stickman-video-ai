"""Bước 1: dùng Gemini (gói free) viết kịch bản video người que, chia cảnh."""
import json
import os
import re
import time

import requests

API_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

PROMPT = """Bạn là biên kịch cho một kênh YouTube hoạt hình người que (stick figure) bằng tiếng Việt.
Viết kịch bản cho video về chủ đề: "{topic}".

Yêu cầu:
- Đúng {scenes} cảnh. Mỗi cảnh có lời dẫn tiếng Việt tự nhiên, 1-3 câu (khoảng 20-45 từ).
- Cảnh 1 là câu mở đầu gây tò mò (hook). Cảnh cuối kêu gọi like và đăng ký kênh.
- Nội dung phải có giá trị thật: thông tin đúng, có ví dụ cụ thể, không lan man.
- "image_prompt" viết bằng TIẾNG ANH, mô tả MỘT khung hình đơn giản với nhân vật người que,
  hành động rõ ràng, ít chi tiết. Không yêu cầu chữ trong ảnh.
- "motion" chọn một trong: zoom_in, zoom_out, pan_left, pan_right, shake (shake dùng cho cảnh kịch tính).

Chỉ trả về JSON đúng dạng sau:
{{
  "title": "tiêu đề YouTube hấp dẫn, dưới 90 ký tự",
  "description": "mô tả YouTube 2-4 câu",
  "tags": ["tag1", "tag2", "tag3"],
  "scenes": [
    {{"narration": "...", "image_prompt": "...", "motion": "zoom_in"}}
  ]
}}"""

MOTIONS = {"zoom_in", "zoom_out", "pan_left", "pan_right", "shake"}


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


def generate_script(topic: str, scenes: int, model: str) -> dict:
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not key:
        raise SystemExit("Thiếu GEMINI_API_KEY. Thêm nó vào GitHub Secrets.")

    body = {
        "contents": [{"parts": [{"text": PROMPT.format(topic=topic, scenes=scenes)}]}],
        "generationConfig": {"responseMimeType": "application/json", "temperature": 0.9},
    }
    models = ([model] if model and model != "auto" else []) + available_models(key)
    models += ["gemini-flash-latest", "gemini-flash-lite-latest"]
    models = list(dict.fromkeys(models))
    errors = []
    for m in models:
        for attempt in range(3):
            try:
                r = requests.post(API_URL.format(model=m), params={"key": key}, json=body, timeout=180)
                if r.status_code == 404:
                    errors.append(f"{m}: không tồn tại")
                    break
                if r.status_code in (429, 500, 503):
                    errors.append(f"{m}: HTTP {r.status_code} {r.text[:200]}")
                    print(f"[script] {errors[-1]}")
                    time.sleep(15 * (attempt + 1))
                    continue
                if not r.ok:
                    errors.append(f"{m}: HTTP {r.status_code} {r.text[:300]}")
                    print(f"[script] {errors[-1]}")
                    break
                text = r.json()["candidates"][0]["content"]["parts"][0]["text"]
                data = _clean(json.loads(text))
                print(f"[script] {m}: {len(data['scenes'])} cảnh — {data['title']}")
                return data
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
        s["image_prompt"] = s.get("image_prompt") or "a stick figure thinking"
        if s.get("motion") not in MOTIONS:
            s["motion"] = "zoom_in"
    data["scenes"] = scenes
    data.setdefault("title", "Video")
    data.setdefault("description", "")
    data.setdefault("tags", [])
    return data
