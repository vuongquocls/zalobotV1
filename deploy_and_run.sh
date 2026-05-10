#!/usr/bin/env bash
set -Eeuo pipefail

trap 'echo "[ERROR] deploy_and_run.sh failed at line $LINENO" >&2' ERR

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
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

log "Project directory: $PROJECT_DIR"
cd "$PROJECT_DIR"

require_file "$PROJECT_DIR/package.json" "package.json"
require_file "$PROJECT_DIR/package-lock.json" "package-lock.json"
require_file "$PROJECT_DIR/tsconfig.json" "tsconfig.json"
require_file "$PROJECT_DIR/pm2_zalo_bot.config.js" "pm2_zalo_bot.config.js"

require_cmd node
require_cmd npm
require_cmd pm2

mkdir -p "$RUNTIME_LOG_DIR"

log "Node: $(node --version)"
log "npm: $(npm --version)"

log "Installing Node dependencies"
npm ci

log "Building TypeScript bridge"
npm run build

export APP_BUILD_ID="$BUILD_ID"
export TZ="${TZ:-Asia/Ho_Chi_Minh}"

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
