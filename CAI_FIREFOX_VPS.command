#!/bin/bash
# ============================================
# CAI_FIREFOX_VPS.command
# Double-click file này để cài Firefox trên VPS
# Anh chỉ cần nhập mật khẩu VPS 1 lần duy nhất
# ============================================

clear
echo "🦊 CÀI FIREFOX CHO BOT ZALO"
echo "=========================="
echo ""

# Kết nối VPS và chạy tất cả
ssh -t -o StrictHostKeyChecking=no root@103.72.56.225 '
echo "=== 1/5 Cài Firefox cho Playwright ==="
cd /root/zalobotV1
source .venv/bin/activate
playwright install firefox
echo ""

echo "=== 2/5 Dọn Chrome cũ ==="
rm -rf /root/zalobotV1/zalo_profile
pkill -9 chromium 2>/dev/null
pkill -9 chrome 2>/dev/null
echo "Done"
echo ""

echo "=== 3/5 Pull code mới ==="
git pull
echo ""

echo "=== 4/5 Restart bot ==="
pm2 delete zalo-bot 2>/dev/null
pm2 start ecosystem.config.js
pm2 save
echo ""

echo "=== 5/5 Đợi 25 giây... ==="
sleep 25
echo ""

echo "=== KẾT QUẢ ==="
pm2 logs zalo-bot --lines 20 --nostream
echo ""
echo "✅ XONG! Hãy mở noVNC (http://103.72.56.225:6080/) để quét QR"
echo "Nhấn Enter để đóng..."
read
'

echo ""
echo "Nhấn Enter để đóng cửa sổ này..."
read
