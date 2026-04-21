#!/usr/bin/env bash
# Created: 20:31 21-Apr-2026
# One-command bootstrap for a fresh Mac.
#
# Usage:
#   ./install.sh                    # venv, deps, init DB, one collection pass
#   ./install.sh --agent            # also install & load the launchd agent
#   ./install.sh --agent --interval 300   # agent running every 5 min
#   ./install.sh --uninstall-agent  # stop and remove the launchd agent
set -euo pipefail

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

AGENT=0
UNINSTALL=0
INTERVAL=600

while [[ $# -gt 0 ]]; do
    case "$1" in
        --agent)            AGENT=1; shift ;;
        --uninstall-agent)  UNINSTALL=1; shift ;;
        --interval)         INTERVAL="$2"; shift 2 ;;
        -h|--help)
            grep '^#' "$0" | head -15 | sed 's/^# //' | sed 's/^#//'
            exit 0 ;;
        *) echo "unknown flag: $1" >&2; exit 2 ;;
    esac
done

PLIST_LABEL="com.user.browserhistory"
PLIST_DST="$HOME/Library/LaunchAgents/${PLIST_LABEL}.plist"
PLIST_TEMPLATE="$SCRIPT_DIR/launchd/${PLIST_LABEL}.plist.template"

if [[ $UNINSTALL -eq 1 ]]; then
    echo "==> Unloading launchd agent"
    launchctl unload "$PLIST_DST" 2>/dev/null || true
    rm -f "$PLIST_DST"
    echo "    removed $PLIST_DST"
    exit 0
fi

# ----- 1. Python + venv -----
if ! command -v python3 >/dev/null 2>&1; then
    echo "error: python3 not found. Install via 'brew install python' or Xcode CLT." >&2
    exit 1
fi
PY_VERSION=$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])')
echo "==> Python $PY_VERSION"

if [[ ! -d .venv ]]; then
    echo "==> Creating virtual env in .venv/"
    python3 -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate
pip install --quiet --upgrade pip
echo "==> Installing dependencies"
pip install --quiet -r requirements.txt

# ----- 2. Initialize central DB -----
echo "==> Initializing ~/.browser-history/history.db (safe if it already exists)"
python3 -m collector.run --init

# ----- 3. First collection pass -----
echo "==> Running first collection pass"
python3 -m collector.run

# ----- 4. Optional: launchd agent -----
if [[ $AGENT -eq 1 ]]; then
    echo "==> Installing launchd agent (interval ${INTERVAL}s)"
    VENV_PY="$SCRIPT_DIR/.venv/bin/python3"
    mkdir -p "$HOME/Library/LaunchAgents"

    # Substitute placeholders -> real paths
    sed \
        -e "s|__PROJECT_DIR__|$SCRIPT_DIR|g" \
        -e "s|__VENV_PYTHON__|$VENV_PY|g" \
        -e "s|__HOME__|$HOME|g" \
        -e "s|__INTERVAL__|$INTERVAL|g" \
        "$PLIST_TEMPLATE" > "$PLIST_DST"

    launchctl unload "$PLIST_DST" 2>/dev/null || true
    launchctl load "$PLIST_DST"
    echo "    loaded $PLIST_DST"
    echo "    check status: launchctl list | grep browserhistory"
fi

cat <<EOF

==============================================================
  Browser History Gateway — install complete.

  DB:       ~/.browser-history/history.db
  Logs:     ~/.browser-history/collector.log
  UI:       cd "$SCRIPT_DIR" && .venv/bin/python -m web.app
            then open http://127.0.0.1:8765

  Next steps:
   1. Grant Full Disk Access to your terminal (+ Claude.app if
      you launch the collector from there) so Safari is visible.
      System Settings -> Privacy & Security -> Full Disk Access
$([[ $AGENT -eq 1 ]] && echo "   2. Agent is running — collection every ${INTERVAL}s." \
                     || echo "   2. To enable background collection: ./install.sh --agent")
==============================================================
EOF
