#!/usr/bin/env bash
# Launch Chrome with remote debugging enabled for Playwright CDP connection.
# Usage: ./scripts/launch-chrome.sh

set -euo pipefail

CDP_PORT="${CDP_PORT:-9222}"
CHROME_BIN=""

# Find Chrome binary
for candidate in \
  "google-chrome" \
  "google-chrome-stable" \
  "chromium-browser" \
  "chromium" \
  "/usr/bin/google-chrome" \
  "/usr/bin/google-chrome-stable" \
  "/usr/bin/chromium-browser" \
  "/snap/bin/chromium" \
  "/opt/google/chrome/google-chrome" \
  ; do
  if command -v "$candidate" &>/dev/null || [ -x "$candidate" ]; then
    CHROME_BIN="$candidate"
    break
  fi
done

if [ -z "$CHROME_BIN" ]; then
  echo "Error: Chrome/Chromium not found. Install Google Chrome or set CHROME_BIN."
  exit 1
fi

echo "Starting Chrome with remote debugging on port $CDP_PORT..."
echo "Binary: $CHROME_BIN"

exec "$CHROME_BIN" \
  --remote-debugging-port="$CDP_PORT" \
  --user-data-dir="${CHROME_USER_DATA:-}" \
  "$@"
