#!/usr/bin/env bash
# One-line installer for MIDI-GPT for REAPER
# Usage: curl -fsSL https://raw.githubusercontent.com/Metacreation-Lab/midigpt-REAPER/main/bootstrap.sh | bash

set -euo pipefail

REPO_URL="https://github.com/Metacreation-Lab/midigpt-REAPER.git"
INSTALL_DIR="${MIDIGPT_DIR:-$HOME/midigpt-REAPER}"

RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
BOLD='\033[1m'
NC='\033[0m'

echo -e "${BOLD}"
echo "  +======================================+"
echo "  |     MIDI-GPT for REAPER Installer   |"
echo "  +======================================+"
echo -e "${NC}"
echo "  Installing to: $INSTALL_DIR"
echo ""

# Require git
if ! command -v git &>/dev/null; then
    echo -e "${RED}[ERROR]${NC} git is required but not found."
    echo ""
    echo "  macOS:  brew install git"
    echo "  Linux:  sudo apt install git"
    exit 1
fi

# Clone or update
if [ -d "$INSTALL_DIR/.git" ]; then
    echo -e "${BLUE}[INFO]${NC} Updating existing installation..."
    git -C "$INSTALL_DIR" pull --quiet
else
    echo -e "${BLUE}[INFO]${NC} Cloning repository..."
    git clone --quiet "$REPO_URL" "$INSTALL_DIR"
fi
echo -e "${GREEN}[OK]${NC} Repository ready at $INSTALL_DIR"
echo ""

# Hand off to the full installer. When piped from curl, stdin is the pipe
# (not the terminal). Redirect from /dev/tty so interactive prompts work.
if [ -t 0 ]; then
    exec bash "$INSTALL_DIR/install.sh" "$@"
else
    exec bash "$INSTALL_DIR/install.sh" "$@" < /dev/tty
fi
