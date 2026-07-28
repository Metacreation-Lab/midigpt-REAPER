#!/usr/bin/env bash
# ============================================================================
# MIDI-GPT for REAPER - Windows Bash Installer
#
# Installs everything needed to run MIDI-GPT on Windows from Git Bash / MSYS:
#   1. System dependencies (git, python, uv)
#   2. Python virtual environment + torch
#   3. REAPER integration (junctions for Scripts + Effects)
#   4. REAPER Python/ReaScript configuration
#   5. Verification
# ============================================================================

set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="$REPO_DIR/.venv"
UV_CMD="uv"
PYTHON_SPEC="3.12"
SKIP_DEPS=false
SKIP_REAPER_CONFIG=false
REAPER_DIR_OVERRIDE=""

# Target MIDI-GPT source repo path. Auto-detected at the sibling path ../MIDI-GPT.
MIDIGPT_SRC=""
if [ -d "$REPO_DIR/../MIDI-GPT" ]; then
    MIDIGPT_SRC="$(cd "$REPO_DIR/../MIDI-GPT" && pwd)"
fi

info() { printf '[INFO] %s\n' "$*"; }
ok() { printf '[OK] %s\n' "$*"; }
warn() { printf '[WARN] %s\n' "$*" >&2; }
fail() { printf '[ERROR] %s\n' "$*" >&2; exit 1; }

step() {
    echo ""
    printf '%s\n' "----------------------------------------------------"
    printf '  %s\n' "$*"
    printf '%s\n' "----------------------------------------------------"
}

show_help() {
    cat <<'EOF'
MIDI-GPT for REAPER - Windows Bash Installer

Usage: ./install-windows.sh [OPTIONS]

Options:
  --skip-deps             Skip system dependency check
  --skip-reaper-config    Skip automatic REAPER Python/ReaScript configuration
  --reaper-dir=PATH       REAPER resource directory (required for portable installs)
  --midigpt-src=PATH      Path to the MIDI-GPT source repository (sibling folder by default)
  --help, -h              Show this help
EOF
}

check_cmd() {
    command -v "$1" >/dev/null 2>&1
}

to_posix_path() {
    local input_path="$1"
    if check_cmd cygpath; then
        cygpath -au "$input_path"
    else
        printf '%s\n' "$input_path" | tr '\\' '/'
    fi
}

resolve_reaper_dir() {
    if [ -n "$REAPER_DIR_OVERRIDE" ]; then
        REAPER_DIR="$(to_posix_path "$REAPER_DIR_OVERRIDE")"
    else
        REAPER_DIR="${APPDATA:-$USERPROFILE/AppData/Roaming}/REAPER"
    fi
}

uv_pip_install() {
    "$UV_CMD" pip install --python "$VENV_PYTHON" "$@"
}

venv_python() {
    "$VENV_PYTHON" "$@"
}

ensure_windows_shell() {
    case "$(uname -s)" in
        MINGW*|MSYS*) return 0 ;;
        *) fail "This installer script must be run under Git Bash or MSYS on Windows. On macOS/Linux, use ./install.sh." ;;
    esac
}

# ── Args ────────────────────────────────────────────────────────

for arg in "$@"; do
    case "$arg" in
        --skip-deps) SKIP_DEPS=true ;;
        --skip-reaper-config) SKIP_REAPER_CONFIG=true ;;
        --reaper-dir=*) REAPER_DIR_OVERRIDE="${arg#*=}" ;;
        --midigpt-src=*) MIDIGPT_SRC="${arg#*=}" ;;
        --help|-h)
            show_help
            exit 0
            ;;
        *)
            fail "Unknown option: $arg"
            ;;
    esac
done

to_windows_path() {
    local input_path="$1"
    if check_cmd cygpath; then
        cygpath -aw "$input_path"
    else
        printf '%s\n' "$input_path"
    fi
}

activate_venv() {
    # shellcheck disable=SC1091
    source "$VENV_DIR/Scripts/activate"
}

find_protobuf() {
    PROTOC_PATH=""
    PROTOBUF_ROOT=""
    PROTOBUF_INCLUDE_DIR=""
    PROTOBUF_LIBRARY=""
    PROTOBUF_SOURCE=""

    local protoc_cmd="" root="" lib_candidate=""
    for candidate in protoc protoc.exe; do
        if check_cmd "$candidate"; then
            protoc_cmd="$(command -v "$candidate")"
            break
        fi
    done

    if [ -n "$protoc_cmd" ]; then
        root="$(cd "$(dirname "$protoc_cmd")/.." && pwd 2>/dev/null || true)"
        if [ -n "$root" ]; then
            if [ -d "$root/include" ]; then
                PROTOBUF_INCLUDE_DIR="$(to_cmake_path "$root/include")"
            fi

            for lib_candidate in \
                "$root/lib/libprotobuf.lib" \
                "$root/lib64/libprotobuf.lib" \
                "$root/lib/protobuf.lib" \
                "$root/lib64/protobuf.lib"
            do
                if [ -f "$lib_candidate" ]; then
                    PROTOBUF_LIBRARY="$(to_cmake_path "$lib_candidate")"
                    break
                fi
            done

            if [ -z "$PROTOBUF_LIBRARY" ]; then
                lib_candidate="$(find "$root" -type f \( -iname 'libprotobuf.lib' -o -iname 'protobuf.lib' \) 2>/dev/null | head -1)"
                if [ -n "$lib_candidate" ] && [ -f "$lib_candidate" ]; then
                    PROTOBUF_LIBRARY="$(to_cmake_path "$lib_candidate")"
                fi
            fi

            PROTOC_PATH="$(to_cmake_path "$protoc_cmd")"
            PROTOBUF_ROOT="$(to_cmake_path "$root")"

            if [ -n "$PROTOBUF_INCLUDE_DIR" ] && [ -n "$PROTOBUF_LIBRARY" ]; then
                PROTOBUF_SOURCE="system"
                return 0
            fi
        fi
    fi

    if find_vcpkg && [ -d "$VCPKG_ROOT_RESOLVED/installed/$VCPKG_TRIPLET/include" ]; then
        root="$VCPKG_ROOT_RESOLVED/installed/$VCPKG_TRIPLET"
        if [ -f "$root/lib/libprotobuf.lib" ]; then
            PROTOBUF_ROOT="$(to_cmake_path "$root")"
            PROTOBUF_INCLUDE_DIR="$(to_cmake_path "$root/include")"
            PROTOBUF_LIBRARY="$(to_cmake_path "$root/lib/libprotobuf.lib")"
            if [ -f "$root/tools/protobuf/protoc.exe" ]; then
                PROTOC_PATH="$(to_cmake_path "$root/tools/protobuf/protoc.exe")"
            fi
            PROTOBUF_SOURCE="vcpkg"
            return 0
        fi
    fi

    return 1
}

find_vcpkg() {
    VCPKG_ROOT_RESOLVED=""
    VCPKG_TOOLCHAIN_FILE=""

    local vcpkg_cmd=""

    if [ -n "${VCPKG_ROOT:-}" ] && [ -f "${VCPKG_ROOT}/scripts/buildsystems/vcpkg.cmake" ]; then
        VCPKG_ROOT_RESOLVED="${VCPKG_ROOT}"
    else
        for candidate in vcpkg vcpkg.exe; do
            if check_cmd "$candidate"; then
                vcpkg_cmd="$(command -v "$candidate")"
                break
            fi
        done

        if [ -n "$vcpkg_cmd" ]; then
            VCPKG_ROOT_RESOLVED="$(cd "$(dirname "$vcpkg_cmd")/.." && pwd 2>/dev/null || true)"
        fi
    fi

    if [ -n "$VCPKG_ROOT_RESOLVED" ] && [ -f "$VCPKG_ROOT_RESOLVED/scripts/buildsystems/vcpkg.cmake" ]; then
        VCPKG_ROOT_RESOLVED="$(to_cmake_path "$VCPKG_ROOT_RESOLVED")"
        VCPKG_TOOLCHAIN_FILE="$VCPKG_ROOT_RESOLVED/scripts/buildsystems/vcpkg.cmake"
        return 0
    fi

    return 1
}

bootstrap_vcpkg() {
    local vcpkg_root=""
    local vcpkg_root_win=""
    local bootstrap_bat_win=""

    check_cmd git || fail "git is required to bootstrap vcpkg"

    vcpkg_root="$(get_default_vcpkg_root)"

    if [ ! -d "$vcpkg_root/.git" ]; then
        info "Cloning vcpkg into $vcpkg_root..."
        git clone https://github.com/microsoft/vcpkg.git "$vcpkg_root" || fail "Failed to clone vcpkg"
    else
        info "Existing vcpkg clone found at $vcpkg_root"
    fi

    vcpkg_root_win="$(to_windows_path "$vcpkg_root")"
    bootstrap_bat_win="$(to_windows_path "$vcpkg_root/bootstrap-vcpkg.bat")"
    info "Bootstrapping vcpkg..."
    cmd.exe //c call "$bootstrap_bat_win" -disableMetrics || fail "Failed to bootstrap vcpkg"

    export VCPKG_ROOT="$vcpkg_root"
    find_vcpkg || fail "vcpkg bootstrap completed but vcpkg could not be located"
    ok "vcpkg ready at $VCPKG_ROOT_RESOLVED"
}

make_reaper_junction() {
    local src="$1"
    local dst="$2"
    local dst_parent dst_win src_win dst_win

    [ -d "$src" ] || return 0

    dst_parent="$(dirname "$dst")"
    mkdir -p "$dst_parent"

    if [ -e "$dst" ] || [ -L "$dst" ]; then
        cmd.exe //c rmdir "$(to_windows_path "$dst")" >/dev/null 2>&1 || true
        rm -rf "$dst" >/dev/null 2>&1 || true
    fi

    src_win="$(to_windows_path "$src")"
    dst_win="$(to_windows_path "$dst")"
    cmd.exe //c mklink //J "$dst_win" "$src_win" >/dev/null || fail "Could not create junction: $dst"
}

set_reaper_ini_value() {
    local ini_path="$1"
    local key="$2"
    local value="$3"

    "$VENV_PYTHON" - "$ini_path" "$key" "$value" <<'PY'
import pathlib
import re
import sys

ini_path = pathlib.Path(sys.argv[1])
key = sys.argv[2]
value = sys.argv[3]
text = ini_path.read_text(encoding="utf-8", errors="ignore")
pattern = re.compile(rf"(?m)^{re.escape(key)}=.*$")
if pattern.search(text):
    text = pattern.sub(lambda _m: f"{key}={value}", text)
else:
    marker = "[REAPER]"
    if marker in text:
        text = text.replace(marker, f"{marker}\n{key}={value}", 1)
    else:
        text += f"\n[REAPER]\n{key}={value}\n"
ini_path.write_text(text, encoding="utf-8", newline="")
PY
}

reaper_running() {
    tasklist.exe //FI "IMAGENAME eq reaper.exe" 2>/dev/null | tr -d '\r' | grep -qi "reaper.exe"
}

create_desktop_launcher() {
    local desktop_dir shortcut_path repo_win server_win

    desktop_dir="${USERPROFILE:-}/Desktop"
    [ -d "$desktop_dir" ] || return 0

    shortcut_path="$desktop_dir/Start MIDI-GPT Server.cmd"
    repo_win="$(to_windows_path "$REPO_DIR")"
    server_win="$(to_windows_path "$REPO_DIR/Start Server - Windows.bat")"

    printf '%s\r\n' \
        '@echo off' \
        "cd /d \"$repo_win\"" \
        "call \"$server_win\"" > "$shortcut_path"

    ok "Desktop launcher created: Start MIDI-GPT Server.cmd"
}

for arg in "$@"; do
    case "$arg" in
        --skip-deps) SKIP_DEPS=true ;;
        --skip-reaper-config) SKIP_REAPER_CONFIG=true ;;
        --reaper-dir=*) REAPER_DIR_OVERRIDE="${arg#*=}" ;;
        --mmm-wheel=*) MMM_WHEEL_LOCAL="${arg#*=}" ;;
        --mmm-zip=*) MMM_ZIP_LOCAL="${arg#*=}" ;;
        --help|-h)
            show_help
            exit 0
            ;;
        *)
            fail "Unknown option: $arg"
            ;;
    esac
done

ensure_windows_shell

echo ""
echo "  ======================================"
echo "      MIDI-GPT for REAPER Installer"
echo "  ======================================"
echo ""
info "Platform: Windows (bash)"

if [ "$SKIP_DEPS" = false ]; then
    step "Step 1/6: Checking system dependencies"

    MISSING=()

    if check_cmd "$UV_CMD"; then
        ok "uv found"
    else
        MISSING+=("uv")
        warn "uv not found"
    fi

    if check_cmd git; then
        ok "git found"
    else
        MISSING+=("git")
        warn "git not found"
    fi

    if [ "${#MISSING[@]}" -gt 0 ]; then
        echo ""
        warn "Missing dependencies: ${MISSING[*]}"
        echo ""

        INSTALLER=""
        if check_cmd winget; then
            INSTALLER="winget"
        elif check_cmd choco; then
            INSTALLER="choco"
        fi

        if [ -n "$INSTALLER" ]; then
            info "Installing via $INSTALLER..."
            for dep in "${MISSING[@]}"; do
                case "$dep" in
                    "uv")
                        if [ "$INSTALLER" = "winget" ]; then
                            winget install --id=astral-sh.uv -e --accept-package-agreements --accept-source-agreements
                        else
                            choco install uv -y
                        fi
                        ;;
                    "git")
                        if [ "$INSTALLER" = "winget" ]; then
                            winget install Git.Git --accept-package-agreements --accept-source-agreements
                        else
                            choco install git -y
                        fi
                        ;;
                esac
            done
        else
            echo "Please install the missing dependencies manually, then re-run:"
            echo "  winget install --id=astral-sh.uv -e"
            echo "  winget install Git.Git"
            fail "Missing dependencies"
        fi
    fi

    check_cmd "$UV_CMD" || fail "uv is required but not found"
    hash -r
    ok "All system dependencies satisfied"
else
    step "Step 1/6: Skipping dependency check (--skip-deps)"
    check_cmd "$UV_CMD" || fail "uv is required but not found"
fi

step "Step 2/6: Setting up Python virtual environment"

info "Ensuring uv-managed Python $PYTHON_SPEC is available..."
"$UV_CMD" python install "$PYTHON_SPEC"

if [ -d "$VENV_DIR" ]; then
    info "Existing venv found at $VENV_DIR"
    activate_venv
    VENV_PYTHON="$VENV_DIR/Scripts/python.exe"
    ok "Activated existing venv"
else
    info "Creating venv with uv-managed Python $PYTHON_SPEC..."
    "$UV_CMD" venv --python "$PYTHON_SPEC" "$VENV_DIR"
    activate_venv
    VENV_PYTHON="$VENV_DIR/Scripts/python.exe"
    uv_pip_install --upgrade pip setuptools wheel >/dev/null
    ok "Created and activated venv at $VENV_DIR"
fi

[ -f "$VENV_PYTHON" ] || fail "Venv python not found at $VENV_PYTHON"

info "Checking PyTorch..."
if venv_python -c "import torch" 2>/dev/null; then
    TORCH_VER="$(venv_python -c 'import torch; print(torch.__version__)')"
    ok "PyTorch $TORCH_VER already installed"
else
    info "Installing PyTorch (this may take a few minutes)..."
    uv_pip_install torch torchvision
    TORCH_VER="$(venv_python -c 'import torch; print(torch.__version__)')"
    ok "PyTorch $TORCH_VER installed"
fi

info "Installing build dependencies..."
uv_pip_install scikit-build-core pybind11 >/dev/null
ok "Build dependencies ready"

resolve_reaper_dir
if [ -n "$REAPER_DIR_OVERRIDE" ]; then
    info "Using user-specified REAPER resource dir: $REAPER_DIR"
else
    info "Using default REAPER resource dir: $REAPER_DIR"
    info "If you use a portable REAPER install, re-run with --reaper-dir=/path/to/REAPER-resource-dir"
fi

step "Step 3/6: Installing MIDI-GPT backend"

# Try to find MIDI-GPT in sibling directory
MIDIGPT_SIBLING="$REPO_DIR/../MIDI-GPT"
MIDIGPT_SRC_WIN=""

if [ -n "$MIDIGPT_SRC" ] && [ -d "$MIDIGPT_SRC" ]; then
    MIDIGPT_SRC_WIN="$MIDIGPT_SRC"
elif [ -d "$MIDIGPT_SIBLING" ]; then
    MIDIGPT_SRC_WIN="$MIDIGPT_SIBLING"
fi

if [ -n "$MIDIGPT_SRC_WIN" ]; then
    info "Installing midigpt[http,inference] from $MIDIGPT_SRC_WIN ..."
    "$UV_CMD" pip install --python "$VENV_PYTHON" -e "${MIDIGPT_SRC_WIN}[http,inference]"
else
    info "Installing midigpt[http,inference] from PyPI ..."
    if ! "$UV_CMD" pip install --python "$VENV_PYTHON" "midigpt[http,inference]"; then
        warn "PyPI install failed — falling back to cloning MIDI-GPT from GitHub ..."
        MIDIGPT_CLONE="$(cd "$REPO_DIR/.." && pwd)/MIDI-GPT"
        if [ ! -d "$MIDIGPT_CLONE/.git" ]; then
            git clone https://github.com/Metacreation-Lab/MIDI-GPT.git "$MIDIGPT_CLONE" \
                || fail "Failed to clone MIDI-GPT. Check your internet connection and try again."
        else
            info "Existing MIDI-GPT clone found at $MIDIGPT_CLONE"
        fi
        "$UV_CMD" pip install --python "$VENV_PYTHON" -e "${MIDIGPT_CLONE}[http,inference]" \
            || fail "Source install from cloned MIDI-GPT also failed."
    fi
fi

if venv_python -c "from midigpt.inference.engine import InferenceEngine" >/dev/null 2>&1; then
    ok "MIDI-GPT backend installed successfully"
else
    fail "MIDI-GPT backend installation failed."
fi

info "Installing plugin dependencies..."
uv_pip_install -e "$REPO_DIR" >/dev/null 2>&1 || uv_pip_install -e "$REPO_DIR"
ok "Plugin dependencies installed"

step "Step 4/6: Setting up REAPER integration"

SCRIPTS_SRC="$REPO_DIR/src/Scripts/MIDI-GPT"
EFFECTS_SRC="$REPO_DIR/src/Effects/MIDI-GPT"
SCRIPTS_DST="$REAPER_DIR/Scripts/MIDI-GPT"
EFFECTS_DST="$REAPER_DIR/Effects/MIDI-GPT"

if [ -d "$REAPER_DIR" ]; then
    make_reaper_junction "$SCRIPTS_SRC" "$SCRIPTS_DST"
    make_reaper_junction "$EFFECTS_SRC" "$EFFECTS_DST"
    ok "REAPER junctions created"
else
    warn "REAPER config directory not found - REAPER may not be installed yet"
fi

if [ "$SKIP_REAPER_CONFIG" = true ]; then
    step "Step 5/6: Skipping REAPER config (--skip-reaper-config)"
else
    step "Step 5/6: Configuring REAPER (reaper.ini)"

    REAPER_INI="$REAPER_DIR/reaper.ini"
    PYTHON_DLL_PATH="$(venv_python -c 'import pathlib, sys; base = pathlib.Path(sys.base_exec_prefix); dll = next(base.glob(f"python{sys.version_info.major}{sys.version_info.minor}.dll"), None); print(dll or "")' 2>/dev/null)"

    if [ -f "$REAPER_INI" ]; then
        if reaper_running; then
            warn "REAPER is currently running"
            echo "Please quit REAPER and re-run this installer, or configure ReaScript manually."
            [ -n "$PYTHON_DLL_PATH" ] && echo "Python library: $PYTHON_DLL_PATH"
        elif [ -n "$PYTHON_DLL_PATH" ] && [ -f "$PYTHON_DLL_PATH" ]; then
            cp "$REAPER_INI" "$REAPER_INI.midigpt-backup"
            info "Backed up reaper.ini"

            set_reaper_ini_value "$REAPER_INI" "reascript" "1"
            set_reaper_ini_value "$REAPER_INI" "pythonlibdll64" "$PYTHON_DLL_PATH"

            ok "ReaScript enabled (reascript=1)"
            ok "Python library: $PYTHON_DLL_PATH"
        else
            warn "Could not detect Python DLL path"
            echo "Configure manually in REAPER: Options > Preferences > Plug-Ins > ReaScript"
        fi
    else
        if [ -d "$REAPER_DIR" ]; then
            warn "reaper.ini not found - launch REAPER once, quit it, then re-run this installer"
        else
            warn "REAPER config directory not found - REAPER may not be installed"
        fi
        [ -n "$PYTHON_DLL_PATH" ] && echo "When ready, set the Python library path to: $PYTHON_DLL_PATH"
    fi
fi

step "Step 6/6: Verifying backend installation"

if venv_python -c "from midigpt.inference.engine import InferenceEngine" >/dev/null 2>&1; then
    ok "Verification successful: midigpt is installed and functional"
else
    fail "Verification failed: midigpt could not be imported"
fi

create_desktop_launcher

echo ""
echo "===================================================="
echo "  Installation Complete!"
echo "===================================================="
echo ""
echo "Next steps in REAPER:"
echo "  1. Actions > Show Action List > Load ReaScript"
echo "  2. Select: $REAPER_DIR/Scripts/MIDI-GPT/REAPER_midigpt_infill.py"
echo "  3. In the FX browser, search for 'MIDI-GPT'"
echo "  4. Add 'MIDI-GPT Global Options' to Monitor FX"
echo "  5. Add 'MIDI-GPT Track Options (Yellow)', '(Prism)', or '(Expressive)' to tracks"
echo ""
echo "To start the server:"
echo "  Double-click Start MIDI-GPT Server.cmd on your Desktop"
echo "  or run Start Server - Windows.bat from the repo root"

