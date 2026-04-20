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

mapfile -t PROC_LINES <<<"$PROC_INFO"
PROC_NAME="${PROC_LINES[0]:-zalo-bot}"
PROC_STATUS="${PROC_LINES[1]:-unknown}"
PROC_PID="${PROC_LINES[2]:-0}"
PROC_SCRIPT="${PROC_LINES[3]:-}"
PROC_CWD="${PROC_LINES[4]:-}"
PROC_INTERPRETER="${PROC_LINES[5]:-}"
PROC_BUILD_ID="${PROC_LINES[6]:-}"

PORT_6080_STATUS="down"
if curl -fsI --max-time 5 "http://127.0.0.1:6080/vnc.html" >/dev/null 2>&1; then
  PORT_6080_STATUS="up"
fi

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

LAST_SESSION_READY="$(find_last_line 'session.ready')"
LAST_LOGIN_REQUIRED="$(find_last_line 'session.login_required')"
LAST_SIDEBAR_SCAN="$(find_last_line 'sidebar.scan')"
LAST_UNREAD_DETECTED="$(find_last_line 'unread.detected')"
LAST_CHAT_INSPECT="$(find_last_line 'chat.inspect')"
LAST_REPLY_SUCCESS="$(find_last_line 'reply.success')"
LAST_REPLY_ERROR="$(find_last_line 'reply.error')"
LAST_BOT_START="$(find_last_line 'bot.start')"

CONCLUSION="bot đang chạy tốt"
DETAIL="process online, port 6080=${PORT_6080_STATUS}"

if [[ "$PROC_STATUS" != "online" ]]; then
  CONCLUSION="bot chưa chạy"
  DETAIL="pm2 status=${PROC_STATUS}, pid=${PROC_PID}"
elif (( LAST_BOT_START == 0 )); then
  CONCLUSION="bot đang chạy nhưng chưa có log của bản mới"
  DETAIL="không thấy marker bot.start trong log gần nhất"
elif (( LAST_LOGIN_REQUIRED > LAST_SESSION_READY )); then
  CONCLUSION="bot đang chạy nhưng cần quét QR"
  DETAIL="log mới nhất nghiêng về session.login_required"
elif (( LAST_REPLY_ERROR > LAST_REPLY_SUCCESS )); then
  CONCLUSION="bot đang lỗi gửi reply"
  DETAIL="reply.error xuất hiện sau reply.success trong log gần nhất"
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
echo "Port 6080: ${PORT_6080_STATUS}"
echo "Log out: ${OUT_LOG}"
echo "Log err: ${ERR_LOG}"
echo "Marker bot.start: ${LAST_BOT_START}"
echo "Marker session.ready: ${LAST_SESSION_READY}"
echo "Marker session.login_required: ${LAST_LOGIN_REQUIRED}"
echo "Marker sidebar.scan: ${LAST_SIDEBAR_SCAN}"
echo "Marker unread.detected: ${LAST_UNREAD_DETECTED}"
echo "Marker chat.inspect: ${LAST_CHAT_INSPECT}"
echo "Marker reply.success: ${LAST_REPLY_SUCCESS}"
echo "Marker reply.error: ${LAST_REPLY_ERROR}"
