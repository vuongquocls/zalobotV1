#!/bin/bash
# ============================================
# KHỞI ĐỘNG LẠI MÀN HÌNH VÀ NOVNC
# ============================================

VPS_IP="103.72.56.225"
VPS_USER="root"

echo "🔧 Đang kết nối VPS để sửa lỗi màn hình ảo..."
echo ""

ssh -o ConnectTimeout=10 -o StrictHostKeyChecking=no $VPS_USER@$VPS_IP << 'REMOTE'
echo "Dọn dẹp các tiến trình màn hình cũ..."
killall Xvfb fluxbox x11vnc websockify 2>/dev/null
rm -f /tmp/.X99-lock
sleep 1

echo "Khởi động Xvfb (Màn hình ảo)..."
export DISPLAY=:99
Xvfb :99 -screen 0 1280x800x24 &
sleep 2
fluxbox &
sleep 1

echo "Khởi động x11vnc..."
x11vnc -display :99 -forever -nopw -listen 0.0.0.0 -xkb -rfbport 5900 &
sleep 2

echo "Khởi động websockify (noVNC)..."
if [ -d "/usr/share/novnc" ]; then
    websockify -D --web=/usr/share/novnc 6080 localhost:5900
elif command -v novnc_proxy &> /dev/null; then
    novnc_proxy --vnc localhost:5900 --listen 6080 &
elif command -v websockify &> /dev/null; then
    websockify -D --web=/usr/local/share/novnc 6080 localhost:5900
else
    # Fallback to snap if exists
    /snap/bin/novnc --vnc localhost:5900 --listen 6080 &
fi

echo "=========================================="
echo "✅ Xong! Hãy thử kết nối lại noVNC."
REMOTE

echo ""
echo "Nhấn phím bất kỳ để đóng cửa sổ này..."
read -n 1
