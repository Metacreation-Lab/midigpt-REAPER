#!/usr/bin/env bash
# ============================================================================
# MIDI-GPT for REAPER — One-Click Installer
#
# Installs everything needed to run MIDI-GPT in REAPER:
#   1. System dependencies (git, python)
#   2. Python virtual environment + torch
#   3. MIDI-GPT backend library
#   4. REAPER symlinks (Scripts + Effects)
#   5. Verification of installation
#
# Usage:
#   ./install.sh              # Full install
#   ./install.sh --skip-deps  # Skip system dependency check (if already installed)
#   ./install.sh --help       # Show help
# ============================================================================

set -euo pipefail

# ── Config ──────────────────────────────────────────────────────
REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="$REPO_DIR/.venv"
PYTHON_MIN_VERSION="3.10"
SKIP_DEPS=false
SKIP_REAPER_CONFIG=false

# Target MIDI-GPT source repo path. Auto-detected at the sibling path ../MIDI-GPT.
MIDIGPT_SRC=""

# ── Colors ──────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
BOLD='\033[1m'
NC='\033[0m'  # No Color

# ── Helpers ─────────────────────────────────────────────────────

info()  { echo -e "${BLUE}[INFO]${NC} $*"; }
ok()    { echo -e "${GREEN}[OK]${NC} $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $*"; }
fail()  { echo -e "${RED}[ERROR]${NC} $*"; exit 1; }

step() {
    echo ""
    echo -e "${BOLD}────────────────────────────────────────────────────${NC}"
    echo -e "${BOLD}  $*${NC}"
    echo -e "${BOLD}────────────────────────────────────────────────────${NC}"
}

check_cmd() {
    command -v "$1" &>/dev/null
}

# ── Args ────────────────────────────────────────────────────────

for arg in "$@"; do
    case "$arg" in
        --skip-deps) SKIP_DEPS=true ;;
        --skip-reaper-config) SKIP_REAPER_CONFIG=true ;;
        --midigpt-src=*)
            MIDIGPT_SRC="${arg#*=}"
            ;;
        --help|-h)
            echo "MIDI-GPT for REAPER — Installer"
            echo ""
            echo "Usage: ./install.sh [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --skip-deps          Skip system dependency check"
            echo "  --skip-reaper-config Skip automatic REAPER Python/ReaScript configuration"
            echo "  --midigpt-src=PATH   Path to the MIDI-GPT source repository (sibling folder by default)"
            echo "  --help               Show this help"
            echo ""
            echo "Examples:"
            echo "  ./install.sh                                   # Full installation"
            echo "  ./install.sh --midigpt-src=/custom/path        # Custom MIDI-GPT source path"
            exit 0
            ;;
        *) warn "Unknown option: $arg" ;;
    esac
done

# ── Banner ──────────────────────────────────────────────────────

echo -e "${BOLD}"
echo "  ╔══════════════════════════════════════╗"
echo "  ║     MIDI-GPT for REAPER Installer    ║"
echo "  ╚══════════════════════════════════════╝"
echo -e "${NC}"

# ── Detect OS ───────────────────────────────────────────────────

OS="$(uname -s)"
case "$OS" in
    Darwin)       PLATFORM="macos" ;;
    Linux)        PLATFORM="linux" ;;
    MINGW*|MSYS*) PLATFORM="windows" ;;
    *)            fail "Unsupported OS: $OS. On Windows, use install.ps1 instead." ;;
esac
info "Platform: $PLATFORM ($OS)"

# ====================================================================
# Step 1: System Dependencies
# ====================================================================

if [ "$SKIP_DEPS" = false ]; then
    step "Step 1/6: Checking system dependencies"

    MISSING=()

    # -- Python --
    if [ -n "${PYTHON_CMD:-}" ] && [ -f "$PYTHON_CMD" ]; then
        PY_VER="$($PYTHON_CMD -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
        ok "Python $PY_VER ($PYTHON_CMD) [override]"
    else
        PYTHON_CMD=""
        for cmd in python3.12 python3.11 python3.10 python3; do
            if check_cmd "$cmd"; then
                PY_VER="$($cmd -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
                PY_MAJOR="$($cmd -c 'import sys; print(sys.version_info.major)')"
                PY_MINOR="$($cmd -c 'import sys; print(sys.version_info.minor)')"
                if [ "$PY_MAJOR" -ge 3 ] && [ "$PY_MINOR" -ge 10 ]; then
                    PYTHON_CMD="$cmd"
                    break
                fi
            fi
        done

        if [ -z "$PYTHON_CMD" ]; then
            MISSING+=("python>=3.10")
            warn "Python >= $PYTHON_MIN_VERSION not found"
        else
            ok "Python $PY_VER ($PYTHON_CMD)"
        fi
    fi

    # -- git --
    if check_cmd git; then
        ok "git $(git --version | awk '{print $3}')"
    else
        MISSING+=("git")
        warn "git not found"
    fi

    # -- Install missing deps --
    if [ ${#MISSING[@]} -gt 0 ]; then
        echo ""
        warn "Missing dependencies: ${MISSING[*]}"
        echo ""

        if [ "$PLATFORM" = "macos" ]; then
            if check_cmd brew; then
                info "Installing via Homebrew..."
                brew install git || fail "Homebrew install failed"
            else
                echo ""
                echo "Please install Homebrew first:"
                echo '  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"'
                echo ""
                echo "Then re-run this installer."
                fail "Homebrew not found"
            fi
        elif [ "$PLATFORM" = "linux" ]; then
            echo ""
            echo "Please install git manually."
            echo ""
            fail "Please install git and re-run"
        fi
    fi

    [ -z "$PYTHON_CMD" ] && fail "Python >= $PYTHON_MIN_VERSION required but not found"
    ok "All system dependencies satisfied"

else
    step "Step 1/6: Skipping dependency check (--skip-deps)"
    # Find python anyway
    if [ -n "${PYTHON_CMD:-}" ] && [ -f "$PYTHON_CMD" ]; then
        info "Using custom Python $PYTHON_CMD [override]"
    else
        PYTHON_CMD=""
        for cmd in python3.12 python3.11 python3.10 python3; do
            if check_cmd "$cmd"; then
                PY_MINOR="$($cmd -c 'import sys; print(sys.version_info.minor)')"
                if [ "$PY_MINOR" -ge 10 ]; then
                    PYTHON_CMD="$cmd"
                    break
                fi
            fi
        done
        [ -z "$PYTHON_CMD" ] && fail "Python >= $PYTHON_MIN_VERSION required but not found"
    fi
fi

# ====================================================================
# Step 2: Virtual Environment + Torch
# ====================================================================

step "Step 2/6: Setting up Python virtual environment"

if [ -d "$VENV_DIR" ]; then
    info "Existing venv found at $VENV_DIR"
    source "$VENV_DIR/bin/activate"
    ok "Activated existing venv"
else
    VENV_OPTS=""
    if [ "${MIDIGPT_SYSTEM_SITE_PACKAGES:-}" = "true" ]; then
        VENV_OPTS="--system-site-packages"
        info "Enabling system site packages for venv..."
    fi
    "$PYTHON_CMD" -m venv $VENV_OPTS "$VENV_DIR"
    source "$VENV_DIR/bin/activate"
    pip install --upgrade pip setuptools wheel -q
    ok "Created and activated venv at $VENV_DIR"
fi

# Verify PyTorch installation (required by the MIDI-GPT model)
info "Checking PyTorch..."
if python -c "import torch" 2>/dev/null; then
    TORCH_VER="$(python -c 'import torch; print(torch.__version__)')"
    ok "PyTorch $TORCH_VER already installed"
else
    info "Installing PyTorch (this may take a few minutes)..."
    if [ "$PLATFORM" = "linux" ]; then
        pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu
    else
        pip install torch
    fi
    if python -c "import torch" 2>/dev/null; then
        TORCH_VER="$(python -c 'import torch; print(torch.__version__)')"
        ok "PyTorch $TORCH_VER installed"
    else
        echo ""
        warn "PyTorch could not be installed automatically."
        echo ""
        echo "  This usually means there is no pre-built PyTorch wheel for your"
        echo "  Python version or platform. Please install PyTorch manually:"
        echo ""
        echo "  1. Visit: https://pytorch.org/get-started/locally/"
        echo "  2. Select your OS, package manager (pip), and Python version"
        echo "  3. Run the install command it gives you (with this venv activated)"
        echo "  4. Then re-run this installer"
        echo ""
        fail "PyTorch installation failed. See instructions above."
    fi
fi

# Virtual environment is ready

# ====================================================================
# Step 3: Install MIDI-GPT Backend
# ====================================================================

step "Step 3/6: Installing MIDI-GPT backend"

if [ -n "$MIDIGPT_SRC" ] && [ -d "$MIDIGPT_SRC" ]; then
    info "Installing midigpt[http,inference] from source: $MIDIGPT_SRC ..."
    pip install -e "${MIDIGPT_SRC}[http,inference]" 2>&1 | tail -5
else
    info "Installing midigpt[http,inference] from PyPI ..."
    if ! pip install "midigpt[http,inference]" 2>&1 | tail -5; then
        warn "PyPI install failed — falling back to cloning MIDI-GPT from GitHub ..."
        MIDIGPT_CLONE="$(cd "$REPO_DIR/.." && pwd)/MIDI-GPT"
        if [ ! -d "$MIDIGPT_CLONE/.git" ]; then
            git clone https://github.com/Metacreation-Lab/MIDI-GPT.git "$MIDIGPT_CLONE" \
                || fail "Failed to clone MIDI-GPT. Check your internet connection and try again."
        else
            info "Existing MIDI-GPT clone found at $MIDIGPT_CLONE"
        fi
        pip install -e "${MIDIGPT_CLONE}[http,inference]" 2>&1 | tail -5 \
            || fail "Source install from cloned MIDI-GPT also failed."
    fi
fi

if python -c "from midigpt.inference.engine import InferenceEngine" 2>/dev/null; then
    ok "midigpt backend installed successfully"
else
    fail "midigpt backend installation failed."
fi

info "Installing plugin dependencies..."
pip install -e "$REPO_DIR" -q 2>/dev/null || pip install -e "$REPO_DIR"
ok "Plugin dependencies installed"

# ====================================================================
# Step 4: REAPER Integration (Symlinks)
# ====================================================================

step "Step 4/6: Setting up REAPER integration"

if [ "$PLATFORM" = "macos" ]; then
    REAPER_DIR="$HOME/Library/Application Support/REAPER"
elif [ "$PLATFORM" = "windows" ]; then
    REAPER_DIR="$APPDATA/REAPER"
else
    REAPER_DIR="$HOME/.config/REAPER"
fi

if [ -d "$REAPER_DIR" ]; then
    for pair in \
        "$REPO_DIR/src/Scripts/MIDI-GPT:$REAPER_DIR/Scripts/MIDI-GPT" \
        "$REPO_DIR/src/Effects/MIDI-GPT:$REAPER_DIR/Effects/MIDI-GPT"
    do
        src="${pair%%:*}"
        dst="${pair##*:}"
        [ -d "$src" ] || continue
        mkdir -p "$(dirname "$dst")"
        [ -e "$dst" ] || [ -L "$dst" ] && rm -rf "$dst"
        ln -sf "$src" "$dst"
    done
    ok "REAPER symlinks created"
else
    warn "REAPER config directory not found — REAPER may not be installed yet"
fi

# ====================================================================
# Step 5: Configure REAPER for Python / ReaScript
# ====================================================================

if [ "$SKIP_REAPER_CONFIG" = true ]; then
    step "Step 5/6: Skipping REAPER config (--skip-reaper-config)"
else
step "Step 5/6: Configuring REAPER (reaper.ini)"

REAPER_INI="$REAPER_DIR/reaper.ini"

# Detect the Python dynamic library (dylib/so/dll) for REAPER
PYTHON_DLL_PATH="$(python -c '
import sysconfig, pathlib, sys, os
ver = f"{sys.version_info.major}.{sys.version_info.minor}"
if sys.platform == "win32":
    base = pathlib.Path(sys.exec_prefix)
    for p in sorted(base.glob(f"python{sys.version_info.major}{sys.version_info.minor}.dll")):
        print(p); break
else:
    libdir = pathlib.Path(sysconfig.get_config_var("LIBDIR"))
    for ext in [".dylib", ".so"]:
        for p in sorted(libdir.glob(f"libpython{ver}*{ext}")):
            print(p); break
        else: continue
        break
')"

if [ -f "$REAPER_INI" ]; then
    if pgrep -x "REAPER" >/dev/null 2>&1 || pgrep -x "reaper" >/dev/null 2>&1; then
        warn "REAPER is currently running!"
        echo "  REAPER overwrites reaper.ini on quit, so changes would be lost."
        echo "  Please quit REAPER and re-run this installer, or configure manually:"
        echo "    Options > Preferences > Plug-Ins > ReaScript"
        if [ -n "$PYTHON_DLL_PATH" ]; then
            echo "    Python library: $PYTHON_DLL_PATH"
        fi
    else
        if [ -n "$PYTHON_DLL_PATH" ] && [ -f "$PYTHON_DLL_PATH" ]; then
            PY_LIB_DIR="$(dirname "$PYTHON_DLL_PATH")"
            PY_LIB_FILE="$(basename "$PYTHON_DLL_PATH")"

            set_reaper_ini() {
                local key="$1" value="$2" file="$3"
                if grep -q "^${key}=" "$file" 2>/dev/null; then
                    sed -i.bak "s|^${key}=.*|${key}=${value}|" "$file"
                else
                    sed -i.bak "/^\[REAPER\]/a\\
${key}=${value}
" "$file"
                fi
            }

            cp "$REAPER_INI" "${REAPER_INI}.midigpt-backup"
            info "Backed up reaper.ini → reaper.ini.midigpt-backup"

            set_reaper_ini "reascript" "1" "$REAPER_INI"
            if [ "$PLATFORM" = "windows" ]; then
                set_reaper_ini "pythonlibdll64" "$PYTHON_DLL_PATH" "$REAPER_INI"
            else
                set_reaper_ini "pythonlibpath64" "$PY_LIB_DIR" "$REAPER_INI"
                set_reaper_ini "pythonlibdll64" "$PY_LIB_FILE" "$REAPER_INI"
            fi

            rm -f "${REAPER_INI}.bak"
            ok "ReaScript enabled (reascript=1)"
            ok "Python library: $PY_LIB_DIR/$PY_LIB_FILE"
        else
            warn "Could not detect Python dynamic library path"
            echo "  You'll need to configure this manually in REAPER:"
            echo "    Options > Preferences > Plug-Ins > ReaScript"
        fi
    fi
else
    if [ -d "$REAPER_DIR" ]; then
        warn "reaper.ini not found — REAPER may not have been launched yet"
        echo "  Launch REAPER once, quit it, then re-run this installer to auto-configure."
    else
        warn "REAPER config directory not found — REAPER may not be installed"
    fi
    if [ -n "$PYTHON_DLL_PATH" ]; then
        echo "  When ready, set the Python library path to:"
        echo -e "    ${GREEN}$PYTHON_DLL_PATH${NC}"
    fi
fi
fi

# ====================================================================
# Step 6: Verify Backend Installation
# ====================================================================

step "Step 6/6: Verifying backend installation"

if python -c "from midigpt.inference.engine import InferenceEngine" 2>/dev/null; then
    ok "Verification successful: midigpt is installed and functional"
else
    fail "Verification failed: midigpt could not be imported"
fi

# ====================================================================
# Create Desktop shortcut to server launcher
# ====================================================================

DESKTOP_DIR="$HOME/Desktop"
if [ -d "$DESKTOP_DIR" ]; then
    if [ "$PLATFORM" = "macos" ]; then
        LAUNCHER="$REPO_DIR/Start Server - Mac.command"
        SHORTCUT="$DESKTOP_DIR/Start MIDI-GPT Server.command"
        if [ -f "$LAUNCHER" ]; then
            cat > "$SHORTCUT" << 'LAUNCHER_EOF'
#!/usr/bin/env bash
LAUNCHER_EOF
            echo "cd \"$(printf '%s' "$REPO_DIR")\" && bash \"./start_midigpt_server.sh\"" >> "$SHORTCUT"
            chmod +x "$SHORTCUT"
            ok "Desktop shortcut created: Start MIDI-GPT Server.command"
        fi
    elif [ "$PLATFORM" = "linux" ]; then
        SHORTCUT="$DESKTOP_DIR/Start MIDI-GPT Server.desktop"
        cat > "$SHORTCUT" << DESKTOP_EOF
[Desktop Entry]
Type=Application
Name=Start MIDI-GPT Server
Exec=bash -c 'cd "$REPO_DIR" && bash ./start_midigpt_server.sh'
Terminal=true
Icon=utilities-terminal
Comment=Start the MIDI-GPT inference server for REAPER
DESKTOP_EOF
        chmod +x "$SHORTCUT"
        ok "Desktop shortcut created: Start MIDI-GPT Server.desktop"
    fi
else
    info "No Desktop folder found — skipping shortcut creation"
fi

# ====================================================================
# Final: Summary and Next Steps
# ====================================================================

echo ""
echo -e "${BOLD}════════════════════════════════════════════════════${NC}"
echo -e "${GREEN}${BOLD}  Installation Complete!${NC}"
echo -e "${BOLD}════════════════════════════════════════════════════${NC}"
echo ""

echo -e "${BOLD}Next steps in REAPER:${NC}"
echo ""
echo "  1. Load the ReaScript action:"
echo "     Actions > Show Action List > Load ReaScript"
echo "     Select: $REAPER_DIR/Scripts/MIDI-GPT/REAPER_midigpt_infill.py"
echo ""
echo "  2. Add JSFX plugins:"
echo "     - Add 'MIDI-GPT Global Options' to Monitor FX (View > Monitoring Effects)"
echo "     - Add 'MIDI-GPT Track Options (Yellow)', '(Prism)', or '(Expressive)' to tracks"
echo ""
echo -e "${BOLD}To start the server:${NC}"
if [ -d "$HOME/Desktop" ]; then
    echo "  Double-click ${GREEN}Start MIDI-GPT Server${NC} on your Desktop"
elif [ "$PLATFORM" = "macos" ]; then
    echo "  Double-click: ${GREEN}Start Server - Mac.command${NC}"
elif [ "$PLATFORM" = "windows" ]; then
    echo "  Double-click: ${GREEN}Start Server - Windows.bat${NC}"
else
    echo "  Run: ${GREEN}./start_midigpt_server.sh${NC}"
fi
echo "  Or from terminal: cd $REPO_DIR && source .venv/bin/activate && midigpt-http"
echo ""

# ====================================================================
# Interactive: Launch server now?
# ====================================================================

if [ -t 0 ]; then
    echo ""
    echo -e "${BOLD}----------------------------------------------------${NC}"
    echo -e "${BOLD}  Launch Server${NC}"
    echo -e "${BOLD}----------------------------------------------------${NC}"
    echo ""
    echo "  Would you like to start the MIDI-GPT server now?"
    echo ""
    read -rp "  Launch server? [Y/n]: " _LAUNCH
    _LAUNCH="${_LAUNCH:-y}"

    if [[ "$_LAUNCH" =~ ^[Yy]$ ]]; then
        echo ""
        echo -e "${BOLD}  Select a model:${NC}"
        echo ""
        echo "    [1] Yellow     - General purpose, recommended (yellow_medium)"
        echo "    [2] Prism      - Extended controls (prism_medium)"
        echo "    [3] Expressive - Microtiming + velocity (expressive_medium)"
        echo ""
        read -rp "  Model [1/2/3, default=1]: " _MODEL_CHOICE

        case "${_MODEL_CHOICE:-1}" in
            2) _MODEL="prism_medium"      ; _LABEL="Prism"      ;;
            3) _MODEL="expressive_medium" ; _LABEL="Expressive" ;;
            *) _MODEL="yellow_medium"     ; _LABEL="Yellow"     ;;
        esac

        echo ""
        echo -e "${BOLD}  Starting MIDI-GPT server (${_LABEL})...${NC}"
        echo "  Keep this terminal open while using MIDI-GPT in REAPER."
        echo "  Press Ctrl+C to stop the server."
        echo ""
        bash "$REPO_DIR/start_midigpt_server.sh" --pretrained "$_MODEL"
    else
        echo ""
        echo -e "${BOLD}Next steps:${NC}"
        echo "  Start the server later with:"
        echo -e "    ${GREEN}cd $REPO_DIR && ./start_midigpt_server.sh${NC}"
        echo ""
    fi
elif [ -n "${MIDIGPT_INTERACTIVE:-}" ]; then
    echo ""
    read -rp "Press Enter to close this window..."
fi
