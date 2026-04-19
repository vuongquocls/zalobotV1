#!/bin/bash
# ============================================
# CHAY_VĨNH_VIỄN_VPS.command
# Đảm bảo bot chạy ngầm vĩnh viễn trên VPS
# ============================================

clear
echo "🚀 THIẾT LẬP CHẠY VĨNH VIỄN TRÊN VPS"
echo "===================================="
echo ""

ssh -t -o StrictHostKeyChecking=no root@103.72.56.225 '
echo "=== 1/4 Cài đặt Screen & Persistence ==="
apt-get install -y screen 2>/dev/null
echo ""

echo "=== 2/4 Khởi động GUI ngầm (không chết khi đóng SSH) ==="
# Kiểm tra nếu chưa có Xvfb thì mới chạy
if ! pgrep -x "Xvfb" > /dev/null; then
    nohup Xvfb :99 -screen 0 1280x800x24 -ac > /dev/null 2>&1 &
    sleep 2
fi

if ! pgrep -x "fluxbox" > /dev/null; then
    DISPLAY=:99 nohup fluxbox > /dev/null 2>&1 &
fi

if ! pgrep -x "x11vnc" > /dev/null; then
    nohup x11vnc -display :99 -nopw -forever -shared -rfbport 5900 > /dev/null 2>&1 &
fi
echo "GUI Services are running in background."
echo ""

echo "=== 3/4 Cập nhật Code (KHÔNG xoá login) ==="
cd /root/zalobotV1
source .venv/bin/activate
git pull
echo ""

echo "=== 4/4 Khởi động Bot bằng PM2 ==="
pm2 delete zalo-bot 2>/dev/null
pm2 start ecosystem.config.js
pm2 save
pm2 startup
echo ""

echo "=== KẾT QUẢ HIỆN TẠI ==="
sleep 20
pm2 logs zalo-bot --lines 15 --nostream
echo ""
echo "✅ XONG! Bây giờ anh có thể TẮT MÁY LÀM VIỆC."
echo "Bot đã được quản lý bởi PM2 và screen ngầm trên VPS."
echo "noVNC vẫn mở tại: http://103.72.56.225:6080/"
echo "Nhấn Enter để kết thúc script này..."
read
'
