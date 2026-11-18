#!/bin/bash
# ContentOS.app launcher — runs inside the .app bundle.
# Starts the local server if needed, then opens the UI in a Chrome app window
# (no tabs / address bar) so it feels like a native standalone app.

set -u
BUNDLE_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PROJECT_PATH="$(cat "$BUNDLE_ROOT/Resources/project.path" 2>/dev/null)"
LOG_DIR="$HOME/Library/Logs/ContentOS"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/launcher.log"
URL="http://127.0.0.1:8765"

log() { printf '%s %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" >> "$LOG_FILE"; }

if [ -z "$PROJECT_PATH" ] || [ ! -f "$PROJECT_PATH/app/server.py" ]; then
  osascript -e 'display alert "ContentOS" message "Project folder not found. Rebuild the app with scripts/make_macos_app.sh."' >/dev/null 2>&1
  log "ERROR: project path missing or invalid: $PROJECT_PATH"
  exit 1
fi

# Find a Python 3 interpreter: launchd gives a minimal PATH, so check known
# Homebrew/system locations before falling back to whatever is on PATH.
PY=""
for candidate in /opt/homebrew/bin/python3 /usr/local/bin/python3 /usr/bin/python3; do
  if [ -x "$candidate" ]; then PY="$candidate"; break; fi
done
if [ -z "$PY" ]; then PY="$(command -v python3 2>/dev/null || true)"; fi
if [ -z "$PY" ]; then
  osascript -e 'display alert "ContentOS" message "Python 3 was not found on this Mac."' >/dev/null 2>&1
  log "ERROR: python3 not found"
  exit 1
fi

# If the server is not responding, start it via a LaunchAgent so it survives
# this launcher exiting. Plain nohup/& inherits the app's process group and is
# killed by launchd; `launchctl submit` ties the job to the submitting process.
if ! curl -fsS --max-time 2 "$URL/api/status" >/dev/null 2>&1; then
  log "Installing LaunchAgent for server"
  PLIST_DIR="$HOME/Library/LaunchAgents"
  PLIST="$PLIST_DIR/com.justmemedia.contentos.plist"
  mkdir -p "$PLIST_DIR"
  cat > "$PLIST" <<PLISTEOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.justmemedia.contentos</string>
  <key>ProgramArguments</key>
  <array>
    <string>$PY</string>
    <string>$PROJECT_PATH/app/server.py</string>
  </array>
  <key>WorkingDirectory</key><string>$PROJECT_PATH</string>
  <key>StandardOutPath</key><string>$LOG_DIR/server.stdout.log</string>
  <key>StandardErrorPath</key><string>$LOG_DIR/server.stderr.log</string>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><false/>
</dict>
</plist>
PLISTEOF
  launchctl unload "$PLIST" >/dev/null 2>&1 || true
  launchctl load -w "$PLIST" >> "$LOG_FILE" 2>&1 || log "WARN: launchctl load returned non-zero"
  ready=0
  for _ in $(seq 1 60); do
    if curl -fsS --max-time 1 "$URL/api/status" >/dev/null 2>&1; then ready=1; break; fi
    sleep 0.25
  done
  if [ "$ready" -ne 1 ]; then
    osascript -e 'display alert "ContentOS" message "Server did not start. Check ~/Library/Logs/ContentOS/launcher.log and server.stderr.log"' >/dev/null 2>&1
    log "ERROR: server failed to become ready"
    exit 1
  fi
  log "Server ready"
else
  log "Server already running"
fi

# Prefer a Chrome "app mode" window; fall back to the default browser.
CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
if [ -x "$CHROME" ]; then
  open -na "Google Chrome" --args --app="$URL" --user-data-dir="$HOME/Library/Application Support/ContentOS/chrome-app-profile"
else
  open "$URL"
fi
log "Opened UI at $URL"
exit 0
