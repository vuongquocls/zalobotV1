#!/usr/bin/env bash
set -Eeuo pipefail

VPS_USER="root"
VPS_HOST="103.72.56.225"
REMOTE_DIR="/root/zalobotV1"
LOCAL_DIR="$(cd "$(dirname "$0")" && pwd)"
PLAYWRIGHT_BROWSER="${PLAYWRIGHT_BROWSER:-chromium}"
SSH_OPTS="-o ConnectTimeout=15 -o ServerAliveInterval=30 -o ServerAliveCountMax=3 -o StrictHostKeyChecking=accept-new"

log() {
  printf '[%s] %s\n' "$(date '+%H:%M:%S')" "$*"
}

pause_and_exit() {
  local code="$1"
  echo ""
  read -r -p "Nhan Enter de dong cua so..."
  exit "$code"
}

clear
echo "=============================================="
echo " CAP NHAT BOT ZALO LEN VPS"
echo "=============================================="
echo ""

cd "$LOCAL_DIR"

CURRENT_BRANCH="$(git branch --show-current)"
if [[ -z "$CURRENT_BRANCH" ]]; then
  echo "Khong xac dinh duoc branch hien tai."
  pause_and_exit 1
fi

log "Dang dung branch: $CURRENT_BRANCH"

if [[ -n "$(git status --porcelain 2>/dev/null)" ]]; then
  log "Co thay doi moi. Dang commit tu dong."
  git add -A
  COMMIT_MSG="update bot $(date '+%Y-%m-%d %H:%M:%S')"
  if ! git commit -m "$COMMIT_MSG"; then
    log "Khong tao commit moi, co the chi la file khong doi noi dung."
  else
    log "Da commit: $COMMIT_MSG"
  fi
else
  log "Khong co thay doi moi o may Mac."
fi

log "Dang push len GitHub..."
if ! git push origin "$CURRENT_BRANCH"; then
  echo "Push that bai."
  pause_and_exit 1
fi
log "Push thanh cong."

REMOTE_CMD=$(cat <<EOF
set -Eeuo pipefail
cd "$REMOTE_DIR"
echo "[REMOTE] Dang o thu muc: $REMOTE_DIR"
git fetch origin
git checkout "$CURRENT_BRANCH"
git pull --ff-only origin "$CURRENT_BRANCH"
export PLAYWRIGHT_BROWSER="$PLAYWRIGHT_BROWSER"
export DISPLAY_VALUE=:99
export HEADLESS_VALUE=false
bash ./deploy_and_run.sh
echo ""
echo "[REMOTE] Kiem tra nhanh tinh trang bot"
bash ./healthcheck_bot.sh || true
EOF
)

echo ""
log "Dang ket noi VPS de cap nhat va restart bot..."
echo "Neu duoc hoi mat khau VPS, anh/chị nhap mat khau root."
echo ""

if ! ssh ${SSH_OPTS} "${VPS_USER}@${VPS_HOST}" "${REMOTE_CMD}"; then
  echo ""
  echo "Cap nhat tren VPS that bai."
  pause_and_exit 1
fi

echo ""
echo "=============================================="
echo " HOAN TAT"
echo " Bot da duoc cap nhat va restart tren VPS."
echo "=============================================="
pause_and_exit 0
