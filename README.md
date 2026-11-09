# Stickman Video AI

Tool tự động tạo video hoạt hình người que tiếng Việt từ một chủ đề, chạy miễn phí trên GitHub Actions.

**Quy trình:** Gemini (kịch bản, chọn hành động và biểu cảm) → Pollinations (ảnh nền, đã cắt logo) → nhân vật người que vẽ bằng code, có khung xương chuyển động (vẫy tay, chỉ, suy nghĩ, nhảy, đi...), nhép miệng theo giọng, chớp mắt → Edge TTS (giọng đọc) → phụ đề + thẻ chữ ý chính → MP4 1080p + thumbnail + tiêu đề/mô tả/tag.

Hai kiểu nhân vật: `doodle` (nét đen cổ điển) và `shirt` (áo xanh, nền màu).

## Cài đặt một lần
1. Lấy API key free tại https://aistudio.google.com/apikey
2. Vào repo: Settings → Secrets and variables → Actions → New repository secret, tên `GEMINI_API_KEY`.
3. (Tuỳ chọn) Đăng ký free tại https://auth.pollinations.ai, thêm secret `POLLINATIONS_TOKEN` để tạo ảnh nhanh hơn, ít bị giới hạn.
4. (Tuỳ chọn) Bỏ vài file nhạc nền `.mp3` không bản quyền (ví dụ từ YouTube Audio Library) vào thư mục `music/`.

## Dùng tài khoản Claude để viết và tối ưu (khuyên dùng)
Chế độ `engine = claude`: Claude Code chạy trên GitHub Actions, làm theo `prompts/claude_director.md`:
viết kịch bản, tự chấm điểm và sửa 2 vòng, tạo ảnh nền + giọng đọc, **xem lại từng khung hình**,
tạo lại ảnh nền lỗi (có người, có chữ, xấu), rút gọn chữ bị tràn, rồi mới dựng video.
Nếu Claude lỗi hoặc hết hạn mức, tool tự chuyển sang Gemini.

Cài một lần:
1. Trên máy có Claude Code, chạy `claude setup-token` và đăng nhập tài khoản Claude (Pro/Max).
2. Copy token, thêm vào repo: Settings → Secrets and variables → Actions → New secret, tên `CLAUDE_CODE_OAUTH_TOKEN`.
3. Claude GitHub App phải được cài cho repo này (https://github.com/apps/claude).

Mỗi video dùng một phần hạn mức gói Claude của bạn. File `review_notes.md` trong Artifacts ghi lại điểm và những gì Claude đã sửa.

## Tự chạy khi commit
Mỗi lần commit lên `main`, workflow tự tạo 1 video mẫu tiếng Việt (16:9, 60 giây) với chủ đề chọn ngẫu nhiên trong `topics.txt`. Muốn chọn ngôn ngữ, khung hình, độ dài... thì chạy tay như bên dưới.

## Tạo video
1. Tab **Actions** → **Tạo video người que** → **Run workflow**.
2. Điền các tuỳ chọn rồi bấm **Run**:

| Tuỳ chọn | Ý nghĩa |
|---|---|
| Chủ đề | Nội dung video |
| Engine | `claude` (tối ưu nhiều vòng) hoặc `gemini` (nhanh) |
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

## Kiểu "motion" (mặc định)
Dựng như video motion graphics chuyên nghiệp, áp dụng cho mọi chủ đề:
- 1 sân khấu rộng (ảnh AI 1,5× khung hình), camera lướt/zoom liên tục có easing.
- Nhân vật và đạo cụ là ảnh AI cắt nền (viền sticker), xuất hiện/di chuyển/nhún/lắc khớp từng từ đang nói.
- Nhãn số liệu, mũi tên, vòng tròn đánh dấu, đường vẽ phát sáng, dòng chảy vật thể, pháo giấy.
- Motion blur, xóa phông, chuyển cảnh whip/zoom, phụ đề 1–3 từ (từ đang đọc tô vàng), âm thanh hiệu ứng.
Định dạng kịch bản: `prompts/motion_spec.md`, ví dụ `examples/sample_motion.json`.
Chọn `style = doodle/shirt` để dùng lại kiểu người que cũ.


## Đầu ra
Mỗi lần chạy tạo artifact **youtube**: `video.mp4`, `thumbnail.jpg` (1280×720 thiết kế riêng), `title.txt`,
`description.txt` (có hashtag), `tags.txt`, `metadata.json` — tải về là đăng lên YouTube được ngay.
