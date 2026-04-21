#!/usr/bin/env bash
# Created: 20:40 21-Apr-2026
# Build the Browser History Gateway macOS .app (+ optional DMG).
#
# Usage:
#   ./build_app.sh            # builds dist/Browser History Gateway.app
#   ./build_app.sh --dmg      # also packages a drag-to-Applications DMG
#   ./build_app.sh --clean    # wipe build/ and dist/ first
set -euo pipefail

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

DO_DMG=0
DO_CLEAN=0
while [[ $# -gt 0 ]]; do
    case "$1" in
        --dmg)   DO_DMG=1; shift ;;
        --clean) DO_CLEAN=1; shift ;;
        *) echo "unknown flag: $1" >&2; exit 2 ;;
    esac
done

APP_NAME="Browser History Gateway"
APP_BUNDLE="dist/${APP_NAME}.app"
DMG_PATH="dist/${APP_NAME}.dmg"

# ---- 1. Build venv ----
if [[ ! -d .venv-build ]]; then
    echo "==> Creating .venv-build/"
    python3 -m venv .venv-build
fi
# shellcheck disable=SC1091
source .venv-build/bin/activate
pip install --quiet --upgrade pip
echo "==> Installing build deps (py2app, rumps, pyobjc, runtime deps)"
pip install --quiet -r requirements-build.txt

# ---- 2. Clean ----
if [[ $DO_CLEAN -eq 1 ]]; then
    echo "==> Wiping build/ and dist/"
    rm -rf build dist
fi

# ---- 3. Build .app ----
echo "==> Running py2app (this takes 30–90 s)"
python3 setup_app.py py2app >/tmp/py2app-build.log 2>&1 || {
    echo "py2app failed. Last 40 log lines:"; tail -40 /tmp/py2app-build.log
    exit 1
}

if [[ ! -d "$APP_BUNDLE" ]]; then
    echo "build reported success but $APP_BUNDLE is missing" >&2
    exit 1
fi

BUNDLE_SIZE=$(du -sh "$APP_BUNDLE" | awk '{print $1}')
echo "    $APP_BUNDLE  ($BUNDLE_SIZE)"

# ---- 3b. Ad-hoc code sign ----
# Sign with the "-" identity (no Apple Developer certificate required).
# Ad-hoc signing gives the bundle a stable-enough identity that macOS TCC
# (Full Disk Access, etc.) is more likely to preserve grants across
# rebuilds than with a fully-unsigned bundle. It does NOT eliminate the
# Gatekeeper "unidentified developer" prompt on first launch.
echo "==> Ad-hoc code-signing bundle"
codesign --force --deep --sign - \
    --identifier com.user.browserhistorygateway \
    "$APP_BUNDLE" >/dev/null 2>&1 || echo "    (codesign warning, continuing)"

# ---- 4. DMG ----
if [[ $DO_DMG -eq 1 ]]; then
    echo "==> Creating DMG"
    rm -f "$DMG_PATH"
    STAGE=$(mktemp -d)
    cp -R "$APP_BUNDLE" "$STAGE/"
    ln -s /Applications "$STAGE/Applications"
    hdiutil create -volname "$APP_NAME" \
        -srcfolder "$STAGE" \
        -ov -format UDZO "$DMG_PATH" >/dev/null
    rm -rf "$STAGE"
    DMG_SIZE=$(du -sh "$DMG_PATH" | awk '{print $1}')
    echo "    $DMG_PATH  ($DMG_SIZE)"
fi

cat <<EOF

================================================================
  Build complete.

  App:   $APP_BUNDLE
$([[ $DO_DMG -eq 1 ]] && echo "  DMG:   $DMG_PATH")

  To run locally:
      open "$APP_BUNDLE"

  To distribute (UNSIGNED — first-launch note below):
      1. Drag the .app (or .dmg) to the target Mac.
      2. Right-click → Open, click Open in the Gatekeeper warning.
         (Only needed once per Mac, because it's not code-signed.)
      3. App will prompt for Full Disk Access — grant it, fully quit,
         and relaunch. Collection starts automatically every 10 min.

  Icon shows in the top menu-bar. Click 🕸 for Open Search / Run Now.
================================================================
EOF
