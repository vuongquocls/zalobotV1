#!/bin/bash
# ============================================
# LẤY MÃ QR ĐĂNG NHẬP ZALO TỪ VPS
# Double-click file này để tải mã QR về và quét
# ============================================

VPS_IP="103.72.56.225"
VPS_USER="root"
DEST_FILE="$HOME/Desktop/qr_code_zalo.png"

echo "📥 Đang tải mã QR từ VPS ($VPS_IP) về máy..."
echo ""

# Copy file qr_code.png từ VPS về Desktop
scp -o ConnectTimeout=10 -o StrictHostKeyChecking=no $VPS_USER@$VPS_IP:/root/zalobotV1/qr_code.png "$DEST_FILE"

if [ -f "$DEST_FILE" ]; then
    echo "✅ Đã tải xong! Đang mở ảnh..."
    open "$DEST_FILE"
    echo ""
    echo "▶️ Anh dùng điện thoại quét mã thật nhanh nhé."
    echo "▶️ Mã có thể bị đổi liên tục mỗi 30s. Nếu máy quét báo mã hết hạn, hãy chạy lại file này để tải mã mới nhất."
else
    echo "❌ Không tìm thấy file qr_code.png. Nguy cơ bot đã đăng nhập thành công hoặc đang bị lỗi khác."
fi

echo ""
echo "Nhấn phím bất kỳ để đóng cửa sổ này..."
read -n 1
