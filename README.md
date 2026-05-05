# Hệ Thống Nhận Diện Tự Động Người Té Ngã (Raspberry Pi & Server AI)

Đây là một dự án ứng dụng Computer Vision (sử dụng MediaPipe) để phát hiện hành vi té ngã thông qua Camera. Hệ thống có khả năng hoạt động trên môi trường thực tế với Raspberry Pi (kết hợp các cảm biến, còi báo động) hoặc có thể được dùng dưới dạng test Local/Desktop.

## 🌟 Chức Năng Chính
- **AI Backend Server (`server.py`)**: Nhận dữ liệu hình ảnh liên tục từ Client, dùng `mediapipe.solutions.pose` trích xuất khung xương, phân tích tính toán góc ngã và khoảng cách.
- **Client Camera (`client.py`)**: Chạy vòng lặp lấy frame từ Webcam, nén và gửi Stream qua API. Gửi thêm thông số hệ thống (CPU, RAM).
- **Hệ thống cảnh báo**: Khi phát hiện ngã, kích hoạt Buzzer (Pin GPIO 17) và gửi cảnh báo qua Telegram.
- **Lưu trữ Cloud**: Tự động lưu hình ảnh lúc ngã lên Google Cloud Storage (Bucket `fall-log-data`). Có chế độ tự động lưu file Local (thư mục `fall_events/`) nếu không có GCS.
- **Dashboard Web**: Cung cấp giao diện trực quan tại đường dẫn `http://<IP_SERVER>:8000/`. Dashboard vẽ biểu đồ lịch sử, xem camera trực tiếp.

## 💻 Cài Đặt Hệ Thống

### 1. Chuẩn Bị Môi Trường
Đảm bảo hệ thống sử dụng Python 3.9 - 3.11. Để tránh xung đột gói, bạn **phải cài đặt chính xác** các phiên bản thư viện đã cung cấp (đặc biệt là MediaPipe 0.10.9 và Google Cloud Storage phiên bản tương thích).

```bash
# Clone hoặc tải code về máy
cd NT131-Fall_Detection_RaspberryPi

# (Tuỳ chọn) Tạo môi trường ảo
# python -m venv venv
# source venv/bin/activate

# Cài đặt toàn bộ thư viện
pip install -r requirements.txt
```

*(Đặc biệt đối với Raspberry Pi: Chạy thêm lệnh `pip install RPi.GPIO` để cài đặt thư viện phần cứng).*

### 2. Cấu Hình Biến Môi Trường (`.env`)
Tạo một file `.env` ở cùng thư mục chứa code và cấu hình các biến sau:

```env
# Địa chỉ URL của Server Backend:
# - Chạy trên cùng 1 máy: http://127.0.0.1:8000
# - Chạy qua mạng LAN hoặc VPS: http://IP_MAY_SERVER:8000
SERVER_URL=http://127.0.0.1:8000

# API Bot Telegram để nhận cảnh báo:
TELEGRAM_TOKEN=your_telegram_bot_token_here
TELEGRAM_CHAT_ID=your_telegram_chat_id_here

# (Tuỳ chọn) Cấu hình Google Cloud Platform
GOOGLE_APPLICATION_CREDENTIALS=/path/to/your/gcp-service-account.json
```

***

## 🚀 Hướng Dẫn Chạy & Kiểm Thử (Run)

### 🔴 Khởi Chạy Server (Backend + Website)
Chạy server trước để hệ thống lắng nghe và cung cấp trang web:

```bash
uv run uvicorn server:app --host 0.0.0.0 --port 8000 --reload
```
Mở trình duyệt, truy cập `http://localhost:8000` hoặc `http://127.0.0.1:8000`.

### 🔐 Xác Thực Người Dùng Với Firebase (Email/Password + Google)
Website đã được tách riêng trang đăng nhập tại `http://localhost:8000/login` và dùng Firebase Authentication thực sự.

1. Tạo project trên Firebase Console.
2. Bật các phương thức đăng nhập trong Firebase Authentication:
  - Email/Password
  - Google
3. Tạo Firestore Database (mode test/dev trước, sau đó siết rule theo production).
4. Copy file cấu hình mẫu:

```bash
copy custom\firebase-config.example.js custom\firebase-config.js
```

5. Điền thông tin Firebase app vào file `custom/firebase-config.js`.

Sau khi cấu hình xong:
- User có thể `Create Account` để tạo tài khoản mới.
- User có thể `Sign In` bằng Email/Password.
- User có thể đăng nhập bằng `Continue with Google`.
- Hồ sơ người dùng được lưu trong Firestore collection `users`.

### 🔵 Khởi Chạy Client (Desktop Camera HOẶC Raspberry Pi)
Mở một cửa sổ Terminal/Command Prompt thứ 2 và chạy client:

**Trường hợp 1: Chạy Desktop / Windows (Đóng giả Pi):**
```bash
python client.py
# Ở môi trường PC, hệ thống sẽ tự động phát hiện thiếu GPIO và chuyển 
# báo động qua chế độ [LOCAL] (Chỉ in ra Text chứ không chập mạch điện thật).
```
**Lưu ý khi chạy PC**: Hàm `cv2.VideoCapture(0)` có thể gặp lỗi nếu bạn chạy lệnh này bên trong ảo hoá WSL/Ubuntu mà chưa cấp quyền pass-through Camera. Lời khuyên là hãy **chạy file `client.py` bằng Python gốc Cài trực tiếp trên Windows**, hoặc thay số `0` bằng tên một file `.mp4` (VD: `cv2.VideoCapture('test.mp4')`).

**Trường hợp 2: Chạy thực tế trên Raspberry Pi:**
```bash
python client.py
# Hệ thống sẽ điều khiển trực tiếp còi qua GPIO17 và dùng cam V4L2.
```

## 🛠 Cấu Trúc Thư Mục
```text
📦 NT131-Fall_Detection_RaspberryPi
 ┣ 📂 custom/
 ┃ ┗ 📜 styles.css          # Style giao diện website
 ┣ 📂 templates/            # Các trang HTML Dashboard
 ┃ ┣ 📜 login.html          # Trang đăng nhập Firebase
 ┃ ┣ 📜 index.html          # Dashboard (đã yêu cầu đăng nhập)
 ┃ ┣ 📜 camera.html
 ┃ ┣ 📜 chart.html
 ┃ ┗ 📜 fallchart.html
 ┣ 📜 server.py             # File Backend chính xử lý AI
 ┣ 📜 client.py             # File Client bắt hình & đẩy lên Sever
 ┣ 📜 requirements.txt      # Thông tin version thư viện bắt buộc
 ┗ 📜 README.md             # File hướng dẫn (bạn đang đọc)
```
