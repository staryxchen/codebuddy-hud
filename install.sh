#!/usr/bin/env bash
# codebuddy-hud installer
# Usage:  bash install.sh
#   or:   curl -fsSL <raw-url>/install.sh | bash
set -e

CYAN='\033[0;36m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
RESET='\033[0m'

info()    { printf "${CYAN}[hud]${RESET} %s\n" "$*"; }
ok()      { printf "${GREEN}[hud]${RESET} %s\n" "$*"; }
warn()    { printf "${YELLOW}[hud]${RESET} %s\n" "$*"; }
die()     { printf "${RED}[hud] error:${RESET} %s\n" "$*" >&2; exit 1; }

# ── 1. Locate hud.py ─────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HUD_PY="$SCRIPT_DIR/hud.py"
[ -f "$HUD_PY" ] || die "hud.py not found in $SCRIPT_DIR"

# ── 2. Find a suitable Python (≥ 3.7) ────────────────────────────────────────
PYTHON=""
for candidate in python3.12 python3.11 python3.10 python3.9 python3.8 python3.7 python3; do
    if command -v "$candidate" &>/dev/null; then
        ver=$("$candidate" -c "import sys; print(sys.version_info[:2])" 2>/dev/null)
        # ver looks like "(3, 11)" — extract minor version
        minor=$(echo "$ver" | tr -d '(),' | awk '{print $2}')
        if [ -n "$minor" ] && [ "$minor" -ge 7 ] 2>/dev/null; then
            PYTHON="$candidate"
            break
        fi
    fi
done
[ -n "$PYTHON" ] || die "Python 3.7+ not found. Please install Python 3.7 or newer."
info "Using $(command -v $PYTHON)  ($($PYTHON --version 2>&1))"

# ── 3. Create ~/.codebuddy if needed ─────────────────────────────────────────
CODEBUDDY_DIR="$HOME/.codebuddy"
mkdir -p "$CODEBUDDY_DIR"

# ── 4. Symlink hud.py ────────────────────────────────────────────────────────
LINK="$CODEBUDDY_DIR/hud.py"
if [ -L "$LINK" ] && [ "$(readlink "$LINK")" = "$HUD_PY" ]; then
    info "Symlink already up to date: $LINK -> $HUD_PY"
else
    ln -sf "$HUD_PY" "$LINK"
    ok "Symlinked: $LINK -> $HUD_PY"
fi

# ── 5. Merge statusLine into settings.json ───────────────────────────────────
SETTINGS="$CODEBUDDY_DIR/settings.json"

$PYTHON - "$SETTINGS" "$PYTHON" "$LINK" <<'PYEOF'
import json, sys, os

settings_path = sys.argv[1]
python_bin    = sys.argv[2]
hud_path      = sys.argv[3]

# Load existing settings (or start empty)
if os.path.exists(settings_path):
    with open(settings_path) as f:
        try:
            cfg = json.load(f)
        except Exception:
            cfg = {}
else:
    cfg = {}

new_status_line = {
    "type": "command",
    "command": f"{python_bin} {hud_path}",
    "padding": 0
}

existing = cfg.get("statusLine")
if existing == new_status_line:
    print("[hud] statusLine already configured, no changes needed.")
    sys.exit(0)

if existing and existing != new_status_line:
    print(f"[hud] Replacing existing statusLine: {json.dumps(existing)}")

cfg["statusLine"] = new_status_line

with open(settings_path, "w") as f:
    json.dump(cfg, f, indent=2)
    f.write("\n")

print(f"[hud] Updated {settings_path}")
PYEOF

# ── 6. Done ───────────────────────────────────────────────────────────────────
echo ""
ok "Installation complete!"
echo ""
echo "  Restart CodeBuddy Code to activate the HUD."
echo ""
echo "  The status line will show:"
echo "    [Model] │ folder  git:(branch*)"
echo "    Context ████░░░░░░ 41.8%"
echo "    ◐ Read: src/index.ts   (when tools are running)"
echo ""
