#!/bin/bash
# ============================================
# SIÊU CẤP CỨU BOT ZALO - FIX LỖI MÀN HÌNH ĐEN
# ============================================

VPS_IP="103.72.56.225"
VPS_USER="root"

echo "🚀 Bắt đầu SIÊU CẤP CỨU cho Bot Zalo ($VPS_IP)..."
echo "------------------------------------------------"

ssh -o ConnectTimeout=10 -o StrictHostKeyChecking=no $VPS_USER@$VPS_IP << 'REMOTE'
cd /root/zalobotV1

echo "1. Dừng và dọn sạch các tiến trình cũ (PM2, Xvfb, VNC, noVNC)..."
pm2 delete zalo-bot 2>/dev/null
killall python3 2>/dev/null
killall Xvfb fluxbox x11vnc websockify novnc 2>/dev/null
rm -f /tmp/.X99-lock
sleep 2

echo "2. Khởi động lại hệ thống màn hình ảo (DISPLAY=:99)..."
export DISPLAY=:99
Xvfb :99 -screen 0 1280x800x24 &
sleep 3
fluxbox &
sleep 2

echo "3. Bật kết nối VNC chuẩn..."
x11vnc -display :99 -forever -nopw -listen 0.0.0.0 -xkb -rfbport 5900 &
sleep 2

echo "4. Bật noVNC (Cổng 6080) để xem qua Web..."
# Thử nhiều đường dẫn noVNC phổ biến trên Ubuntu
if [ -d "/usr/share/novnc" ]; then
    websockify -D --web=/usr/share/novnc 6080 localhost:5900
elif [ -d "/usr/local/share/novnc" ]; then
    websockify -D --web=/usr/local/share/novnc 6080 localhost:5900
elif command -v novnc_proxy &> /dev/null; then
    novnc_proxy --vnc localhost:5900 --listen 6080 &
else
    # Fallback cho snap
    /snap/bin/novnc --vnc localhost:5900 --listen 6080 &
fi
sleep 2

echo "5. Khởi động lại Bot với cấu hình HEADFUL (Hiện màn hình)..."
# Ép PM2 chạy với DISPLAY=:99 và HEADLESS=false
pm2 start "export DISPLAY=:99 && export HEADLESS=false && cd /root/zalobotV1 && source .venv/bin/activate && python3 zalo_bot.py" --name zalo-bot
pm2 save
sleep 5

echo "------------------------------------------------"
echo "✅ HOÀN TẤT SIÊU CẤP CỨU!"
echo "👉 Anh hãy tải lại trang: http://103.72.56.225:6080/vnc.html"
echo "👉 Bấm Connect. Anh SẼ thấy trình duyệt Zalo hiện lên."
echo "👉 Nếu nó bắt quét mã, anh quét xong là bot chạy ngay!"
echo "------------------------------------------------"
REMOTE

echo ""
echo "Nhấn phím bất kỳ để hoàn thành..."
read -n 1
