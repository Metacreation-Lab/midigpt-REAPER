#!/usr/bin/env bash
# Update MIDI-GPT for REAPER to the latest version
# Usage: ./update.sh

set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="$REPO_DIR/.venv"

RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
BOLD='\033[1m'
NC='\033[0m'

info() { echo -e "${BLUE}[INFO]${NC} $*"; }
ok()   { echo -e "${GREEN}[OK]${NC} $*"; }
fail() { echo -e "${RED}[ERROR]${NC} $*"; exit 1; }

echo -e "${BOLD}"
echo "  +--------------------------------------+"
echo "  |   MIDI-GPT for REAPER  -- Update    |"
echo "  +--------------------------------------+"
echo -e "${NC}"

# ── Pull latest plugin code ──────────────────────────────────────
info "Pulling latest plugin code..."
git -C "$REPO_DIR" pull || fail "git pull failed. Check your internet connection."
ok "Plugin code up to date"

# ── Activate venv ────────────────────────────────────────────────
[ -f "$VENV_DIR/bin/activate" ] || fail "Virtual environment not found. Run install.sh first."
source "$VENV_DIR/bin/activate"

# ── Upgrade midigpt from PyPI ────────────────────────────────────
info "Upgrading midigpt backend..."
pip install --upgrade "midigpt[http,inference]" -q
ok "midigpt upgraded to $(python -c 'import importlib.metadata; print(importlib.metadata.version("midigpt"))')"

# ── Done ─────────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}${BOLD}Update complete.${NC}"
echo ""

if [ -t 0 ]; then
    read -rp "  Start the server now? [Y/n]: " _LAUNCH
    _LAUNCH="${_LAUNCH:-y}"
    if [[ "$_LAUNCH" =~ ^[Yy]$ ]]; then
        echo ""
        echo "    [1] Yellow     (default)"
        echo "    [2] Prism"
        echo "    [3] Expressive"
        echo ""
        read -rp "  Model [1/2/3, default=1]: " _M
        case "${_M:-1}" in
            2) _MODEL="prism_medium"      ;;
            3) _MODEL="expressive_medium" ;;
            *) _MODEL="yellow_medium"     ;;
        esac
        echo ""
        bash "$REPO_DIR/start_midigpt_server.sh" --pretrained "$_MODEL"
    fi
fi
