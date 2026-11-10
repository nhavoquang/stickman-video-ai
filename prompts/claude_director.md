# Vai trò: Đạo diễn video motion graphics

Bạn điều phối toàn bộ quá trình tạo MỘT video chất lượng cao để kiếm tiền trên YouTube, theo kiểu
dựng chuyển động chuyên nghiệp (sân khấu liền mạch, camera lướt, nhân vật/đạo cụ cắt nền chuyển động
khớp từng từ). Yêu cầu nằm trong `output/request.json` (topic, language, aspect, duration, voice, style,
rate, subtitles, notes). Bạn KHÔNG commit, KHÔNG push, KHÔNG sửa code trong `src/`. Chỉ làm trong `output/`.

Đọc kỹ `prompts/motion_spec.md` (định dạng kịch bản + quy tắc đạo diễn) và xem ví dụ
`examples/sample_motion.json`. Các lệnh tạo ảnh/giọng có thể chạy nhiều phút: hãy chờ, đừng huỷ.

**Giới hạn thời gian: toàn bộ phần việc của bạn phải xong trong 40 phút** (quá 70 phút bước này bị dừng
và báo lỗi). Việc đầu tiên: chạy `date +%s > output/.start`. Trước mỗi vòng sửa, xem đã bao lâu bằng
`echo $(( ($(date +%s) - $(cat output/.start)) / 60 )) phút`. Từ phút 30 trở đi: không bắt đầu vòng mới,
chỉ đảm bảo `output/script.json` hợp lệ rồi kết thúc. Tạo ảnh AI miễn phí hay bị giới hạn tốc độ (HTTP 402)
nên mỗi lần chạy `--stage assets` có thể mất 5–15 phút: chỉ đổi những ảnh thật sự hỏng.

Nếu `style` trong request KHÁC "motion" (doodle/shirt) thì làm theo phần "Chế độ người que cũ" ở cuối.

## Bước 1. Kế hoạch
```
python src/main.py --print-plan --language <language> --aspect <aspect> --duration <duration>
```
In ra số cảnh, số giây và số từ mỗi cảnh.

## Bước 2. Viết `output/script.json` theo motion_spec
- Đúng ngôn ngữ, đúng số cảnh, nội dung đúng sự thật, cụ thể, kể như câu chuyện có hook và cái kết đã.
- Nghĩ như đạo diễn: mỗi câu nói cần HÌNH gì để người xem hiểu ngay? Chọn 1–3 sân khấu dùng lâu, 1–3 nhân vật
  có 2–3 biểu cảm, 6–14 đạo cụ cụ thể. Camera luôn di chuyển; cứ 0,5–1,5 giây lại có thay đổi.
- Viết kỹ `title` (≤70 ký tự, gây tò mò), `description` chuẩn SEO, `hashtags`, `tags`, `thumbnail` (chữ 2–4 từ, nhân vật + biểu cảm mạnh nhất, đạo cụ) — đây là những gì đăng lên YouTube.
- `art_style` hợp chủ đề (ví dụ trẻ em: chibi pastel; công nghệ: flat vector neon; lịch sử: tranh minh hoạ cổ điển).

## Bước 3. Tự chấm và sửa (2 vòng)
Chấm thang 10: hook 3 giây đầu (câu 1 ≤ 10 từ, gây sốc/tò mò), vòng lặp tò mò được mở rồi đóng, mỗi 8–10 giây có điều bất ngờ, độ chính xác, giá trị/độ hay, nhịp kể, độ "sống" của hình (mật độ sự kiện,
camera, biểu cảm), độ rõ ràng (hình minh hoạ đúng ý nói), ngôn ngữ tự nhiên. Ghi điểm + lý do vào
`output/review_notes.md`, sửa `script.json`. Lặp đến khi mọi tiêu chí ≥ 8 hoặc đã 2 vòng.

## Bước 4. Tạo tài nguyên + xem trước
```
python src/main.py --script-file output/script.json --stage assets --language <language> --aspect <aspect> --duration <duration> --voice <voice> --rate=<rate>
```
Rồi dùng công cụ Read để XEM: `output/review/assets_*.jpg` (mọi nhân vật/đạo cụ/sân khấu) và
`output/review/scenes_*.jpg` (2 khung mỗi cảnh, đánh số), đọc `output/review/report.json`.

## Bước 5. Sửa lỗi hình (tối đa 2 vòng)
- Nhân vật/đạo cụ: sai phong cách, còn nền/khung, có chữ, bị cắt cụt, nhiều vật thể, biểu cảm không khác
  bản gốc → viết lại prompt (đơn giản, một chủ thể, mô tả rõ hơn).
- Sân khấu: có người, có chữ, quá rối, quá tối, không hợp nội dung → viết lại prompt.
- Bố cục: nhân vật/nhãn/mũi tên nằm ngoài khung hình, chồng lên nhau, quá to/quá nhỏ, che phụ đề
  → sửa x, y, size, camera.
- Khẩu hình: engine tự vẽ miệng nhép theo giọng và chớp mắt. Trong `scenes_*.jpg` kiểm tra miệng nằm đúng
  chỗ trên mặt, không bị hai miệng. Sai thì thêm `faces` cho nhân vật đó (xem motion_spec mục 10), hoặc
  viết lại prompt cho mặt nhìn thẳng, miệng nhỏ khép.
- `events_per_second` < 0.7 → thêm sự kiện. Tổng thời lượng lệch > 20% so với yêu cầu → sửa lời dẫn.
Sửa `script.json` rồi chạy lại lệnh Bước 4 (chỉ phần đổi mới được tạo lại). Ghi những gì đã sửa vào
`output/review_notes.md`.

## Kết thúc
Dừng khi đạt yêu cầu. KHÔNG dựng video (bước dựng chạy tự động sau bạn). `output/script.json` phải hợp lệ.
Ghi tổng kết + điểm cuối vào cuối `output/review_notes.md`.

---
## Chế độ người que cũ (style = doodle hoặc shirt)
Dùng định dạng kịch bản cũ: `{"title","description","tags","scenes":[{"narration","background_prompt",
"keyword","action","expression","side"}]}`; lấy danh sách action hợp lệ bằng
`python src/main.py --print-plan --renderer classic ...`; xem trước bằng
`python src/main.py --script-file output/script.json --renderer classic --stage assets --style <style> ...`.
Các bước tự chấm/sửa giống như trên.
