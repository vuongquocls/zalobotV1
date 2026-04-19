#!/bin/bash
# ============================================
# CHAY_VINH_VIEN_VPS.command
# Deploy bot chạy ngầm vĩnh viễn trên VPS
# Tắt terminal / tắt máy Mac → VPS vẫn chạy
# ============================================

clear
echo "🚀 THIẾT LẬP CHẠY VĨNH VIỄN TRÊN VPS"
echo "===================================="
echo ""

# == BƯỚC 1: Tạo startup script trên VPS ==
# Dùng ssh KHÔNG có -t → không gắn vào terminal
ssh -o StrictHostKeyChecking=no root@103.72.56.225 'bash -s' << 'REMOTE_SCRIPT'

echo "=== 1/5 Tạo file khởi động GUI ngầm ==="
cat > /root/start_gui.sh << 'EOF'
#!/bin/bash
# Khởi động màn hình ảo + VNC server
export DISPLAY=:99

# Xvfb
if ! pgrep -x "Xvfb" > /dev/null; then
    Xvfb :99 -screen 0 1280x800x24 -ac &
    sleep 2
fi

# Fluxbox window manager
if ! pgrep -x "fluxbox" > /dev/null; then
    DISPLAY=:99 fluxbox &
fi

# x11vnc cho noVNC
if ! pgrep -x "x11vnc" > /dev/null; then
    x11vnc -display :99 -nopw -forever -shared -rfbport 5900 &
fi

# noVNC websockify
if ! pgrep -f "websockify" > /dev/null; then
    cd /opt/noVNC && ./utils/novnc_proxy --vnc localhost:5900 --listen 6080 &
fi
EOF
chmod +x /root/start_gui.sh

echo "=== 2/5 Khởi động GUI ngầm ==="
/root/start_gui.sh
sleep 3
echo "GUI services started."

echo "=== 3/5 Thêm vào crontab @reboot (auto-start khi VPS restart) ==="
# Xoá entry cũ nếu có
crontab -l 2>/dev/null | grep -v "start_gui.sh" | grep -v "pm2 resurrect" > /tmp/cron_clean
echo "@reboot /root/start_gui.sh" >> /tmp/cron_clean
echo "@reboot /usr/bin/pm2 resurrect" >> /tmp/cron_clean
crontab /tmp/cron_clean
rm /tmp/cron_clean
echo "Crontab updated."

echo "=== 4/5 Cập nhật code ==="
cd /root/zalobotV1
source .venv/bin/activate
git pull

echo "=== 5/5 Khởi động bot bằng PM2 ==="
pm2 delete zalo-bot 2>/dev/null
pm2 start ecosystem.config.js
pm2 save

echo ""
echo "=== ĐỢI 20s ĐỂ XEM LOG ==="
sleep 20
pm2 logs zalo-bot --lines 15 --nostream

echo ""
echo "========================================="
echo "✅ HOÀN TẤT! Bot đang chạy vĩnh viễn."
echo "✅ Tắt terminal này KHÔNG ảnh hưởng gì."
echo "✅ VPS restart → tự động khởi động lại."
echo "✅ noVNC: http://103.72.56.225:6080/"
echo "========================================="

REMOTE_SCRIPT

echo ""
echo "🎉 Xong! Anh có thể đóng cửa sổ này."
echo "Nhấn Enter..."
read
