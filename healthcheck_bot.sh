#!/usr/bin/env bash
set -Eeuo pipefail

trap 'echo "[ERROR] healthcheck_bot.sh failed at line $LINENO" >&2' ERR

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
PM2_APP_NAME="zalo-bot"
PM2_HOME_DIR="${PM2_HOME:-$HOME/.pm2}"
OUT_LOG="$PROJECT_DIR/runtime-logs/${PM2_APP_NAME}-out.log"
ERR_LOG="$PROJECT_DIR/runtime-logs/${PM2_APP_NAME}-error.log"

if [[ ! -f "$OUT_LOG" ]]; then
  OUT_LOG="$PM2_HOME_DIR/logs/${PM2_APP_NAME}-out.log"
fi
if [[ ! -f "$ERR_LOG" ]]; then
  ERR_LOG="$PM2_HOME_DIR/logs/${PM2_APP_NAME}-error.log"
fi

log() {
  printf '[%s] %s\n' "$(date '+%F %T')" "$*"
}

if ! command -v pm2 >/dev/null 2>&1; then
  echo "Kết luận: bot chưa chạy"
  echo "Chi tiết: chưa có lệnh pm2 trong PATH"
  exit 1
fi

if ! command -v node >/dev/null 2>&1; then
  echo "Kết luận: không thể kiểm tra trạng thái bot"
  echo "Chi tiết: không thể parse pm2 jlist vì thiếu node"
  exit 1
fi

PM2_JSON="$(pm2 jlist 2>/dev/null || true)"
PROC_INFO="$(
  printf '%s' "$PM2_JSON" | node -e '
    const fs = require("fs");
    let data = "[]";
    try { data = fs.readFileSync(0, "utf8") || "[]"; } catch {}
    let list = [];
    try { list = JSON.parse(data); } catch {}
    const proc = list.find((item) => item && item.name === "zalo-bot");
    if (!proc) process.exit(1);
    console.log(proc.name || "");
    console.log((proc.pm2_env && proc.pm2_env.status) || "unknown");
    console.log(proc.pid || 0);
    console.log((proc.pm2_env && proc.pm2_env.pm_exec_path) || "");
    console.log((proc.pm2_env && proc.pm2_env.pm_cwd) || "");
    console.log((proc.pm2_env && proc.pm2_env.exec_interpreter) || "");
    console.log((proc.pm2_env && proc.pm2_env.APP_BUILD_ID) || "");
  ' 2>/dev/null || true
)"

if [[ -z "$PROC_INFO" ]]; then
  echo "Kết luận: bot chưa chạy"
  echo "Chi tiết: không tìm thấy process pm2 tên zalo-bot"
  exit 0
fi

PROC_NAME="$(printf '%s\n' "$PROC_INFO" | sed -n '1p')"
PROC_STATUS="$(printf '%s\n' "$PROC_INFO" | sed -n '2p')"
PROC_PID="$(printf '%s\n' "$PROC_INFO" | sed -n '3p')"
PROC_SCRIPT="$(printf '%s\n' "$PROC_INFO" | sed -n '4p')"
PROC_CWD="$(printf '%s\n' "$PROC_INFO" | sed -n '5p')"
PROC_INTERPRETER="$(printf '%s\n' "$PROC_INFO" | sed -n '6p')"
PROC_BUILD_ID="$(printf '%s\n' "$PROC_INFO" | sed -n '7p')"
PROC_NAME="${PROC_NAME:-zalo-bot}"
PROC_STATUS="${PROC_STATUS:-unknown}"
PROC_PID="${PROC_PID:-0}"

TMP_LOG="$(mktemp)"
cleanup() {
  rm -f "$TMP_LOG"
}
trap cleanup EXIT

{
  [[ -f "$OUT_LOG" ]] && tail -n 1000 "$OUT_LOG"
  [[ -f "$ERR_LOG" ]] && tail -n 500 "$ERR_LOG"
} >"$TMP_LOG"

find_last_line() {
  local pattern="$1"
  local line
  line="$(grep -n "$pattern" "$TMP_LOG" | tail -n 1 | cut -d: -f1 || true)"
  if [[ -n "$line" ]]; then
    echo "$line"
  else
    echo 0
  fi
}

LAST_BRIDGE_RUNNING="$(find_last_line 'Bridge is running')"
LAST_TG_STARTED="$(find_last_line 'Telegram bot started')"
LAST_ZALO_STARTED="$(find_last_line 'Zalo listener started')"
LAST_ZALO_AUTO_LOGIN_FAILED="$(find_last_line 'Zalo auto-login failed')"
LAST_MISSING_TG_TOKEN="$(find_last_line 'Missing required environment variable: TG_TOKEN')"
LAST_MISSING_TG_GROUP="$(find_last_line 'Missing required environment variable: TG_GROUP_ID')"
LAST_FATAL="$(find_last_line 'Fatal error')"

CONCLUSION="bot đang chạy tốt"
DETAIL="process online"

if [[ "$PROC_STATUS" != "online" ]]; then
  CONCLUSION="bot chưa chạy"
  DETAIL="pm2 status=${PROC_STATUS}, pid=${PROC_PID}"
elif (( LAST_MISSING_TG_TOKEN > 0 || LAST_MISSING_TG_GROUP > 0 )); then
  CONCLUSION="bot thiếu cấu hình Telegram"
  DETAIL="thiếu TG_TOKEN hoặc TG_GROUP_ID trong .env"
elif (( LAST_ZALO_STARTED > 0 )); then
  CONCLUSION="bot đang chạy tốt"
  DETAIL="Telegram đã chạy, Zalo listener đã khởi động"
elif (( LAST_BRIDGE_RUNNING == 0 && LAST_TG_STARTED == 0 )); then
  CONCLUSION="bot đang chạy nhưng chưa có log của bản mới"
  DETAIL="không thấy marker Bridge is running hoặc Telegram bot started"
elif (( LAST_ZALO_AUTO_LOGIN_FAILED > LAST_ZALO_STARTED )); then
  CONCLUSION="bot Telegram đã chạy, Zalo cần đăng nhập"
  DETAIL="gửi /login trong Telegram group để quét QR Zalo"
elif (( LAST_FATAL > LAST_BRIDGE_RUNNING )); then
  CONCLUSION="bot có lỗi fatal sau khi khởi động"
  DETAIL="xem log err để lấy stack trace"
fi

echo "Kết luận: ${CONCLUSION}"
echo "Chi tiết: ${DETAIL}"
echo "PM2 process: ${PROC_NAME}"
echo "PM2 status: ${PROC_STATUS}"
echo "PM2 pid: ${PROC_PID}"
echo "PM2 script: ${PROC_SCRIPT}"
echo "PM2 cwd: ${PROC_CWD}"
echo "PM2 interpreter: ${PROC_INTERPRETER}"
echo "PM2 build_id: ${PROC_BUILD_ID}"
echo "Project dir: ${PROJECT_DIR}"
echo "Log out: ${OUT_LOG}"
echo "Log err: ${ERR_LOG}"
echo "Marker bridge.running: ${LAST_BRIDGE_RUNNING}"
echo "Marker telegram.started: ${LAST_TG_STARTED}"
echo "Marker zalo.started: ${LAST_ZALO_STARTED}"
echo "Marker zalo.auto_login_failed: ${LAST_ZALO_AUTO_LOGIN_FAILED}"
echo "Marker missing_tg_token: ${LAST_MISSING_TG_TOKEN}"
echo "Marker missing_tg_group: ${LAST_MISSING_TG_GROUP}"
echo "Marker fatal: ${LAST_FATAL}"
