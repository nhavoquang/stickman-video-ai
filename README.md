# Stickman Video AI

Tool tự động tạo video hoạt hình người que tiếng Việt từ một chủ đề, chạy miễn phí trên GitHub Actions.

**Quy trình:** Gemini (kịch bản) → Pollinations (ảnh người que) → ffmpeg (zoom/lia/rung) → Edge TTS (giọng đọc) → phụ đề → MP4 1080p + thumbnail + tiêu đề/mô tả/tag.

## Cài đặt một lần
1. Lấy API key free tại https://aistudio.google.com/apikey
2. Vào repo: Settings → Secrets and variables → Actions → New repository secret, tên `GEMINI_API_KEY`.
3. (Tuỳ chọn) Bỏ vài file nhạc nền `.mp3` không bản quyền (ví dụ từ YouTube Audio Library) vào thư mục `music/`.

## Tạo video
1. Tab **Actions** → **Tạo video người que** → **Run workflow**.
2. Nhập chủ đề, số cảnh, giọng đọc (nữ/nam) → **Run**.
3. Chạy xong, mở lần chạy đó, tải **video** ở mục Artifacts (gồm file MP4, thumbnail và file JSON chứa tiêu đề, mô tả, tag).

## Chạy trên máy (tuỳ chọn)
```bash
pip install -r requirements.txt   # cần ffmpeg
GEMINI_API_KEY=... python src/main.py --topic "Vì sao bầu trời màu xanh" --scenes 8 --voice nu
# Test không cần mạng:
python src/main.py --script-file examples/sample_script.json --offline
```
