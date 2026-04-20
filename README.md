# Zalo Work Reminder Bot

Bot Zalo tự động nhắc việc cho nhóm Truyền thông VQG Yok Đôn.

## Tính năng

- **Nhắc việc tự động** hàng ngày lúc 8h sáng (cấu hình được)
- **Đọc Google Sheet** từ link docs.google.com hoặc link `redirect.zalo.me/...`
- **Phân loại**: quá hạn / hôm nay / sắp đến hạn / chưa giao
- **Nhắc khi Sheet trống**: nếu hôm nay chưa có nội dung → nhắc mọi người điền
- **Trả lời tin nhắn cá nhân**
- **Trả lời trong nhóm khi được nhắc tên hoặc dùng lệnh**
- **Ghi nhớ điều người dùng dạy bot** qua lệnh `/hoc`
- **Hỗ trợ viết bài** bằng AI (OpenRouter → Groq → Gemini fallback)

## Lệnh

| Lệnh | Mô tả |
|-------|--------|
| `/nhacviec` | Nhắc việc ngay (đọc Sheet) |
| `/xemviec` | Xem danh sách việc chưa xong |
| `/hotrobai [mô tả]` | AI gợi ý nội dung bài viết |
| `/hoc [nội dung]` | Dạy bot ghi nhớ một nguyên tắc/nội dung |
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

Neu anh/chi dang co link dang:
```text
https://redirect.zalo.me/v3/verifyv2/pc?...&continue=https%3A%2F%2Fdocs.google.com%2Fspreadsheets%2F...
```
thi co the dat truc tiep vao bien `GOOGLE_SHEET_SOURCE_URL`, bot se tu tach ra link Google Sheet that su.

### 3. Cấu hình .env

```bash
cp .env.example .env
# Sửa các giá trị trong .env
```

Quan trọng:
- `GOOGLE_SHEET_SOURCE_URL` — co the dan link `redirect.zalo.me/...` vao day
- `ZALO_GROUP_NAME` — tên chính xác nhóm Zalo cần gửi nhắc
- API keys đã có sẵn từ bot cũ
- `PLAYWRIGHT_BROWSER` — de mac dinh la `chromium`, nen giu nguyen tren VPS

### 4. Chạy bot

```bash
source .venv/bin/activate
python3 zalo_bot.py
```

Lần đầu chạy sẽ cần **quét QR đăng nhập Zalo** trên cửa sổ Chrome.

## Deploy len VPS bang 1 file .command

File uu tien de su dung la:

```bash
CAP_NHAT_BOT.command
```

File nay se tu lam cac viec:
1. Commit code moi o may Mac.
2. Push len GitHub.
3. SSH vao VPS `103.72.56.225`.
4. `git pull --ff-only` o VPS.
5. Cai dependency neu can.
6. Cai dung browser Playwright.
7. Restart bot bang PM2.

Neu macOS bao file chua duoc phep chay:
```bash
chmod +x /Users/mt/Antigranvity/zalo-work-reminder-bot/CAP_NHAT_BOT.command
```

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
