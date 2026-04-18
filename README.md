# Zalo Work Reminder Bot

Bot Zalo tự động nhắc việc cho nhóm Truyền thông VQG Yok Đôn.

## Tính năng

- **Nhắc việc tự động** hàng ngày lúc 8h sáng (cấu hình được)
- **Đọc Google Sheet** để lấy danh sách công việc truyền thông
- **Phân loại**: quá hạn / hôm nay / sắp đến hạn / chưa giao
- **Nhắc khi Sheet trống**: nếu hôm nay chưa có nội dung → nhắc mọi người điền
- **Hỗ trợ viết bài** bằng AI (OpenRouter → Groq → Gemini fallback)

## Lệnh

| Lệnh | Mô tả |
|-------|--------|
| `/nhacviec` | Nhắc việc ngay (đọc Sheet) |
| `/xemviec` | Xem danh sách việc chưa xong |
| `/hotrobai [mô tả]` | AI gợi ý nội dung bài viết |
| `/help` | Xem hướng dẫn |

## Cài đặt

### 1. Tạo môi trường Python

```bash
cd /Users/mt/Antigranvity/zalo-work-reminder-bot
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
```

### 2. Google Sheet

Sheet cần share **"Bất kỳ ai có đường liên kết"** (Anyone with the link) để bot đọc được.

> Bot dùng cách tải CSV trực tiếp từ Google Sheet, **KHÔNG cần Service Account**.

Kiểm tra: mở link này trong trình duyệt ẩn danh, nếu tải được CSV = OK:
```
https://docs.google.com/spreadsheets/d/1tdgynCsD8b3JjptyAvXNbZtnF5Ng6ChaFxQO4uHDYK8/export?format=csv&gid=1629674940
```

### 3. Cấu hình .env

```bash
cp .env.example .env
# Sửa các giá trị trong .env
```

Quan trọng:
- `ZALO_GROUP_NAME` — tên chính xác nhóm Zalo cần gửi nhắc
- API keys đã có sẵn từ bot cũ

### 4. Chạy bot

```bash
source .venv/bin/activate
python3 zalo_bot.py
```

Lần đầu chạy sẽ cần **quét QR đăng nhập Zalo** trên cửa sổ Chrome.

## Cấu trúc dự án

```
zalo-work-reminder-bot/
├── .env                 # Cấu hình (không commit)
├── .env.example         # Mẫu cấu hình
├── .gitignore
├── requirements.txt
├── README.md
├── zalo_bot.py          # Bot chính (Playwright + Zalo Web)
├── sheet_reader.py      # Đọc Google Sheet (CSV export, không cần auth)
├── message_builder.py   # Format tin nhắn nhắc việc
└── ai_helper.py         # AI hỗ trợ viết bài (multi-model fallback)
```

## LLM Providers

Bot hỗ trợ 3 provider miễn phí, tự động fallback nếu cái trước lỗi:

1. **OpenRouter** — `meta-llama/llama-4-maverick:free`
2. **Groq** — `llama-3.3-70b-versatile` (14,400 req/ngày)
3. **Gemini** — `gemini-2.0-flash` (fallback cuối)
