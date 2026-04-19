#!/bin/bash
# ============================================
# FIX_VIEWPORT_VPS.command
# Tăng màn hình ảo + viewport cho đủ rộng hiện ô chat
# ============================================

clear
echo "🖥️ FIX KÍCH THƯỚC MÀN HÌNH"
echo "==========================="
echo ""

ssh -t -o StrictHostKeyChecking=no root@103.72.56.225 '
echo "=== 1/4 Tăng màn hình ảo lên 1280x800 ==="
pkill -9 Xvfb 2>/dev/null
sleep 1
Xvfb :99 -screen 0 1280x800x24 -ac &
sleep 2
echo "Xvfb restarted at 1280x800"

echo "=== 2/4 Restart x11vnc ==="
pkill -9 x11vnc 2>/dev/null
sleep 1
x11vnc -display :99 -nopw -forever -shared -rfbport 5900 &
sleep 2
echo "x11vnc restarted"

echo "=== 3/4 Restart fluxbox ==="
pkill -9 fluxbox 2>/dev/null
DISPLAY=:99 fluxbox &
sleep 1

echo "=== 4/4 Pull code mới + restart bot ==="
cd /root/zalobotV1
source .venv/bin/activate
git pull
rm -rf /root/zalobotV1/zalo_profile
pm2 delete zalo-bot 2>/dev/null
pm2 start ecosystem.config.js
pm2 save
sleep 20
pm2 logs zalo-bot --lines 10 --nostream

echo ""
echo "✅ XONG! Mở noVNC quét QR: http://103.72.56.225:6080/"
echo "Nhấn Enter để đóng..."
read
'

echo "Nhấn Enter..."
read
