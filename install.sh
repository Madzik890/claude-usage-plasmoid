#!/usr/bin/env bash
# Installs the claude-usage helper and the Claude Usage plasmoid for the current user.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLUGIN_ID="com.github.madzik890.claudeusage"

install -D -m 0755 "$HERE/helper/claude_usage.py" "$HOME/.local/bin/claude-usage"
echo "Helper: $HOME/.local/bin/claude-usage"

if kpackagetool5 --type Plasma/Applet --list 2>/dev/null | grep -q "^$PLUGIN_ID\$"; then
    kpackagetool5 --type Plasma/Applet --upgrade "$HERE/plasmoid"
else
    kpackagetool5 --type Plasma/Applet --install "$HERE/plasmoid"
fi

cat <<EOF

Installed plasmoid $PLUGIN_ID.
- Preview in a window:  plasmawindowed $PLUGIN_ID
- Add to panel:         right-click the panel → Add Widgets… → "Claude Usage"
- After updating a widget already on the panel: plasmashell --replace &
EOF
