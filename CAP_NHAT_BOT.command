#!/usr/bin/env bash
# ===========================================================
# CẬP NHẬT BOT ZALO LÊN VPS
# Double-click file này trên macOS để:
#   1. Git commit + push code mới nhất
#   2. SSH vào VPS → git pull → restart bot
# ===========================================================
set -Eeuo pipefail

VPS_USER="root"
VPS_HOST="103.72.56.225"
REMOTE_DIR="/root/zalobotV1"
LOCAL_DIR="$(cd "$(dirname "$0")" && pwd)"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

log()  { printf "${GREEN}[%s] %s${NC}\n" "$(date '+%H:%M:%S')" "$*"; }
warn() { printf "${YELLOW}[%s] ⚠️  %s${NC}\n" "$(date '+%H:%M:%S')" "$*"; }
fail() { printf "${RED}[%s] ❌ %s${NC}\n" "$(date '+%H:%M:%S')" "$*"; }

echo ""
echo "=============================================="
echo "  🔄 CẬP NHẬT BOT ZALO LÊN VPS"
echo "=============================================="
echo ""

# ===== BƯỚC 1: Git commit + push =====
log "BƯỚC 1: Git commit + push từ máy local"
cd "$LOCAL_DIR"

if [[ -n "$(git status --porcelain 2>/dev/null)" ]]; then
    git add -A
    COMMIT_MSG="fix: sửa 4 bugs khiến bot im lặng - $(date '+%Y-%m-%d %H:%M')"
    git commit -m "$COMMIT_MSG"
    log "Đã commit: $COMMIT_MSG"
else
    log "Không có thay đổi mới cần commit"
fi

# Push
log "Đang push lên GitHub..."
if git push 2>&1; then
    log "Push thành công ✅"
else
    fail "Push thất bại. Kiểm tra lại quyền truy cập GitHub."
    read -r -n 1 -p "Nhấn phím bất kỳ để đóng..."
    exit 1
fi

echo ""

# ===== BƯỚC 2: SSH vào VPS =====
log "BƯỚC 2: Kết nối VPS ${VPS_USER}@${VPS_HOST}"

SSH_OPTS=(
    -o ConnectTimeout=15
    -o ServerAliveInterval=30
    -o ServerAliveCountMax=3
    -o StrictHostKeyChecking=accept-new
)

# Thử SSH key trước
if ssh -o BatchMode=yes "${SSH_OPTS[@]}" "${VPS_USER}@${VPS_HOST}" "echo ok" >/dev/null 2>&1; then
    log "SSH key xác thực thành công"
else
    warn "SSH key không hoạt động. Bạn sẽ cần nhập mật khẩu VPS."
fi

# SSH vào VPS và cập nhật
ssh -tt "${SSH_OPTS[@]}" "${VPS_USER}@${VPS_HOST}" <<'REMOTE_SCRIPT'
set -Eeuo pipefail

REMOTE_DIR="/root/zalobotV1"
PM2_APP="zalo-bot"

echo ""
echo "🖥️  Đang trên VPS..."
echo ""

cd "$REMOTE_DIR" || {
    echo "❌ Không tìm thấy thư mục $REMOTE_DIR"
    exit 1
}

# Git pull
echo "📥 Git pull..."
git pull --ff-only || {
    echo "❌ Git pull thất bại. Có thể có conflict."
    exit 1
}
echo "✅ Git pull thành công"

# Cài dependencies nếu requirements.txt đổi
echo "📦 Cài Python dependencies..."
source .venv/bin/activate 2>/dev/null || {
    python3 -m venv .venv
    source .venv/bin/activate
}
pip install -q -r requirements.txt 2>/dev/null

# Restart PM2
echo "🔄 Restart pm2: ${PM2_APP}..."
if pm2 describe "$PM2_APP" >/dev/null 2>&1; then
    pm2 restart "$PM2_APP" --update-env
else
    # Nếu chưa có process, start mới
    SKIP_PIP_INSTALL=true SKIP_PLAYWRIGHT_INSTALL=true bash ./deploy_and_run.sh
fi
pm2 save

echo ""
echo "=============================================="
echo "  ✅ CẬP NHẬT THÀNH CÔNG!"
echo "=============================================="
echo ""

# Hiện log mới nhất
echo "📋 Log 30 dòng gần nhất:"
echo "----------------------------------------------"
pm2 logs "$PM2_APP" --lines 30 --nostream 2>/dev/null || true
echo ""

# Hiện status
echo "📊 PM2 Status:"
pm2 describe "$PM2_APP" 2>/dev/null | head -20 || true

REMOTE_SCRIPT

echo ""
log "🎉 Hoàn tất! Bot đã được cập nhật trên VPS."
echo ""
read -r -n 1 -p "Nhấn phím bất kỳ để đóng cửa sổ..."
echo ""
