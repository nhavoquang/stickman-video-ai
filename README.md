# Stickman Video AI

Tool tự động tạo video hoạt hình người que tiếng Việt từ một chủ đề, chạy miễn phí trên GitHub Actions.

**Quy trình:** Gemini (kịch bản, chọn hành động và biểu cảm) → Pollinations (ảnh nền, đã cắt logo) → nhân vật người que vẽ bằng code, có khung xương chuyển động (vẫy tay, chỉ, suy nghĩ, nhảy, đi...), nhép miệng theo giọng, chớp mắt → Edge TTS (giọng đọc) → phụ đề + thẻ chữ ý chính → MP4 1080p + thumbnail + tiêu đề/mô tả/tag.

Hai kiểu nhân vật: `doodle` (nét đen cổ điển) và `shirt` (áo xanh, nền màu).

## Cài đặt một lần
1. Lấy API key free tại https://aistudio.google.com/apikey
2. Vào repo: Settings → Secrets and variables → Actions → New repository secret, tên `GEMINI_API_KEY`.
3. (Tuỳ chọn) Đăng ký free tại https://auth.pollinations.ai, thêm secret `POLLINATIONS_TOKEN` để tạo ảnh nhanh hơn, ít bị giới hạn.
4. (Tuỳ chọn) Bỏ vài file nhạc nền `.mp3` không bản quyền (ví dụ từ YouTube Audio Library) vào thư mục `music/`.

## Tạo video
1. Tab **Actions** → **Tạo video người que** → **Run workflow**.
2. Điền các tuỳ chọn rồi bấm **Run**:

| Tuỳ chọn | Ý nghĩa |
|---|---|
| Chủ đề | Nội dung video |
| Ngôn ngữ | vi, en, ja, ko, zh, th, id, es, fr, de, pt, hi (lời dẫn, phụ đề, giọng đọc đều theo ngôn ngữ này) |
| Khung hình | `16:9` ngang (YouTube, laptop), `9:16` dọc (Shorts, TikTok, Reels), `1:1` vuông |
| Độ dài | 30 giây đến 10 phút (số cảnh tự tính theo độ dài) |
| Giọng đọc | nữ / nam |
| Nhân vật | `doodle` nét đen, `shirt` áo xanh |
| Tốc độ đọc | ví dụ `-10%`, `+0%`, `+15%` |
| Phụ đề | bật / tắt |
| Yêu cầu thêm | ví dụ "hài hước", "cho trẻ em", "nhiều số liệu" |

3. Chạy xong, mở lần chạy đó, tải **video** ở mục Artifacts (gồm file MP4, thumbnail và file JSON chứa tiêu đề, mô tả, tag). Video dọc có thêm `#Shorts` trong mô tả.

## Chạy trên máy (tuỳ chọn)
```bash
pip install -r requirements.txt   # cần ffmpeg
GEMINI_API_KEY=... python src/main.py --topic "Vì sao bầu trời màu xanh" --duration 60 --aspect 9:16 --language vi
# Test không cần mạng:
python src/main.py --script-file examples/sample_script.json --offline
```
