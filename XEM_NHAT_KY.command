#!/bin/bash
# ============================================
# XEM NHẬT KÝ LIVE TRÊN VPS
# Double-click file này để xem bot đang làm gì
# ============================================

VPS_IP="103.72.56.225"
VPS_USER="root"

echo "🔍 Đang kết nối VPS ($VPS_IP) để xem trạng thái..."
echo "--- Nhấn Ctrl+C để thoát xem nhật ký ---"
echo ""

ssh -o ConnectTimeout=10 -o StrictHostKeyChecking=no $VPS_USER@$VPS_IP << 'REMOTE'
cd /root/zalobotV1

if [ -f "qr_code.png" ]; then
    echo "⚠️ LƯU Ý: Đã tìm thấy file qr_code.png trên VPS! Có thể bot đang chờ quét mã."
    echo "=========================================="
fi

echo "📋 NHẬT KÝ LIVE (Thực tế bot đang làm gì):"
echo "=========================================="
pm2 logs zalo-bot --lines 50
REMOTE

echo ""
echo "✅ Đã đóng kết nối!"
echo ""
echo "Nhấn phím bất kỳ để đóng cửa sổ này..."
read -n 1
