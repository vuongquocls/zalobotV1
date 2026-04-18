# Sử dụng image Python chính thức
FROM python:3.10-slim

# Cài đặt các phụ thuộc hệ thống cho Playwright
RUN apt-get update && apt-get install -y \
    curl \
    gnupg \
    && curl -fsSL https://deb.nodesource.com/setup_lts.x | bash - \
    && apt-get install -y nodejs \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# Thiết lập thư mục làm việc
WORKDIR /app

# Copy các file cần thiết
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Cài đặt browser và dependencies
RUN playwright install chromium
RUN playwright install-deps chromium

# Copy toàn bộ code
COPY . .

# Chạy bot
ENV HEADLESS=true
CMD ["python", "zalo_bot.py"]
