#!/bin/bash
# LAM_SACH_VPS.sh — Dọn dẹp và cài đặt lại môi trường Zalo Bot
# Chạy lệnh này trên VPS (root)

echo "--- 🛑 1. Dừng Bot và dọn dẹp tiến trình cũ ---"
pm2 stop zalo-bot || true
pkill -f chromium || true
pkill -f chrome || true

echo "--- 🧹 2. Xoá Profile cũ (Bị lỗi 'Restore' và 'Mất ô chat') ---"
# Chú ý: Việc này sẽ yêu cầu quét lại mã QR 1 lần duy nhất
rm -rf /root/zalobotV1/zalo_profile
rm -rf /root/.cache/ms-playwright

echo "--- 📥 3. Cập nhật Code mới nhất (Refactored) ---"
cd /root/zalobotV1
git fetch origin
git reset --hard origin/main

echo "--- 🚀 4. Cài đặt lại Chromium và Dependencies ---"
# Cài đặt các thư viện hệ thống cần thiết cho trình duyệt
npx playwright install-deps chromium
# Cài đặt bản Chromium sạch
npx playwright install chromium

echo "--- 🏁 5. Khởi động lại Bot ---"
pm2 restart zalo-bot --update-env
pm2 save

echo ""
echo "✅ HOÀN TẤT! Anh hãy đợi 30 giây rồi mở noVNC quét mã QR."
echo "Sau khi quét xong, Zalo sẽ tự khởi động lại sạch sẽ và hiện ô chat."
