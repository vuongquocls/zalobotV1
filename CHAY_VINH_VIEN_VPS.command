#!/bin/bash
# ============================================
# CHAY_VINH_VIEN_VPS.command
# Deploy bot chay ngam vinh vien tren VPS.
# ============================================

clear
echo "THIET LAP CHAY VINH VIEN TREN VPS"
echo "===================================="
echo ""

ssh -o StrictHostKeyChecking=no root@103.72.56.225 'bash -s' << 'REMOTE_SCRIPT'

set -Eeuo pipefail

echo "=== 1/4 Cai Node dependencies va build ==="
cd /root/zalobotV1
git pull --ff-only
npm ci
npm run build

echo "=== 2/4 Them pm2 resurrect vao crontab @reboot ==="
crontab -l 2>/dev/null | grep -v "pm2 resurrect" > /tmp/cron_clean || true
echo "@reboot /usr/bin/pm2 resurrect" >> /tmp/cron_clean
crontab /tmp/cron_clean
rm -f /tmp/cron_clean
echo "Crontab updated."

echo "=== 3/4 Khoi dong bot bang PM2 ==="
pm2 delete zalo-bot 2>/dev/null
pm2 start pm2_zalo_bot.config.js --only zalo-bot --update-env
pm2 save

echo ""
echo "=== 4/4 Doi 20s de xem log ==="
sleep 20
pm2 logs zalo-bot --lines 15 --nostream

echo ""
echo "========================================="
echo "HOAN TAT. Bot dang chay vinh vien bang PM2."
echo "VPS restart se tu khoi dong lai bang pm2 resurrect."
echo "========================================="

REMOTE_SCRIPT

echo ""
echo "Xong. Anh co the dong cua so nay."
echo "Nhấn Enter..."
read
