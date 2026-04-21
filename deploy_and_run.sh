#!/usr/bin/env bash
set -Eeuo pipefail

trap 'echo "[ERROR] deploy_and_run.sh failed at line $LINENO" >&2' ERR

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="$PROJECT_DIR/.venv"
DISPLAY_VALUE="${DISPLAY_VALUE:-:99}"
HEADLESS_VALUE="${HEADLESS_VALUE:-false}"
PLAYWRIGHT_BROWSER="${PLAYWRIGHT_BROWSER:-chromium}"
SKIP_PIP_INSTALL="${SKIP_PIP_INSTALL:-false}"
SKIP_PLAYWRIGHT_INSTALL="${SKIP_PLAYWRIGHT_INSTALL:-false}"
PM2_APP_NAME="zalo-bot"
RUNTIME_LOG_DIR="$PROJECT_DIR/runtime-logs"
BUILD_ID="$(git rev-parse --short HEAD 2>/dev/null || date '+%Y%m%d%H%M%S')"

log() {
  printf '[%s] %s\n' "$(date '+%F %T')" "$*"
}

require_file() {
  local path="$1"
  local label="$2"
  if [[ ! -e "$path" ]]; then
    echo "[ERROR] Missing ${label}: $path" >&2
    exit 1
  fi
}

require_cmd() {
  local cmd="$1"
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "[ERROR] Required command not found: $cmd" >&2
    exit 1
  fi
}

ensure_display_stack() {
  local needs_restart="false"

  if ! pgrep -f "Xvfb ${DISPLAY_VALUE}" >/dev/null 2>&1; then
    log "Xvfb is not running on ${DISPLAY_VALUE}"
    needs_restart="true"
  fi
  if ! pgrep -x fluxbox >/dev/null 2>&1; then
    log "fluxbox is not running"
    needs_restart="true"
  fi
  if ! pgrep -f "x11vnc .*5900" >/dev/null 2>&1; then
    log "x11vnc is not running on port 5900"
    needs_restart="true"
  fi
  if ! curl -fsI --max-time 5 "http://127.0.0.1:6080/vnc.html" >/dev/null 2>&1; then
    log "websockify/noVNC is not responding on port 6080"
    needs_restart="true"
  fi

  if [[ "$needs_restart" == "true" ]]; then
    log "Restarting display stack"
    bash "$PROJECT_DIR/restart_display.sh"
  else
    log "Display stack is healthy"
  fi
}

log "Project directory: $PROJECT_DIR"
cd "$PROJECT_DIR"

require_file "$PROJECT_DIR/zalo_bot.py" "bot entrypoint"
require_file "$PROJECT_DIR/requirements.txt" "requirements.txt"
require_file "$PROJECT_DIR/restart_display.sh" "restart_display.sh"
require_file "$PROJECT_DIR/pm2_zalo_bot.config.js" "pm2_zalo_bot.config.js"

require_cmd python3
require_cmd pm2
require_cmd node
require_cmd curl

mkdir -p "$RUNTIME_LOG_DIR"

if [[ ! -d "$VENV_DIR" ]]; then
  log "Creating virtualenv at $VENV_DIR"
  python3 -m venv "$VENV_DIR"
fi

# Activate project virtualenv.
source "$VENV_DIR/bin/activate"

if [[ "$SKIP_PIP_INSTALL" == "true" ]]; then
  log "Skipping Python dependency install because SKIP_PIP_INSTALL=true"
else
  log "Installing Python dependencies"
  python -m pip install --upgrade pip
  python -m pip install -r "$PROJECT_DIR/requirements.txt"
fi

if [[ "$SKIP_PLAYWRIGHT_INSTALL" == "true" ]]; then
  log "Skipping Playwright browser install because SKIP_PLAYWRIGHT_INSTALL=true"
else
  log "Installing Playwright browser: $PLAYWRIGHT_BROWSER"
  python -m playwright install "$PLAYWRIGHT_BROWSER"
fi

export DISPLAY="$DISPLAY_VALUE"
export HEADLESS="$HEADLESS_VALUE"
export PLAYWRIGHT_BROWSER="$PLAYWRIGHT_BROWSER"
export PYTHONUNBUFFERED=1
export APP_BUILD_ID="$BUILD_ID"
export TZ="${TZ:-Asia/Ho_Chi_Minh}"
export BOT_TIMEZONE="${BOT_TIMEZONE:-Asia/Ho_Chi_Minh}"

ensure_display_stack

log "Starting clean pm2 app: $PM2_APP_NAME (build ${BUILD_ID})"
pm2 delete "$PM2_APP_NAME" >/dev/null 2>&1 || true
pm2 start "$PROJECT_DIR/pm2_zalo_bot.config.js" --only "$PM2_APP_NAME" --update-env
pm2 save

log "PM2 status"
pm2 describe "$PM2_APP_NAME"

log "PM2 resolved script"
pm2 jlist | node -e '
  const fs = require("fs");
  const data = JSON.parse(fs.readFileSync(0, "utf8") || "[]");
  const proc = data.find((item) => item && item.name === "zalo-bot");
  if (!proc) process.exit(1);
  const env = proc.pm2_env || {};
  console.log(JSON.stringify({
    name: proc.name,
    status: env.status,
    pm_exec_path: env.pm_exec_path,
    pm_cwd: env.pm_cwd,
    interpreter: env.exec_interpreter,
    build_id: env.APP_BUILD_ID || ""
  }, null, 2));
'

log "Last 50 log lines"
pm2 logs "$PM2_APP_NAME" --lines 50 --nostream
