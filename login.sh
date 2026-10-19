#!/bin/zsh
# Start Monday automatically when you log in (like Siri), or stop doing that.
#   ./login.sh install     start at login (and now)
#   ./login.sh uninstall   stop starting at login
#   ./login.sh status      is it running?
# Logs: ~/.monday/monday.log
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
LABEL="com.monday.assistant"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"

case "$1" in
  install)
    mkdir -p "$HOME/Library/LaunchAgents" "$HOME/.monday"
    cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array><string>$DIR/.venv/bin/python</string><string>$DIR/main.py</string></array>
  <key>WorkingDirectory</key><string>$DIR</string>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><dict><key>SuccessfulExit</key><false/></dict>
  <key>ProcessType</key><string>Interactive</string>
  <key>StandardOutPath</key><string>$HOME/.monday/monday.log</string>
  <key>StandardErrorPath</key><string>$HOME/.monday/monday.log</string>
</dict>
</plist>
EOF
    launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
    launchctl bootstrap "gui/$(id -u)" "$PLIST"
    echo "Monday will now start at login (and is starting now)."
    echo "First run: macOS asks to allow Microphone, Accessibility, Screen Recording and Camera for \"Python\". Allow them."
    ;;
  uninstall)
    launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
    rm -f "$PLIST"
    echo "Monday no longer starts at login."
    ;;
  status)
    launchctl print "gui/$(id -u)/$LABEL" 2>/dev/null | grep -E "state|pid" || echo "Not installed."
    ;;
  *)
    echo "usage: ./login.sh install | uninstall | status"
    ;;
esac
