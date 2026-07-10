# Local Video Dubbing Studio

Một ứng dụng desktop cục bộ giúp tự động dịch phụ đề (Vietsub) và lồng tiếng (Dubbing) video từ tiếng Trung sang tiếng Việt. 

Dự án được tối ưu hóa cho quy trình làm video MMO/TikTok/Reels: sử dụng file phụ đề tiếng Trung xuất từ CapCut để khớp timeline chính xác, hỗ trợ dịch thuật tự động bằng AI hoặc nạp file dịch thủ công, và lồng tiếng chất lượng cao bằng các bộ TTS tiên tiến (Edge TTS, VoxCPM, Piper) hoàn toàn chạy dưới máy tính của bạn.

---

## Quy trình hoạt động (Pipeline)

```
Nạp Video + File SRT Trung (CapCut)
   │
   ├──► Dịch phụ đề (Dịch tự động bằng AI / Nhập file SRT Việt dịch sẵn)
   │
   ├──► Lồng tiếng (TTS qua Edge TTS, VoxCPM, Piper)
   │
   ├──► Xử lý hình ảnh (Tự mờ chữ gốc, định hình khung hình)
   │
   └──► Render và xuất video lồng tiếng hoàn chỉnh
```

---

## Các tính năng chính

1. **Khớp Timeline hoàn hảo qua CapCut SRT**: Bỏ qua công đoạn nhận dạng giọng nói tự động (ASR) vốn dễ bị lệch và câu quá dài đối với video ngắn. Hệ thống nạp trực tiếp file phụ đề tiếng Trung xuất từ CapCut để đảm bảo phân đoạn chính xác theo ngữ điệu gốc.
2. **Hai chế độ dịch thuật linh hoạt**:
   * **Dịch AI tự động**: Sử dụng các AI dịch thuật tích hợp (Router, Google, Gemini, OpenAI) tối ưu theo văn phong ngắn gọn, bắt trend (TikTok/Reels, review phim, kể chuyện).
   * **Nhập file dịch có sẵn**: Nạp trực tiếp file phụ đề tiếng Việt `.srt` bạn đã tự dịch trước đó qua Gemini hoặc ChatGPT.
3. **Lồng tiếng chất lượng cao (TTS)**:
   * **Edge TTS**: Giọng đọc tự nhiên, tải trực tiếp và miễn phí từ máy chủ Microsoft Edge.
   * **VoxCPM / VoxCPM2**: Công nghệ lồng tiếng ngoại tuyến, hỗ trợ clone giọng nói từ file mẫu (như preset giọng review phim `cc.wav`).
   * **Piper TTS**: Công cụ đọc text offline siêu nhanh bằng file model `.onnx`.
4. **Trình phát Video trực quan (Live Preview)**: Tích hợp màn hình xem trước video trực tiếp ở cột trái giúp bạn kiểm tra hình ảnh video ngay khi kéo thả hoặc chọn file.
5. **Giao diện tối giản (Minimalist Black & White UI)**:
   * Giao diện tối chủ đạo sang trọng, sạch sẽ, chỉ giữ lại 2 trang cốt lõi là **Auto Dubbing** và **Settings**.
   * Loại bỏ hoàn toàn lỗi xê dịch giao diện (Layout Shifting) khi đổi tùy chọn bằng cách sử dụng cơ chế Bật/Tắt thay vì Ẩn/Hiện.
   * Ô tích checkbox và radio button được thiết kế lại theo tông màu Trắng - Đen tương phản cao, dễ nhìn và hiện đại.

---

## Cấu trúc thư mục dự án

```
local_video_dubbing_studio/
├── app.py                  # Điểm khởi chạy ứng dụng (Entry point)
├── requirements.txt        # Các thư viện phụ thuộc
├── config.example.json     # File cấu hình mẫu
├── config.json             # File cấu hình thực tế của bạn (được bảo mật trên Git)
├── core/                   # Cấu hình hệ thống, SQLite, ghi log, worker đa luồng
├── models/                 # Lớp đối tượng dữ liệu (Project, SubtitleSegment...)
├── services/               # Logic chính (FFmpeg, Dịch thuật AI, TTS, Ghép nhạc, Render)
├── ui/                     # Giao diện PySide6 và các widget thành phần
├── utils/                  # Tiện ích bổ trợ (Đọc ghi srt, định dạng thời gian, builder FFmpeg)
├── data/                   # Thư mục chứa video, log, cơ sở dữ liệu và models (được ignore trên Git)
└── tests/                  # Bộ kiểm thử tự động (pytest)
```

---

## Hướng dẫn cài đặt và khởi chạy

### 1. Khởi tạo môi trường ảo (Virtual Environment)
Mở Terminal tại thư mục dự án và chạy:

```powershell
# Trên Windows (PowerShell)
python -m venv .venv
.venv\Scripts\Activate.ps1

# Trên macOS / Linux
python3 -m venv .venv
source .venv/bin/activate
```

### 2. Cài đặt các thư viện Python
```bash
pip install -r requirements.txt
```

### 3. Cấu hình FFmpeg
Ứng dụng sử dụng công cụ `ffmpeg` và `ffprobe` để xử lý video/âm thanh.
1. Tải FFmpeg bản Essentials từ [gyan.dev](https://www.gyan.dev/ffmpeg/builds/).
2. Giải nén và cấu hình đường dẫn tuyệt đối đến tệp `ffmpeg.exe` và `ffprobe.exe` trong tab **Settings** của ứng dụng.
3. Bấm **Check FFmpeg/FFprobe** để xác nhận phần mềm đã nhận diện thành công -> Bấm **Save**.

### 4. Tạo cấu hình config.json
Sao chép file cấu hình mẫu để ứng dụng nạp các thiết lập:
```bash
# Trên Windows (PowerShell)
copy config.example.json config.json
```
Bạn có thể tinh chỉnh API Key của Gemini/OpenAI hoặc đặt mặc định tốc độ đọc (`default_speed`) và số luồng tải giọng nói (`parallel_workers`) trực tiếp trong file này.

### 5. Chạy ứng dụng
```bash
python app.py
```

---

## Kiểm thử tự động (Unit Tests)
Để kiểm tra tính toàn vẹn của mã nguồn sau khi chỉnh sửa, hãy chạy lệnh:
```bash
python -m pytest -q
```
Hệ thống sẽ chạy kiểm thử cho các bộ điều khiển phụ đề, thời gian và dựng lệnh FFmpeg.

---

## Bản quyền & Bảo mật
* Ứng dụng chạy hoàn toàn offline trên máy của bạn (ngoại trừ các yêu cầu API dịch thuật và Edge TTS do bạn tùy chọn cấu hình).
* Không có mã theo dõi, không gửi dữ liệu ra bên ngoài. File `config.json` chứa API Key của bạn được bảo vệ nghiêm ngặt trên Git nhờ `.gitignore`.
