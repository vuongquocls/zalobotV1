#!/usr/bin/env bash
set -Eeuo pipefail

VPS_USER="root"
VPS_HOST="103.72.56.225"
REMOTE_DIR="/root/zalobotV1"

BATCH_SSH_OPTS=(
  -o BatchMode=yes
  -o ConnectTimeout=10
  -o ServerAliveInterval=30
  -o ServerAliveCountMax=3
  -o StrictHostKeyChecking=accept-new
)

INTERACTIVE_SSH_OPTS=(
  -o ConnectTimeout=10
  -o ServerAliveInterval=30
  -o ServerAliveCountMax=3
  -o StrictHostKeyChecking=accept-new
)

echo "Connecting to ${VPS_USER}@${VPS_HOST} ..."

if ! ssh "${BATCH_SSH_OPTS[@]}" "${VPS_USER}@${VPS_HOST}" "echo 'SSH key authentication OK'" >/dev/null 2>&1; then
  echo "SSH key authentication tự động thất bại với BatchMode=yes."
  echo "Thử kết nối lại 1 lần với ssh bình thường, không dùng BatchMode."
  echo
  if ! ssh "${INTERACTIVE_SSH_OPTS[@]}" "${VPS_USER}@${VPS_HOST}" "echo 'SSH interactive authentication OK'" >/dev/null 2>&1; then
    echo "SSH vẫn thất bại. Hãy kiểm tra SSH key, ssh-agent hoặc quyền truy cập tới ${VPS_USER}@${VPS_HOST}."
    echo
    echo "Gợi ý kiểm tra:"
    echo "  ssh ${VPS_USER}@${VPS_HOST}"
    echo "  ssh-add -l"
    echo
    read -r -n 1 -p "Nhấn phím bất kỳ để đóng cửa sổ..."
    echo
    exit 1
  fi
fi

ssh -tt "${INTERACTIVE_SSH_OPTS[@]}" "${VPS_USER}@${VPS_HOST}" <<EOF
set -Eeuo pipefail

cd "${REMOTE_DIR}" || {
  echo "Không tìm thấy thư mục repo: ${REMOTE_DIR}" >&2
  exit 1
}

if [[ ! -f "./deploy_and_run.sh" ]]; then
  echo "Thiếu file deploy_and_run.sh trong ${REMOTE_DIR}" >&2
  exit 1
fi

bash ./deploy_and_run.sh
echo
echo "===== PM2 LOGS: zalo-bot ====="
pm2 logs zalo-bot --lines 100 --nostream
EOF
