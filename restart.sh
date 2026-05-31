#!/usr/bin/env bash
# restart.sh — Kill stale instances, then start api + worker + frontend.
# Usage:
#   ./restart.sh          Full restart (kill + start)
#   ./restart.sh --kill   Kill only, don't restart
#   ./restart.sh --once   Start without killing first (for fresh machines)
set -euo pipefail
cd "$(dirname "$0")"

# ── Colours ──────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'

# ── PIDs / log files ────────────────────────────────────────────────────────
PIDDIR=".pids"
LOGDIR=".logs"
mkdir -p "$PIDDIR" "$LOGDIR"

kill_by_port() {
  local port=$1
  local pids
  pids=$(lsof -ti :"$port" 2>/dev/null || true)
  if [ -n "$pids" ]; then
    echo -e "${YELLOW}Killing stale processes on :${port}: ${pids}${NC}"
    echo "$pids" | xargs kill -9 2>/dev/null || true
    sleep 0.5
  fi
}

kill_by_pattern() {
  local pattern=$1
  local self_pid=$$
  local pids
  # pgrep -f matches full cmdline; exclude self and this script
  pids=$(pgrep -f "$pattern" 2>/dev/null | grep -v "^${self_pid}$" || true)
  if [ -n "$pids" ]; then
    echo -e "${YELLOW}Killing stale processes matching '${pattern}': ${pids}${NC}"
    echo "$pids" | xargs kill -9 2>/dev/null || true
    sleep 0.5
  fi
}

kill_stale() {
  echo -e "${YELLOW}── Killing stale instances ──${NC}"
  kill_by_port 8000
  kill_by_port 5173
  kill_by_port 7233
  # Only match processes started from THIS project directory
  local proj_root
  proj_root=$(pwd)
  kill_by_pattern "uvicorn api.main:app"
  kill_by_pattern "workers.main"
  kill_by_pattern "node.*vite.*${proj_root}"
  kill_by_pattern "npm.*run.*dev.*${proj_root}"
  # Kill any leftover PIDs from previous runs of this script
  for pidfile in "$PIDDIR"/*.pid; do
    [ -f "$pidfile" ] || continue
    local old_pid
    old_pid=$(cat "$pidfile")
    if kill -0 "$old_pid" 2>/dev/null; then
      echo -e "${YELLOW}Killing previous child PID ${old_pid}${NC}"
      kill -9 "$old_pid" 2>/dev/null || true
    fi
    rm -f "$pidfile"
  done
  echo -e "${GREEN}Clean.${NC}"
}

start_services() {
  echo -e "${GREEN}── Starting services ──${NC}"

  # Backend API
  cd backend
  PYTHONPATH=. PARQUET_BASE_PATH="${PARQUET_BASE_PATH:-$HOME/.trading-system/data/parquet}" \
    ../backend/.venv/bin/uvicorn api.main:app --reload --host 0.0.0.0 --port 8000 \
    > "../$LOGDIR/api.log" 2>&1 &
  echo $! > "../$PIDDIR/api.pid"
  cd ..

  # Worker
  cd backend
  PYTHONPATH=. PARQUET_BASE_PATH="${PARQUET_BASE_PATH:-$HOME/.trading-system/data/parquet}" \
    ../backend/.venv/bin/python -m workers.main \
    > "../$LOGDIR/worker.log" 2>&1 &
  echo $! > "../$PIDDIR/worker.pid"
  cd ..

  # Frontend
  cd frontend
  npm run dev \
    > "../$LOGDIR/frontend.log" 2>&1 &
  echo $! > "../$PIDDIR/frontend.pid"
  cd ..

  sleep 1

  echo ""
  echo -e "${GREEN}  API      → http://localhost:8000${NC}"
  echo -e "${GREEN}  Frontend → http://localhost:5173${NC}"
  echo -e "${GREEN}  Logs     → .logs/{api,worker,frontend}.log${NC}"
  echo ""
  echo -e "  Tail logs:  ${YELLOW}tail -f .logs/api.log${NC}"
  echo -e "  Stop all:   ${YELLOW}./restart.sh --kill${NC}"
  echo ""
}

# ── Main ─────────────────────────────────────────────────────────────────────
case "${1:-}" in
  --kill)
    kill_stale
    ;;
  --once)
    start_services
    ;;
  --status)
    echo -e "${GREEN}── Running instances ──${NC}"
    for name in api worker frontend; do
      local_pidfile="$PIDDIR/$name.pid"
      if [ -f "$local_pidfile" ] && kill -0 "$(cat "$local_pidfile")" 2>/dev/null; then
        echo -e "  ${GREEN}●${NC} $name (PID $(cat "$local_pidfile"))"
      else
        echo -e "  ${RED}○${NC} $name (not running)"
      fi
    done
    ;;
  *)
    kill_stale
    start_services
    ;;
esac
