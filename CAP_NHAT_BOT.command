#!/usr/bin/env bash
# ===========================================================
# CẬP NHẬT BOT ZALO LÊN VPS
# Double-click file này trên macOS để:
#   1. Git commit + push code mới nhất
#   2. SSH vào VPS → git pull → restart bot
#
# Nếu chưa có SSH key, script sẽ xin nhập mật khẩu.
# ===========================================================

VPS_USER="root"
VPS_HOST="103.72.56.225"
REMOTE_DIR="/root/zalobotV1"
LOCAL_DIR="$(cd "$(dirname "$0")" && pwd)"
PM2_APP="zalo-bot"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
CYAN='\033[0;36m'
NC='\033[0m'

log()  { printf "${GREEN}[%s] ✅ %s${NC}\n" "$(date '+%H:%M:%S')" "$*"; }
warn() { printf "${YELLOW}[%s] ⚠️  %s${NC}\n" "$(date '+%H:%M:%S')" "$*"; }
fail() { printf "${RED}[%s] ❌ %s${NC}\n" "$(date '+%H:%M:%S')" "$*"; }
info() { printf "${CYAN}[%s] ℹ️  %s${NC}\n" "$(date '+%H:%M:%S')" "$*"; }

echo ""
echo "=============================================="
echo "  🔄 CẬP NHẬT BOT ZALO LÊN VPS"
echo "=============================================="
echo ""

# ===== BƯỚC 1: Git commit + push =====
log "BƯỚC 1/3: Git commit + push"
cd "$LOCAL_DIR"

if [[ -n "$(git status --porcelain 2>/dev/null)" ]]; then
    git add -A
    COMMIT_MSG="update: cập nhật bot - $(date '+%Y-%m-%d %H:%M')"
    git commit -m "$COMMIT_MSG" || true
    log "Đã commit: $COMMIT_MSG"
else
    info "Không có thay đổi mới cần commit"
fi

info "Đang push lên GitHub..."
if git push 2>&1; then
    log "Push thành công"
else
    fail "Push thất bại!"
    read -r -p "Nhấn Enter để đóng..."
    exit 1
fi

echo ""

# ===== BƯỚC 2: SSH vào VPS và cập nhật =====
log "BƯỚC 2/3: Kết nối VPS và cập nhật code"

SSH_OPTS="-o ConnectTimeout=15 -o ServerAliveInterval=30 -o ServerAliveCountMax=3 -o StrictHostKeyChecking=accept-new"

# Chạy từng lệnh riêng qua SSH — tránh heredoc gây lỗi với password prompt
REMOTE_CMD="cd ${REMOTE_DIR} && echo '📥 Git fetch + reset...' && git fetch origin && git reset --hard origin/main && echo '✅ Git sync OK' && source .venv/bin/activate && pip install -q -r requirements.txt 2>/dev/null && echo '✅ Dependencies OK'"

info "Nhập mật khẩu VPS nếu được yêu cầu:"
echo ""

if ! ssh ${SSH_OPTS} "${VPS_USER}@${VPS_HOST}" "${REMOTE_CMD}"; then
    fail "Git pull trên VPS thất bại!"
    read -r -p "Nhấn Enter để đóng..."
    exit 1
fi

log "Code đã được cập nhật trên VPS"
echo ""

# ===== BƯỚC 3: Restart PM2 =====
log "BƯỚC 3/3: Restart bot trên VPS"

RESTART_CMD="cd ${REMOTE_DIR} && source .venv/bin/activate && export DISPLAY=:99 && if pm2 describe ${PM2_APP} >/dev/null 2>&1; then pm2 restart ${PM2_APP} --update-env; else SKIP_PIP_INSTALL=true SKIP_PLAYWRIGHT_INSTALL=true bash ./deploy_and_run.sh; fi && pm2 save && echo '' && echo '📊 PM2 Status:' && pm2 describe ${PM2_APP} 2>/dev/null | head -15 && echo '' && echo '📋 30 dòng log gần nhất:' && pm2 logs ${PM2_APP} --lines 30 --nostream 2>/dev/null"

info "Nhập mật khẩu VPS lần nữa nếu được yêu cầu:"
echo ""

if ! ssh ${SSH_OPTS} "${VPS_USER}@${VPS_HOST}" "${RESTART_CMD}"; then
    fail "Restart bot trên VPS thất bại!"
    read -r -p "Nhấn Enter để đóng..."
    exit 1
fi

echo ""
echo "=============================================="
echo "  🎉 CẬP NHẬT THÀNH CÔNG!"
echo "  Bot đã được restart trên VPS."
echo "=============================================="
echo ""
read -r -p "Nhấn Enter để đóng cửa sổ..."
