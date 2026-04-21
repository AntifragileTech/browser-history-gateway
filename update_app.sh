#!/usr/bin/env bash
# Created: 20:56 21-Apr-2026
# Build the latest code and replace /Applications/Browser History Gateway.app
# in one shot. Bundle identifier + install path are identical across builds,
# so macOS TCC (Full Disk Access) almost always preserves the existing grant.
#
# Usage:
#   ./update_app.sh              # quick build, replace, relaunch
#   ./update_app.sh --clean      # wipe build/ and dist/ first
#   ./update_app.sh --no-launch  # don't relaunch afterwards
set -euo pipefail

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

CLEAN=0
LAUNCH=1
while [[ $# -gt 0 ]]; do
    case "$1" in
        --clean)     CLEAN=1; shift ;;
        --no-launch) LAUNCH=0; shift ;;
        *) echo "unknown flag: $1" >&2; exit 2 ;;
    esac
done

APP_NAME="Browser History Gateway"
SRC="$SCRIPT_DIR/dist/${APP_NAME}.app"
DST="/Applications/${APP_NAME}.app"

# ---- 1. Stop running instance so we can overwrite it ----
if pgrep -f "/Applications/${APP_NAME}.app/Contents/MacOS/" >/dev/null 2>&1; then
    echo "==> Stopping running app"
    osascript -e "tell application \"${APP_NAME}\" to quit" 2>/dev/null || true
    pkill -f "/Applications/${APP_NAME}.app/Contents/MacOS/" 2>/dev/null || true
    # Wait for it to exit so the Finder can replace the bundle.
    for _ in 1 2 3 4 5 6 7 8 9 10; do
        if ! pgrep -f "/Applications/${APP_NAME}.app/Contents/MacOS/" >/dev/null 2>&1; then
            break
        fi
        sleep 0.5
    done
fi

# ---- 2. Build fresh ----
echo "==> Building .app"
BUILD_CMD=(./build_app.sh)
[[ $CLEAN -eq 1 ]] && BUILD_CMD+=(--clean)
"${BUILD_CMD[@]}" >/tmp/update-build.log 2>&1 || {
    echo "build failed. Last 30 log lines:"; tail -30 /tmp/update-build.log
    exit 1
}
echo "    built $SRC ($(du -sh "$SRC" | awk '{print $1}'))"

# ---- 3. Replace in /Applications ----
if [[ -d "$DST" ]]; then
    echo "==> Removing old $DST"
    rm -rf "$DST"
fi
echo "==> Copying new bundle to /Applications"
cp -R "$SRC" "$DST"

# Clear the quarantine xattr that macOS adds to cp'd bundles — otherwise
# Gatekeeper will re-prompt the "cannot be opened" dialog on next launch.
xattr -dr com.apple.quarantine "$DST" 2>/dev/null || true

# ---- 4. Launch ----
if [[ $LAUNCH -eq 1 ]]; then
    echo "==> Relaunching"
    open "$DST"
fi

cat <<EOF

================================================================
  Update complete.

  New bundle:  $DST

  TCC / Full Disk Access:
    Bundle id and install path are unchanged, so the existing FDA
    grant typically survives. If Safari collection suddenly stops
    working after an update, re-toggle "Browser History Gateway"
    in System Settings → Privacy & Security → Full Disk Access,
    then Quit + relaunch from the menu bar.

  Menu bar: the ⏱ icon should be visible within ~2 seconds.
================================================================
EOF
