#!/usr/bin/env bash
# Uninstall MIDI-GPT for REAPER
# Usage: ./uninstall.sh

set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
BOLD='\033[1m'
NC='\033[0m'

info() { echo -e "${BLUE}[INFO]${NC} $*"; }
ok()   { echo -e "${GREEN}[OK]${NC} $*"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $*"; }

echo -e "${BOLD}"
echo "  +--------------------------------------+"
echo "  |  MIDI-GPT for REAPER  -- Uninstall  |"
echo "  +--------------------------------------+"
echo -e "${NC}"

# ── Locate REAPER config dir ─────────────────────────────────────
OS="$(uname -s)"
case "$OS" in
    Darwin)       REAPER_DIR="$HOME/Library/Application Support/REAPER" ;;
    Linux)        REAPER_DIR="$HOME/.config/REAPER" ;;
    MINGW*|MSYS*) REAPER_DIR="$APPDATA/REAPER" ;;
    *)            REAPER_DIR="" ;;
esac

# ── Remove REAPER symlinks ───────────────────────────────────────
REMOVED_LINKS=0
if [ -n "$REAPER_DIR" ] && [ -d "$REAPER_DIR" ]; then
    for path in \
        "$REAPER_DIR/Scripts/MIDI-GPT" \
        "$REAPER_DIR/Effects/MIDI-GPT"
    do
        if [ -L "$path" ]; then
            rm "$path"
            ok "Removed symlink: $path"
            REMOVED_LINKS=$((REMOVED_LINKS + 1))
        elif [ -d "$path" ]; then
            warn "Found non-symlink directory at $path — skipping (remove manually if needed)"
        fi
    done
else
    warn "REAPER config directory not found — no symlinks to remove"
fi

# ── Optionally delete the install directory ──────────────────────
echo ""
echo "  The plugin files are at: $REPO_DIR"
echo ""
read -rp "  Delete the plugin folder and virtual environment? [y/N]: " _DEL
_DEL="${_DEL:-n}"

if [[ "$_DEL" =~ ^[Yy]$ ]]; then
    echo ""
    warn "This will permanently delete: $REPO_DIR"
    read -rp "  Are you sure? Type 'yes' to confirm: " _CONFIRM
    if [ "$_CONFIRM" = "yes" ]; then
        rm -rf "$REPO_DIR"
        ok "Deleted $REPO_DIR"
    else
        info "Skipped — folder not deleted"
    fi
else
    info "Folder kept at $REPO_DIR"
fi

echo ""
echo -e "${GREEN}${BOLD}Uninstall complete.${NC}"
if [ $REMOVED_LINKS -gt 0 ]; then
    echo "  REAPER scripts and effects have been removed."
    echo "  Restart REAPER to clear any cached references."
fi
echo ""
