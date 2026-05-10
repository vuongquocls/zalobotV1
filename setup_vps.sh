#!/usr/bin/env bash
set -Eeuo pipefail

# Script cai dat Zalo Telegram Bridge tren VPS Ubuntu.

echo "Bat dau cai dat Zalo Telegram Bridge..."

# Cập nhật hệ thống
sudo apt update && sudo apt upgrade -y

# Cài đặt Node.js và PM2.
curl -fsSL https://deb.nodesource.com/setup_lts.x | sudo -E bash -
sudo apt install -y nodejs
sudo npm install -g pm2

npm ci
npm run build

echo "Cai dat hoan tat."
echo "------------------------------------------------"
echo "1. Tao file .env voi TG_TOKEN va TG_GROUP_ID."
echo "2. Chay: npm run dev"
echo "3. Neu chua dang nhap Zalo, gui /login trong Telegram group de quet QR."
echo ""
echo "Chay on dinh 24/7 bang PM2:"
echo "pm2 start pm2_zalo_bot.config.js --only zalo-bot --update-env"
echo "pm2 save"
echo "pm2 startup"
echo "------------------------------------------------"
