#!/bin/sh
# Installs (or updates) the OIL relay on this Mac: it starts at every login
# and keeps running. See README.md in this folder for the rest of the setup.
#
#   sh packaging/relay/install.sh                      the relay only
#   sh packaging/relay/install.sh NAME TOKEN           + keep NAME.duckdns.org pointing here
#   sh packaging/relay/install.sh --remove             stop it and take it out again
set -e

HERE="$(cd "$(dirname "$0")" && pwd)"
DIR="$HOME/Library/Application Support/OIL-relay"
AGENTS="$HOME/Library/LaunchAgents"
LOG="$HOME/Library/Logs/oil-relay.log"
PORT=47800

unload() {
    launchctl unload "$AGENTS/$1.plist" 2>/dev/null || true
}

if [ "$1" = "--remove" ]; then
    unload nl.oil.relay
    unload nl.oil.duckdns
    rm -f "$AGENTS/nl.oil.relay.plist" "$AGENTS/nl.oil.duckdns.plist"
    echo "The OIL relay is stopped and removed ($DIR is left in place)."
    exit 0
fi

PYTHON="$(command -v python3)"
if [ -z "$PYTHON" ]; then
    echo "No python3 found: install Python 3 first (python.org)." >&2
    exit 1
fi

# A copy outside Documents: macOS doesn't let programs started at login read
# Documents without asking.
mkdir -p "$DIR" "$AGENTS" "$(dirname "$LOG")"
cp "$HERE/../../relay.py" "$DIR/relay.py"

unload nl.oil.relay
sed -e "s|@PYTHON@|$PYTHON|g" -e "s|@DIR@|$DIR|g" -e "s|@PORT@|$PORT|g" -e "s|@LOG@|$LOG|g" \
    "$HERE/nl.oil.relay.plist" > "$AGENTS/nl.oil.relay.plist"
launchctl load -w "$AGENTS/nl.oil.relay.plist"
echo "The OIL relay runs now (and at every login) on port $PORT, with $PYTHON."
echo "Its log: $LOG"

if [ -n "$1" ] && [ -n "$2" ]; then
    # Every 5 minutes: tell DuckDNS this home's current address.
    unload nl.oil.duckdns
    cat > "$AGENTS/nl.oil.duckdns.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>nl.oil.duckdns</string>
    <key>ProgramArguments</key>
    <array>
        <string>/usr/bin/curl</string>
        <string>-s</string>
        <string>-o</string>
        <string>/dev/null</string>
        <string>https://www.duckdns.org/update?domains=$1&amp;token=$2&amp;ip=</string>
    </array>
    <key>StartInterval</key>
    <integer>300</integer>
    <key>RunAtLoad</key>
    <true/>
</dict>
</plist>
EOF
    chmod 600 "$AGENTS/nl.oil.duckdns.plist"  # it holds the token
    launchctl load -w "$AGENTS/nl.oil.duckdns.plist"
    echo "$1.duckdns.org is kept pointing at this home's address."
fi
