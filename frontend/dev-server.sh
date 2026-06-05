#!/usr/bin/env bash
# Start Vite watch-mode build + preview server with API proxy.
# The watch process auto-rebuilds whenever source files change.
# Run with: ./dev-server.sh
# Stop with: ./dev-server.sh stop

set -e
cd "$(dirname "$0")"

PID_FILE=".dev-pids"

case "${1:-start}" in
  start)
    if [ -f "$PID_FILE" ]; then
      echo "⚠️  Dev server already running (PIDs in $PID_FILE). Stop first with: $0 stop"
      exit 1
    fi

    # Initial build
    echo "🔨 Building..."
    npx vite build 2>&1 | tail -1

    # Watch mode — auto-rebuilds on file changes
    echo "👀 Starting watch mode..."
    npx vite build --watch > /tmp/vite-watch.log 2>&1 &
    WATCH_PID=$!

    # Preview server (serves dist/ with /api proxy)
    echo "🌐 Starting preview server on :5180..."
    node preview-server.mjs > /tmp/preview-server.log 2>&1 &
    SERVE_PID=$!

    echo "$WATCH_PID $SERVE_PID" > "$PID_FILE"
    echo "✅ Ready — watch: $WATCH_PID, server: $SERVE_PID"
    echo "   Open http://localhost:5180"
    echo "   Stop with: $0 stop"

    # Cleanup on Ctrl+C
    trap 'kill $WATCH_PID $SERVE_PID 2>/dev/null; rm -f "$PID_FILE"; exit 0' INT TERM
    wait
    ;;

  stop)
    if [ ! -f "$PID_FILE" ]; then
      echo "No dev server running"
      exit 0
    fi
    read -r WP SP < "$PID_FILE"
    kill "$WP" "$SP" 2>/dev/null || true
    pkill -f "vite build --watch" 2>/dev/null || true
    pkill -f "preview-server.mjs" 2>/dev/null || true
    rm -f "$PID_FILE"
    echo "🛑 Stopped"
    ;;

  *)
    echo "Usage: $0 [start|stop]"
    exit 1
    ;;
esac
