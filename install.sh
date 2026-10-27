#!/usr/bin/env bash
# Installs the claude-usage helper and the Claude Usage plasmoid for the current user.
# Usage: install.sh [--plasma 5|6]   (default: detected from plasmashell --version)
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLUGIN_ID="com.github.madzik890.claudeusage"

PLASMA=""
while [ $# -gt 0 ]; do
    case "$1" in
        --plasma) PLASMA="${2:-}"; shift 2 ;;
        --plasma=*) PLASMA="${1#*=}"; shift ;;
        *) echo "Unknown option: $1" >&2; exit 2 ;;
    esac
done

if [ -z "$PLASMA" ]; then
    PLASMA="$(plasmashell --version 2>/dev/null | sed -n 's/^plasmashell \([0-9]\+\)\..*/\1/p')"
fi
case "$PLASMA" in
    5|6) ;;
    *) echo "Cannot detect the Plasma version; pass --plasma 5 or --plasma 6" >&2; exit 1 ;;
esac
KPACKAGETOOL="kpackagetool$PLASMA"

install -D -m 0755 "$HERE/helper/claude_usage.py" "$HOME/.local/bin/claude-usage"
echo "Helper: $HOME/.local/bin/claude-usage"

# The package is assembled from the shared files plus the Plasma-specific variant.
PACKAGE="$(mktemp -d)"
trap 'rm -rf "$PACKAGE"' EXIT
cp -r "$HERE/plasmoid/common/." "$PACKAGE/"
cp -r "$HERE/plasmoid/plasma$PLASMA/." "$PACKAGE/"

if "$KPACKAGETOOL" --type Plasma/Applet --list 2>/dev/null | grep -q "^$PLUGIN_ID\$"; then
    "$KPACKAGETOOL" --type Plasma/Applet --upgrade "$PACKAGE"
else
    "$KPACKAGETOOL" --type Plasma/Applet --install "$PACKAGE"
fi

cat <<EOF

Installed plasmoid $PLUGIN_ID (Plasma $PLASMA).
- Preview in a window:  plasmawindowed $PLUGIN_ID
- Add to panel:         right-click the panel → Add Widgets… → "Claude Usage"
- After updating a widget already on the panel: plasmashell --replace &
EOF
