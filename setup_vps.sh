#!/bin/bash

# Script cài đặt Zalo Bot trên VPS Ubuntu
# Hướng dẫn:
# 1. Upload thư mục code lên VPS
# 2. Chạy lệnh: bash setup_vps.sh

echo "🚀 Bắt đầu cài đặt Zalo Bot..."

# Cập nhật hệ thống
sudo apt update && sudo apt upgrade -y

# Cài đặt Python và Pip
sudo apt install python3-pip python3-venv -y

# Cài đặt Node.js và PM2 (để chạy bot ngầm)
curl -fsSL https://deb.nodesource.com/setup_lts.x | sudo -E bash -
sudo apt install -y nodejs
sudo npm install -g pm2

# Tạo môi trường ảo và cài đặt dependencies
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

# Cài đặt trình duyệt cho Playwright (cần sudo để cài system deps)
playwright install chromium
sudo playwright install-deps chromium

echo "✅ Cài đặt hoàn tất!"
echo "------------------------------------------------"
echo "Để chạy bot lần đầu (cần quét QR):"
echo "1. Đảm bảo file .env đã chính xác"
echo "2. Chạy lệnh: source .venv/bin/activate && python3 zalo_bot.py"
echo "3. Copy file qr_code.png ra ngoài để quét mã"
echo ""
echo "Để chạy bot ổn định 24/7 bằng PM2:"
echo "pm2 start \"source .venv/bin/activate && python3 zalo_bot.py\" --name zalo-bot"
echo "pm2 save"
echo "pm2 startup"
echo "------------------------------------------------"
