#!/usr/bin/env bash
set -Eeuo pipefail

trap 'echo "[ERROR] restart_display.sh failed at line $LINENO" >&2' ERR

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
DISPLAY_VALUE="${DISPLAY_VALUE:-:99}"
VNC_PORT="${VNC_PORT:-5900}"
NOVNC_PORT="${NOVNC_PORT:-6080}"
RUNTIME_LOG_DIR="$PROJECT_DIR/runtime-logs"
XVFB_PID_FILE="$RUNTIME_LOG_DIR/xvfb.pid"
FLUXBOX_PID_FILE="$RUNTIME_LOG_DIR/fluxbox.pid"
X11VNC_PID_FILE="$RUNTIME_LOG_DIR/x11vnc.pid"
WEBSOCKIFY_PID_FILE="$RUNTIME_LOG_DIR/websockify.pid"

log() {
  printf '[%s] %s\n' "$(date '+%F %T')" "$*"
}

require_cmd() {
  local cmd="$1"
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "[ERROR] Required command not found: $cmd" >&2
    exit 1
  fi
}

detect_novnc_webroot() {
  local candidate
  for candidate in /usr/share/novnc /usr/local/share/novnc; do
    if [[ -d "$candidate" ]]; then
      echo "$candidate"
      return 0
    fi
  done
  return 1
}

require_cmd Xvfb
require_cmd fluxbox
require_cmd x11vnc
require_cmd websockify

stop_pid_file() {
  local pid_file="$1"
  if [[ -f "$pid_file" ]]; then
    local pid
    pid="$(cat "$pid_file" 2>/dev/null || true)"
    if [[ -n "$pid" ]] && kill -0 "$pid" >/dev/null 2>&1; then
      kill "$pid" >/dev/null 2>&1 || true
      sleep 1
      kill -9 "$pid" >/dev/null 2>&1 || true
    fi
    rm -f "$pid_file"
  fi
}

NOVNC_WEBROOT="$(detect_novnc_webroot || true)"
if [[ -z "$NOVNC_WEBROOT" ]]; then
  echo "[ERROR] noVNC web root not found in /usr/share/novnc or /usr/local/share/novnc" >&2
  exit 1
fi

mkdir -p "$RUNTIME_LOG_DIR"
export DISPLAY="$DISPLAY_VALUE"

log "Stopping old display stack"
stop_pid_file "$XVFB_PID_FILE"
stop_pid_file "$FLUXBOX_PID_FILE"
stop_pid_file "$X11VNC_PID_FILE"
stop_pid_file "$WEBSOCKIFY_PID_FILE"
pkill -f "^Xvfb ${DISPLAY_VALUE} " >/dev/null 2>&1 || true
pkill -f "^x11vnc .* -rfbport ${VNC_PORT}($| )" >/dev/null 2>&1 || true
pkill -f "^websockify .* ${NOVNC_PORT} localhost:${VNC_PORT}($| )" >/dev/null 2>&1 || true
rm -f "/tmp/.X${DISPLAY_VALUE#:}-lock"
sleep 1

log "Starting Xvfb on ${DISPLAY_VALUE}"
nohup Xvfb "$DISPLAY_VALUE" -screen 0 1280x800x24 >"$RUNTIME_LOG_DIR/xvfb.log" 2>&1 &
echo $! >"$XVFB_PID_FILE"
sleep 2

log "Starting fluxbox"
nohup fluxbox >"$RUNTIME_LOG_DIR/fluxbox.log" 2>&1 &
echo $! >"$FLUXBOX_PID_FILE"
sleep 1

log "Starting x11vnc on port ${VNC_PORT}"
nohup x11vnc -display "$DISPLAY_VALUE" -forever -nopw -listen 0.0.0.0 -xkb -rfbport "$VNC_PORT" >"$RUNTIME_LOG_DIR/x11vnc.log" 2>&1 &
echo $! >"$X11VNC_PID_FILE"
sleep 2

log "Starting websockify/noVNC on port ${NOVNC_PORT}"
nohup websockify --web="$NOVNC_WEBROOT" "$NOVNC_PORT" "localhost:${VNC_PORT}" >"$RUNTIME_LOG_DIR/websockify.log" 2>&1 &
echo $! >"$WEBSOCKIFY_PID_FILE"
sleep 2

log "Display stack restarted"
log "noVNC URL: http://127.0.0.1:${NOVNC_PORT}/vnc.html"
