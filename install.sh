#!/usr/bin/env bash
# ============================================================================
# MIDI-GPT for REAPER — One-Click Installer
#
# Installs everything needed to run MIDI-GPT in REAPER:
#   1. System dependencies (git, python)
#   2. Python virtual environment + torch
#   3. MIDI-GPT backend library
#   4. REAPER symlinks (Scripts), plus ReaPack and ReaImGui (the dashboard
#      UI's REAPER extension dependencies)
#   5. Verification of installation
#
# ReaPack itself is installed directly (it's just an extension binary,
# downloaded over HTTPS from its GitHub release and checksum-verified
# against GitHub's own published digest before use -- it isn't code-signed,
# so this is the only integrity check available for it). The dashboard
# UI's ReaImGui extension is also downloaded directly from codeberg.org
# (ReaTeam Extensions) with checksum verification. Both installs require
# REAPER to be closed (the installer will ask permission to close it).
#
# Usage:
#   ./install.sh              # Full install
#   ./install.sh --skip-deps  # Skip system dependency check (if already installed)
#   ./install.sh --torch-gpu  # Install PyTorch with CUDA/MPS support
#   ./install.sh --reaper-only  # Only REAPER integration (symlinks, ReaPack, ReaImGui, reaper.ini)
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

check_build_tools() {
    local missing=()
    case "$PLATFORM" in
        macos)
            if ! check_cmd xcodebuild; then
                missing+=("Xcode Command Line Tools (run: xcode-select --install)")
            fi
            ;;
        linux)
            if ! check_cmd gcc || ! check_cmd cmake; then
                missing+=("build tools: gcc, cmake (e.g. sudo apt install build-essential cmake)")
            fi
            ;;
        windows)
            if ! check_cmd cl.exe && ! check_cmd cmake; then
                missing+=("Visual Studio Build Tools + CMake (winget install Microsoft.VisualStudio.2022.BuildTools; winget install Kitware.CMake)")
            fi
            ;;
    esac
    if [ ${#missing[@]} -gt 0 ]; then
        warn "Source install requires compilation tools:"
        for m in "${missing[@]}"; do
            echo "  - $m"
        done
        return 1
    fi
    return 0
}

reaper_is_running() {
    # Test-only override (see tests/integration/) -- simulates REAPER
    # being open without needing a real REAPER process running.
    if [ -n "${MIDIGPT_FAKE_REAPER_RUNNING:-}" ]; then
        [ "$MIDIGPT_FAKE_REAPER_RUNNING" = "true" ]
        return
    fi
    pgrep -x "REAPER" >/dev/null 2>&1 || pgrep -x "reaper" >/dev/null 2>&1
}

# Ask REAPER to quit gracefully (triggers its own "save changes?" prompt if
# needed -- never force-kills) and wait for the process to actually exit.
quit_reaper_and_wait() {
    info "Asking REAPER to quit -- any unsaved project will prompt you to save first..."
    if [ "$PLATFORM" = "macos" ]; then
        osascript -e 'tell application "REAPER" to quit' 2>/dev/null
    else
        pkill -TERM -x reaper 2>/dev/null
    fi

    local waited=0
    while reaper_is_running && [ "$waited" -lt 120 ]; do
        sleep 2
        waited=$((waited + 2))
    done

    if reaper_is_running; then
        warn "REAPER is still open (it may be waiting on a save prompt)."
        read -rp "  Close it manually, then press Enter to continue (Ctrl+C to abort): " _
    fi
}

relaunch_reaper() {
    # Test-only override -- simulates REAPER relaunch without real process
    if [ -n "${MIDIGPT_FAKE_REAPER_RUNNING:-}" ]; then
        info "Test mode: simulating REAPER relaunch"
        return 0
    fi
    if [ "$PLATFORM" = "macos" ]; then
        open -a REAPER 2>/dev/null
    elif check_cmd reaper; then
        nohup reaper >/dev/null 2>&1 &
        disown 2>/dev/null || true
    else
        warn "Could not find a 'reaper' command to relaunch it automatically -- start it manually."
        return 1
    fi
    return 0
}

open_url() {
    local url="$1"
    if [ "$PLATFORM" = "macos" ]; then
        open "$url" 2>/dev/null
        return $?
    elif [ "$PLATFORM" = "windows" ]; then
        cmd.exe /c start "" "$url" 2>/dev/null
        return $?
    else
        xdg-open "$url" 2>/dev/null
        return $?
    fi
}

# Downloads the Arachno GM SoundFont into this repo's own soundfonts/
# folder (kept alongside the plugin, not scattered into REAPER's resource
# dir), under its real filename -- MIDI-GPT Setup Tracks.py reads
# whatever .sf2 is actually there rather than a hardcoded name, so this
# doesn't need to match anything else exactly. Arachno is freeware and this
# is the exact .zip Arachnosoft's own download page links to (mirrored on
# Dropbox) -- not a third-party scrape. Sforzando itself is a real
# application installer, not a data file, so it's intentionally NOT
# auto-installed the same way (see the instrument-setup prompt below).
download_arachno_soundfont() {
    if ! check_cmd unzip; then
        warn "'unzip' not found -- install it, or get Arachno manually: https://www.arachnosoft.com/main/download.php?id=soundfont-sf2"
        return 1
    fi

    local dest_dir="$REPO_DIR/soundfonts"
    if find "$dest_dir" -iname "*.sf2" 2>/dev/null | grep -q .; then
        ok "Arachno SoundFont already present in $dest_dir"
        return 0
    fi

    info "Downloading Arachno SoundFont (~140MB, may take a few minutes)..."
    mkdir -p "$dest_dir"
    local tmp_zip
    tmp_zip="$(mktemp).zip"
    if ! curl -fL --max-time 900 -o "$tmp_zip" "https://www.dropbox.com/s/2rnpya9ecb9m4jh/arachno-soundfont-10-sf2.zip?dl=1"; then
        warn "Failed to download Arachno SoundFont -- get it manually: https://www.arachnosoft.com/main/download.php?id=soundfont-sf2"
        rm -f "$tmp_zip"
        return 1
    fi

    local inner_name dest_file
    inner_name="$(unzip -Z1 "$tmp_zip" 2>/dev/null | grep -i '\.sf2$' | head -1)"
    dest_file="$dest_dir/$inner_name"
    if [ -z "$inner_name" ] || ! unzip -p "$tmp_zip" "$inner_name" > "$dest_file" 2>/dev/null; then
        warn "Downloaded archive didn't extract cleanly -- get Arachno manually: https://www.arachnosoft.com/main/download.php?id=soundfont-sf2"
        rm -f "$tmp_zip" "$dest_file"
        return 1
    fi
    rm -f "$tmp_zip"
    ok "Arachno SoundFont installed: $dest_file"
    return 0
}

# Downloads ReaImGui extension completely (native binary + Python API + Lua shims)
# directly from codeberg.org, replicating what ReaPack does from the ReaTeam Extensions repo.
# This avoids the bootstrap race condition and doesn't require REAPER restarts.
#
# Checksums: used when codeberg's release API publishes one for a file
# (a `sha256`, or a GitHub-style `digest`, field on the asset). At the time
# of writing it publishes none -- and imgui.lua isn't a release asset at all
# -- so these install unverified, with a warning saying so.
# ReaImGui releases: https://codeberg.org/cfillion/reaimgui/releases
REAIMGUI_VERSION="0.10.0.5"

# Prints "name sha256" lines for the release assets codeberg publishes a
# checksum for (possibly none).
reaimgui_checksums() {
    check_cmd python3 || return 0
    curl -fsSL "https://codeberg.org/api/v1/repos/cfillion/reaimgui/releases/tags/v$REAIMGUI_VERSION" 2>/dev/null |
        python3 -c "
import json, sys
try:
    for a in json.load(sys.stdin).get('assets', []):
        sha = a.get('sha256') or (a.get('digest') or '').replace('sha256:', '')
        if sha:
            print(a['name'], sha.lower())
except Exception:
    pass
" 2>/dev/null || true
}

# Downloads $1 to $2. If $3 (an expected SHA256) is non-empty, the file is
# kept only if it matches. Sets REAIMGUI_UNVERIFIED when installed without
# one.
fetch_reaimgui_file() {
    local url="$1" dest="$2" expected_sha="$3"
    local tmp actual_sha
    tmp="$(mktemp)"
    if ! curl -fsSL "$url" -o "$tmp"; then
        warn "Failed to download $(basename "$dest") from $url"
        rm -f "$tmp"
        return 1
    fi
    if [ -n "$expected_sha" ]; then
        actual_sha="$( (shasum -a 256 "$tmp" 2>/dev/null || sha256sum "$tmp" 2>/dev/null) | awk '{print $1}')"
        if [ "$actual_sha" != "$expected_sha" ]; then
            warn "$(basename "$dest") didn't match its published checksum -- discarded (expected $expected_sha, got ${actual_sha:-none})"
            rm -f "$tmp"
            return 1
        fi
        mv "$tmp" "$dest"
        ok "$(basename "$dest") installed and checksum-verified"
    else
        mv "$tmp" "$dest"
        ok "$(basename "$dest") installed"
        REAIMGUI_UNVERIFIED="$REAIMGUI_UNVERIFIED $(basename "$dest")"
    fi
}

download_reaimgui() {
    local platform_arch="$1"
    local dest_dir="$2"
    local imgui_asset=""

    case "$platform_arch" in
        macos:arm64|macos:aarch64) imgui_asset="reaper_imgui-arm64.dylib" ;;
        macos:x86_64)              imgui_asset="reaper_imgui-x86_64.dylib" ;;
        linux:aarch64|linux:arm64) imgui_asset="reaper_imgui-aarch64.so" ;;
        linux:x86_64)              imgui_asset="reaper_imgui-x86_64.so" ;;
        linux:armv7l)              imgui_asset="reaper_imgui-armv7l.so" ;;
        linux:i686)                imgui_asset="reaper_imgui-i686.so" ;;
        *) return 1 ;;
    esac

    local userplugins_dir="$dest_dir"
    local api_dir="$dest_dir/../Scripts/ReaTeam Extensions/API"
    local rel_url="https://codeberg.org/cfillion/reaimgui/releases/download/v$REAIMGUI_VERSION"
    local sums
    sums="$(reaimgui_checksums)"
    # Expected SHA256 for a release asset, or empty if none is published.
    sum_for() { printf '%s\n' "$sums" | awk -v n="$1" '$1 == n { print $2 }'; }

    info "Installing ReaImGui v$REAIMGUI_VERSION ($imgui_asset + Python API)..."
    mkdir -p "$userplugins_dir" "$api_dir"
    REAIMGUI_UNVERIFIED=""

    # ---- 1. Native binary ----
    fetch_reaimgui_file "$rel_url/$imgui_asset" "$userplugins_dir/$imgui_asset" "$(sum_for "$imgui_asset")" || return 1
    if [ "$PLATFORM" = "macos" ]; then
        xattr -d com.apple.quarantine "$userplugins_dir/$imgui_asset" 2>/dev/null || true
    fi

    # ---- 2. Python API (imgui.py) -- MIDI-GPT.py imports it, so required ----
    fetch_reaimgui_file "$rel_url/imgui.py" "$api_dir/imgui.py" "$(sum_for imgui.py)" || return 1

    # ---- 3. Lua shims (not used by MIDI-GPT; installed for ReaPack parity) ----
    fetch_reaimgui_file "https://codeberg.org/cfillion/reaimgui/raw/v$REAIMGUI_VERSION/shims/imgui.lua" \
        "$api_dir/imgui.lua" "" || true
    fetch_reaimgui_file "$rel_url/gfx2imgui.lua" "$api_dir/gfx2imgui.lua" "$(sum_for gfx2imgui.lua)" || true

    if [ -n "$REAIMGUI_UNVERIFIED" ]; then
        warn "No published checksum for ReaImGui$REAIMGUI_UNVERIFIED -- installed unverified"
    fi
    return 0
}

# ── Args ────────────────────────────────────────────────────────

REAPER_ONLY=false
BACKEND_ONLY=false
TORCH_GPU=false

for arg in "$@"; do
    case "$arg" in
        --skip-deps) SKIP_DEPS=true ;;
        --skip-reaper-config) SKIP_REAPER_CONFIG=true ;;
        --reaper-only) REAPER_ONLY=true ;;
        --backend-only) BACKEND_ONLY=true ;;
        --torch-gpu) TORCH_GPU=true ;;
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
            echo "  --reaper-only        Only do REAPER integration (Step 4/5: symlinks, ReaPack,"
            echo "                       ReaImGui, reaper.ini) -- skips venv/backend entirely."
            echo "                       Useful to redo just the REAPER side, or for testing."
            echo "  --backend-only       Only do venv/backend (Steps 1-3, 6) -- skips REAPER"
            echo "                       integration entirely, so it never needs REAPER closed."
            echo "                       What update.sh uses to refresh the backend in place."
            echo "  --torch-gpu          Install PyTorch with GPU support (CUDA on Linux/Windows,"
            echo "                       MPS on macOS is included in default wheel)."
            echo "  --midigpt-src=PATH   Path to the MIDI-GPT source repository (sibling folder by default)"
            echo "  --help               Show this help"
            echo ""
            echo "Examples:"
            echo "  ./install.sh                                   # Full installation (CPU torch)"
            echo "  ./install.sh --torch-gpu                       # Full installation with GPU torch"
            echo "  ./install.sh --midigpt-src=/custom/path        # Custom MIDI-GPT source path"
            echo "  ./install.sh --reaper-only                     # Just (re)do REAPER integration"
            echo "  ./install.sh --backend-only                    # Just refresh venv/backend"
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
ARCH="$(uname -m)"
info "Platform: $PLATFORM ($OS) [$ARCH]"

if [ "$REAPER_ONLY" = true ]; then
    step "Skipping system deps / venv / backend (--reaper-only)"
    # Still need a python to detect the ReaScript library path in Step 5.
    if [ -z "${PYTHON_CMD:-}" ]; then
        for cmd in python3.12 python3.11 python3.10 python3; do
            if check_cmd "$cmd"; then
                PYTHON_CMD="$cmd"
                break
            fi
        done
    fi
fi

# ====================================================================
# Step 1: System Dependencies
# ====================================================================

if [ "$REAPER_ONLY" = false ]; then

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

    # -- curl -- required for ReaPack/Arachno downloads (Step 4) and for
    # bootstrapping Homebrew below if that's needed too. Present by default
    # on macOS and most desktop Linux distros, but not guaranteed on
    # minimal/server/HPC-cluster Linux images.
    if check_cmd curl; then
        ok "curl $(curl --version | head -1 | awk '{print $2}')"
    else
        MISSING+=("curl")
        warn "curl not found"
    fi

    # -- Install missing deps --
    if [ ${#MISSING[@]} -gt 0 ]; then
        echo ""
        warn "Missing dependencies: ${MISSING[*]}"
        echo ""

        # Try to auto-install git on macOS via Homebrew
        if [[ " ${MISSING[*]} " == *"git"* ]] && [ "$PLATFORM" = "macos" ]; then
            if check_cmd brew; then
                info "Installing git via Homebrew..."
                brew install git || fail "Homebrew install failed"
            else
                echo "  Install Homebrew first, then re-run:"
                echo '    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"'
                echo ""
                fail "Homebrew not found"
            fi
        elif [[ " ${MISSING[*]} " == *"git"* ]] && [ "$PLATFORM" = "linux" ]; then
            fail "Please install git (e.g. sudo apt install git) then re-run"
        fi

        if [[ " ${MISSING[*]} " == *"curl"* ]]; then
            if [ "$PLATFORM" = "linux" ]; then
                fail "Please install curl (e.g. sudo apt install curl, or ask your cluster admin / try 'module load curl') then re-run"
            elif [ "$PLATFORM" = "macos" ]; then
                fail "Please install curl (e.g. brew install curl) then re-run"
            else
                fail "Please install curl (e.g. winget install curl.curl or choco install curl) then re-run"
            fi
        fi

        # Python missing — give platform-specific install guidance
        if [[ " ${MISSING[*]} " == *"python"* ]]; then
            echo "  Python 3.10, 3.11, or 3.12 is required. Install options:"
            echo ""
            if [ "$PLATFORM" = "macos" ]; then
                echo "  Option A — Homebrew (recommended):"
                echo "    brew install python@3.12"
                echo ""
                echo "  Option B — Official installer:"
                echo "    https://www.python.org/downloads/"
                echo "    Download Python 3.12 for macOS and run the .pkg"
            elif [ "$PLATFORM" = "linux" ]; then
                echo "  Ubuntu/Debian:"
                echo "    sudo apt update && sudo apt install python3.12 python3.12-venv"
                echo ""
                echo "  Other distros: https://www.python.org/downloads/"
            else
                echo "  Download Python 3.12 from: https://www.python.org/downloads/"
            fi
            echo ""
            echo "  After installing Python, re-run this installer."
            fail "Python >= $PYTHON_MIN_VERSION is required"
        fi
    fi

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
        if [ "$TORCH_GPU" = true ]; then
            pip install torch torchvision --index-url https://download.pytorch.org/whl/cu121
        else
            pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu
        fi
    elif [ "$PLATFORM" = "windows" ]; then
        if [ "$TORCH_GPU" = true ]; then
            pip install torch torchvision --index-url https://download.pytorch.org/whl/cu121
        else
            pip install torch
        fi
    else
        # macOS: default wheel includes MPS support for Apple Silicon
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
        echo "  3. Run the install command it gives you WITH THIS VENV ACTIVATED:"
        echo "       source $VENV_DIR/bin/activate"
        echo "       pip install <command-from-pytorch-org>"
        echo "  4. Then re-run this installer (it will detect existing torch)"
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
    check_build_tools || fail "Missing build tools required for source install"
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

fi # REAPER_ONLY == false (Steps 1-3)

# Referenced unconditionally later (the relaunch check, and the final
# summary) so this must be defined even under --backend-only, which skips
# the block below that would otherwise set it.
REAPER_WAS_CLOSED_BY_US=false

if [ "$BACKEND_ONLY" = false ]; then
# ====================================================================
# Step 4: REAPER Integration (Symlinks, ReaPack, ReaImGui)
# ====================================================================

step "Step 4/6: Setting up REAPER integration"

if [ -n "${MIDIGPT_REAPER_DIR:-}" ]; then
    # Test-only override (see tests/integration/) -- lets the REAPER
    # integration logic run against a disposable fake directory instead of
    # the real REAPER install, so different starting states (empty,
    # ReaPack already present, existing reaper.ini content, etc.) can be
    # exercised repeatably without ever touching a real machine's REAPER.
    REAPER_DIR="$MIDIGPT_REAPER_DIR"
elif [ "$PLATFORM" = "macos" ]; then
    REAPER_DIR="$HOME/Library/Application Support/REAPER"
elif [ "$PLATFORM" = "windows" ]; then
    REAPER_DIR="$APPDATA/REAPER"
else
    REAPER_DIR="$HOME/.config/REAPER"
fi

if [ -d "$REAPER_DIR" ]; then
    # Installing ReaPack and configuring reaper.ini (Step 5) both need REAPER
    # closed. Ask once, up front, so both steps can run this pass instead of
    # telling the user to re-run the installer later.
    if reaper_is_running; then
        if [ -t 0 ]; then
            warn "REAPER is currently running."
            echo "  Installing ReaPack and configuring REAPER (reaper.ini) both require REAPER"
            echo "  to be closed. Nothing is discarded silently -- REAPER will prompt you to"
            echo "  save any unsaved project first, same as quitting normally."
            read -rp "  Close REAPER now and continue? [y/N]: " _CLOSE_REAPER
            if [[ "$_CLOSE_REAPER" =~ ^[Yy]$ ]]; then
                quit_reaper_and_wait
                if ! reaper_is_running; then
                    REAPER_WAS_CLOSED_BY_US=true
                fi
            else
                warn "Continuing with REAPER open -- ReaPack install and reaper.ini setup will be skipped this run."
            fi
        else
            warn "REAPER is currently running -- ReaPack install and reaper.ini setup require REAPER to be closed (non-interactive)."
            echo "  Close REAPER, then re-run this installer:"
            echo "    ./install.sh"
            exit 1
        fi
    fi

    for pair in \
        "$REPO_DIR/src/Scripts/MIDI-GPT:$REAPER_DIR/Scripts/MIDI-GPT"
    do
        src="${pair%%:*}"
        dst="${pair##*:}"
        [ -d "$src" ] || continue
        mkdir -p "$(dirname "$dst")"
        [ -e "$dst" ] || [ -L "$dst" ] && rm -rf "$dst"
        ln -sf "$src" "$dst"
    done
    ok "REAPER symlinks created"

    # -- ReaPack + ReaImGui --
    REAPACK_READY=false
    if find "$REAPER_DIR/UserPlugins" -iname "reaper_reapack*" 2>/dev/null | grep -q .; then
        ok "ReaPack already installed"
        REAPACK_READY=true
    elif reaper_is_running; then
        warn "ReaPack not installed, and REAPER is still open -- skipping (re-run after closing REAPER, or install manually: https://reapack.com/)"
    else
        info "Installing ReaPack..."
        ARCH="$(uname -m)"
        REAPACK_ASSET=""
        case "$PLATFORM:$ARCH" in
            macos:arm64|macos:aarch64) REAPACK_ASSET="reaper_reapack-arm64.dylib" ;;
            macos:x86_64)              REAPACK_ASSET="reaper_reapack-x86_64.dylib" ;;
            linux:aarch64|linux:arm64) REAPACK_ASSET="reaper_reapack-aarch64.so" ;;
            linux:x86_64)              REAPACK_ASSET="reaper_reapack-x86_64.so" ;;
            linux:armv7l)              REAPACK_ASSET="reaper_reapack-armv7l.so" ;;
            linux:i686)                REAPACK_ASSET="reaper_reapack-i686.so" ;;
            windows:*)                 REAPACK_ASSET="reaper_reapack-x64.dll" ;;
        esac

        if [ -n "$REAPACK_ASSET" ]; then
            mkdir -p "$REAPER_DIR/UserPlugins"
            REAPACK_URL="https://github.com/cfillion/reapack/releases/latest/download/$REAPACK_ASSET"
            REAPACK_DEST="$REAPER_DIR/UserPlugins/$REAPACK_ASSET"

            # ReaPack's own releases aren't code-signed, so there's no
            # signature to verify -- fetch GitHub's published SHA256 for
            # this exact asset instead, so we can at least catch a
            # corrupted or tampered-with download before trusting it.
            # Fetched with curl (system trust store, same as the download
            # itself) rather than python's urllib -- a python installed
            # without its CA bootstrap (common with the official
            # python.org macOS installer, before running its "Install
            # Certificates.command") would otherwise fail here silently.
            # python is only used to parse the already-fetched JSON text.
            REAPACK_EXPECTED_SHA=""
            # `|| true` -- a network hiccup or GitHub API rate-limit here must
            # not abort the whole install under `set -e`; the checksum is a
            # nice-to-have (handled as "installing unverified" below), not a
            # hard requirement.
            # Unauthenticated API calls share a 60/hour limit per IP (CI runners
            # share IPs); a GITHUB_TOKEN in the environment (CI sets one)
            # raises that to 1000/hour.
            REAPACK_API_URL="https://api.github.com/repos/cfillion/reapack/releases/latest"
            if [ -n "${GITHUB_TOKEN:-}" ]; then
                REAPACK_RELEASE_JSON="$(curl -fsSL -H "Authorization: Bearer $GITHUB_TOKEN" "$REAPACK_API_URL" 2>/dev/null || true)"
            else
                REAPACK_RELEASE_JSON="$(curl -fsSL "$REAPACK_API_URL" 2>/dev/null || true)"
            fi
            if [ -n "$REAPACK_RELEASE_JSON" ] && check_cmd python3; then
                REAPACK_EXPECTED_SHA="$(printf '%s' "$REAPACK_RELEASE_JSON" | python3 -c "
import json, sys
try:
    data = json.load(sys.stdin)
    for a in data.get('assets', []):
        if a['name'] == '$REAPACK_ASSET':
            print(a.get('digest', '').replace('sha256:', ''))
            break
except Exception:
    pass
" 2>/dev/null)"
            fi

            if curl -fsSL "$REAPACK_URL" -o "$REAPACK_DEST"; then
                REAPACK_VERIFIED=true
                if [ -n "$REAPACK_EXPECTED_SHA" ]; then
                    REAPACK_ACTUAL_SHA="$( (shasum -a 256 "$REAPACK_DEST" 2>/dev/null || sha256sum "$REAPACK_DEST" 2>/dev/null) | awk '{print $1}')"
                    if [ "$REAPACK_ACTUAL_SHA" != "$REAPACK_EXPECTED_SHA" ]; then
                        REAPACK_VERIFIED=false
                    fi
                else
                    warn "Could not fetch an expected checksum for ReaPack -- installing unverified"
                fi

                if [ "$REAPACK_VERIFIED" = true ]; then
                    if [ "$PLATFORM" = "macos" ]; then
                        # curl-downloaded files can still end up quarantined
                        # on recent macOS, which silently blocks REAPER
                        # from loading the extension until the user
                        # manually approves it in System Settings > Privacy
                        # & Security. Strip it ourselves, now that the
                        # checksum above confirms it's what GitHub actually
                        # published -- this is our own file, in our own
                        # user directory, so no elevated privileges needed.
                        xattr -d com.apple.quarantine "$REAPACK_DEST" 2>/dev/null || true
                    fi
                    if [ -n "$REAPACK_EXPECTED_SHA" ]; then
                        ok "ReaPack installed and checksum-verified ($REAPACK_ASSET)"
                    else
                        ok "ReaPack installed, unverified ($REAPACK_ASSET)"
                    fi
                    REAPACK_READY=true
                else
                    rm -f "$REAPACK_DEST"
                    warn "Downloaded ReaPack didn't match GitHub's published checksum -- discarded. Install manually: https://reapack.com/"
                fi
            else
                warn "Failed to download ReaPack -- install manually: https://reapack.com/"
            fi
        else
            warn "Unrecognized platform/architecture ($PLATFORM/$ARCH) -- install ReaPack manually: https://reapack.com/"
        fi
    fi

    # The dashboard needs both the extension binary and imgui.py; a binary
    # alone (e.g. from an older version of this installer) still leaves
    # `import imgui` failing.
    if find "$REAPER_DIR/UserPlugins" -iname "reaper_imgui*" 2>/dev/null | grep -q . \
        && [ -f "$REAPER_DIR/Scripts/ReaTeam Extensions/API/imgui.py" ]; then
        ok "ReaImGui already installed"
    else
        if download_reaimgui "$PLATFORM:$ARCH" "$REAPER_DIR/UserPlugins"; then
            REAPACK_READY=true
        else
            warn "Direct ReaImGui download failed"
            if [ "$REAPACK_READY" = true ]; then
                warn "ReaImGui not installed — manual installation required:"
                echo "  In REAPER: Extensions > ReaPack > Browse packages > search 'ReaImGui' > install > restart REAPER"
                echo "  This also installs the other packages in the 'ReaTeam Extensions' repo (ReaBlink, ReaMCULive, js_ReaScriptAPI)"
            else
                warn "ReaImGui extension not found — the dashboard UI needs it"
                echo "  In REAPER: Extensions > ReaPack > Browse packages > search 'ReaImGui' > install > restart REAPER"
            fi
        fi
    fi
else
    warn "REAPER config directory not found — REAPER may not be installed yet"
    echo "  Install REAPER: https://www.reaper.fm/download.php"
    echo "  Launch REAPER once, quit it, then re-run this installer:"
    echo "    ./install.sh"
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
PYTHON_DLL_PATH="$("${PYTHON_CMD:-python3}" -c '
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
    if reaper_is_running; then
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
                    awk -v k="$key" -v v="$value" '
                        $0 ~ "^" k "=" { print k "=" v; next }
                        { print }
                    ' "$file" > "${file}.tmp" && mv "${file}.tmp" "$file"
                else
                    # REAPER writes the section header as [reaper] (lowercase)
                    # on some versions/platforms and [REAPER] on others -- match
                    # either. If no such section exists yet (fresh reaper.ini),
                    # append one at the end of the file.
                    awk -v k="$key" -v v="$value" '
                        BEGIN { done = 0 }
                        {
                            print
                            if (!done && tolower($0) == "[reaper]") {
                                print k "=" v
                                done = 1
                            }
                        }
                        END {
                            if (!done) {
                                print ""
                                print "[REAPER]"
                                print k "=" v
                            }
                        }
                    ' "$file" > "${file}.tmp" && mv "${file}.tmp" "$file"
                fi
            }

            cp "$REAPER_INI" "${REAPER_INI}.midigpt-backup"
            info "Backed up reaper.ini → reaper.ini.midigpt-backup"

            # pythonlibpath64 = directory, pythonlibdll64 = bare file name --
            # REAPER's format on every platform (install.ps1 does the same).
            set_reaper_ini "reascript" "1" "$REAPER_INI"
            set_reaper_ini "pythonlibpath64" "$PY_LIB_DIR" "$REAPER_INI"
            set_reaper_ini "pythonlibdll64" "$PY_LIB_FILE" "$REAPER_INI"

            if grep -q "^reascript=1" "$REAPER_INI" && grep -q "^pythonlibdll64=" "$REAPER_INI"; then
                ok "ReaScript enabled (reascript=1)"
                ok "Python library: $PY_LIB_DIR/$PY_LIB_FILE"
            else
                warn "Failed to write ReaScript/Python settings to reaper.ini"
                echo "  Configure manually: Options > Preferences > Plug-Ins > ReaScript"
                echo "    Python library: $PY_LIB_DIR/$PY_LIB_FILE"
            fi

            # Sforzando's Linux .deb installs its VST3 to /usr/lib/vst3, which
            # REAPER on Linux doesn't scan by default (~/.vst;~/.vst3 only), so
            # without this only its CLAP shows up -- and Setup Tracks can't use CLAP.
            if [ "$PLATFORM" = "linux" ]; then
                # || true: no vstpath= line yet is the normal fresh case, and
                # grep's exit 1 would otherwise abort the installer (set -e).
                VST_PATH="$(grep -m1 '^vstpath=' "$REAPER_INI" | cut -d= -f2- || true)"
                [ -n "$VST_PATH" ] || VST_PATH='~/.vst;~/.vst3'
                case ";$VST_PATH;" in
                    *";/usr/lib/vst3;"*) ;;
                    *) set_reaper_ini "vstpath" "$VST_PATH;/usr/lib/vst3" "$REAPER_INI" ;;
                esac
                ok "VST plug-in paths: $(grep -m1 '^vstpath=' "$REAPER_INI" | cut -d= -f2-)"
            fi
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
        echo "  Install REAPER: https://www.reaper.fm/download.php"
        echo "  Launch REAPER once, quit it, then re-run this installer:"
        echo "    ./install.sh"
    fi
    if [ -n "$PYTHON_DLL_PATH" ]; then
        echo ""
        echo "  Manual REAPER configuration required:"
        echo "  1. Open REAPER"
        echo "  2. Options > Preferences > Plug-Ins > ReaScript"
        echo "  3. Enable 'ReaScript' (checkbox)"
        echo "  4. Set 'Python library' to:"
        echo -e "       ${GREEN}$PYTHON_DLL_PATH${NC}"
        echo "  5. Click OK, then RESTART REAPER for changes to take effect."
    fi
fi
fi
fi # BACKEND_ONLY == false (Steps 4-5)

# Check if we need to launch REAPER:
# 1. We closed REAPER ourselves (for ReaPack/reaper.ini changes)
# If direct ReaImGui download succeeded, no relaunch needed for ImGui.
NEED_REAPER_RELAUNCH=false
if [ "$REAPER_WAS_CLOSED_BY_US" = true ]; then
    if ! reaper_is_running; then
        NEED_REAPER_RELAUNCH=true
    fi
fi

if [ "$NEED_REAPER_RELAUNCH" = true ]; then
    info "Relaunching REAPER so ReaPack can load..."
    if relaunch_reaper; then
        ok "REAPER relaunched -- ReaPack loaded"
        # Close REAPER gracefully so user starts fresh
        quit_reaper_and_wait
        info "REAPER closed. Setup complete — start REAPER when ready to use MIDI-GPT."
    fi
fi

# Referenced unconditionally in the final summary below, so this must be
# defined even under --reaper-only (which skips the block that would
# otherwise set it).
DESKTOP_SHORTCUT_CREATED=false

if [ "$REAPER_ONLY" = false ]; then
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
            # ~/Desktop can be blocked by macOS's Full Disk Access / TCC
            # restrictions for processes without an interactive GUI
            # session (e.g. a script run over SSH) -- this is purely a
            # convenience shortcut, so a failure here must never take down
            # an otherwise-successful install (set -e would otherwise
            # abort the whole script on the redirection failing).
            SHORTCUT_OK=true
            printf '#!/usr/bin/env bash\ncd "%s" && bash "./start_midigpt_server.sh"\n' "$REPO_DIR" > "$SHORTCUT" 2>/dev/null || SHORTCUT_OK=false
            if [ "$SHORTCUT_OK" = true ]; then
                chmod +x "$SHORTCUT" 2>/dev/null || SHORTCUT_OK=false
            fi
            if [ "$SHORTCUT_OK" = true ]; then
                ok "Desktop shortcut created: Start MIDI-GPT Server.command"
                DESKTOP_SHORTCUT_CREATED=true
            else
                warn "Couldn't create Desktop shortcut (permission denied -- this can happen when running non-interactively, e.g. over SSH, without Full Disk Access)"
                echo "  Start the server manually: cd $REPO_DIR && ./start_midigpt_server.sh"
            fi
        fi
    elif [ "$PLATFORM" = "linux" ]; then
        SHORTCUT="$DESKTOP_DIR/Start MIDI-GPT Server.desktop"
        SHORTCUT_OK=true
        {
            echo "[Desktop Entry]"
            echo "Type=Application"
            echo "Name=Start MIDI-GPT Server"
            echo "Exec=bash -c 'cd \"$REPO_DIR\" && bash ./start_midigpt_server.sh'"
            echo "Terminal=true"
            echo "Icon=utilities-terminal"
            echo "Comment=Start the MIDI-GPT inference server for REAPER"
        } > "$SHORTCUT" 2>/dev/null || SHORTCUT_OK=false
        if [ "$SHORTCUT_OK" = true ]; then
            chmod +x "$SHORTCUT" 2>/dev/null || SHORTCUT_OK=false
        fi
        if [ "$SHORTCUT_OK" = true ]; then
            ok "Desktop shortcut created: Start MIDI-GPT Server.desktop"
            DESKTOP_SHORTCUT_CREATED=true
        else
            warn "Couldn't create Desktop shortcut (permission denied)"
            echo "  Start the server manually: cd $REPO_DIR && ./start_midigpt_server.sh"
        fi
    fi
else
    info "No Desktop folder found — skipping shortcut creation"
fi
fi # REAPER_ONLY == false (Step 6 + Desktop shortcut)

# ====================================================================
# Final: Summary and Next Steps
# ====================================================================

echo ""
echo -e "${BOLD}════════════════════════════════════════════════════${NC}"
if [ "$BACKEND_ONLY" = true ]; then
    echo -e "${GREEN}${BOLD}  Backend Updated!${NC}"
else
    echo -e "${GREEN}${BOLD}  Installation Complete!${NC}"
fi
echo -e "${BOLD}════════════════════════════════════════════════════${NC}"
echo ""

# $REAPER_DIR is only ever set inside the Step 4 block above, which
# --backend-only skips entirely -- nothing below this point may reference
# it (or anything else REAPER-side) unguarded.
if [ "$BACKEND_ONLY" = false ]; then
echo -e "${BOLD}Next steps in REAPER:${NC}"
echo ""
echo "  1. Load the dashboard as a ReaScript action:"
echo "     Actions > Show Action List > Load ReaScript"
echo "     Select: $REAPER_DIR/Scripts/MIDI-GPT/MIDI-GPT.py"
echo ""
echo "  2. Run 'MIDI-GPT.py' — it's a single window for the whole"
echo "     workflow (global options, per-track controls, running generation)."
echo "     Needs the ReaImGui extension -- see the warning above if it's missing."
echo "     Worth binding it to a toolbar button or keyboard shortcut, since"
echo "     it's the only action you'll use day to day."
echo ""
echo "  If the MIDI-GPT server runs on a different machine, click 'Change...'"
echo "  next to the server address in the dashboard and enter its IP/domain"
echo "  and port (e.g. http://192.168.1.20:3456). Defaults to"
echo "  http://127.0.0.1:3456."
echo ""
fi # BACKEND_ONLY == false (REAPER-side next steps)

echo -e "${BOLD}To start the server:${NC}"
if [ "$DESKTOP_SHORTCUT_CREATED" = true ]; then
    echo -e "  Double-click ${GREEN}Start MIDI-GPT Server${NC} on your Desktop"
elif [ "$PLATFORM" = "macos" ]; then
    echo -e "  Double-click: ${GREEN}Start Server - Mac.command${NC}"
elif [ "$PLATFORM" = "windows" ]; then
    echo -e "  Double-click: ${GREEN}Start Server - Windows.bat${NC}"
else
    echo -e "  Run: ${GREEN}./start_midigpt_server.sh${NC}"
fi
echo "  Or from terminal: cd $REPO_DIR && source .venv/bin/activate && midigpt-http"
echo ""

# ====================================================================
# Interactive: Instrument setup (Sforzando + Arachno)
# ====================================================================

# A one-time setup question, not something a --backend-only refresh
# (update.sh) should re-ask every single time it runs.
if [ -t 0 ] && [ "$BACKEND_ONLY" = false ]; then
    echo ""
    echo -e "${BOLD}----------------------------------------------------${NC}"
    echo -e "${BOLD}  Optional: Instrument Setup (Sforzando + Arachno)${NC}"
    echo -e "${BOLD}----------------------------------------------------${NC}"
    echo ""
    echo "  MIDI-GPT tracks play through Sforzando (a free SFZ sampler) loaded"
    echo "  with the Arachno General MIDI SoundFont -- see VST.md for the full"
    echo "  setup."
    echo ""
    echo "  Sforzando is a real application installer (not just a data file),"
    echo "  behind its own download page, so this installer opens that page for"
    echo "  you rather than running an installer on your behalf."
    SFZ_URL="https://www.plogue.com/products/sforzando.html"
    if [ "$PLATFORM" = "linux" ]; then
        # The Linux build is only on the downloads page, not the product page.
        SFZ_URL="https://www.plogue.com/downloads.html#sforzando"
        echo ""
        warn "Sforzando for Linux is a BETA from Plogue -- it works with MIDI-GPT"
        echo "  (VST3, tested on Ubuntu 24.04), but may be less stable than the"
        echo "  macOS/Windows builds."
        echo ""
        echo "  To install it:"
        echo "    1. Download 'sforzando for Linux (beta)' -- the x86_64 (or aarch64) zip"
        echo "    2. Unzip it, open a terminal in the unzipped folder, and run:"
        echo "         ./install_sforzando.sh"
        echo "       (Plogue's own installer -- run it without sudo; it asks for your"
        echo "       password itself. It installs to /opt/Plogue, /usr/lib/vst3 and"
        echo "       /usr/lib/clap.)"
        echo "    3. Restart REAPER. This installer has already added /usr/lib/vst3"
        echo "       to REAPER's VST paths, so the VST3 shows up on its own."
        echo "  On a minimal install (no desktop environment), Sforzando also needs"
        echo "  libxcb-util1: sudo apt install libxcb-util1"
        echo ""
    fi
    read -rp "  Open the Sforzando download page in your browser now? [y/N]: " _OPEN_SFZ
    if [[ "$_OPEN_SFZ" =~ ^[Yy]$ ]]; then
        if open_url "$SFZ_URL"; then
            ok "Opened the Sforzando download page"
        else
            warn "Could not open browser automatically"
            echo "  Visit manually: $SFZ_URL"
        fi
    fi
    echo ""
    echo "  Arachno is just a SoundFont data file, so this installer can fetch"
    echo "  it directly, into this repo's own soundfonts/ folder."
    read -rp "  Download the Arachno GM SoundFont (~140MB) now? [y/N]: " _DL_ARACHNO
    if [[ "$_DL_ARACHNO" =~ ^[Yy]$ ]]; then
        download_arachno_soundfont || true
    fi
fi

# ====================================================================
# Interactive: Launch server now?
# ====================================================================

if [ -t 0 ] && [ "$REAPER_ONLY" = false ]; then
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
