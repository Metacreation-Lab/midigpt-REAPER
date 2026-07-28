#!/usr/bin/env bash
# ============================================================================
# Build a distributable MIDI-GPT for REAPER release package
#
# Creates a single zip file containing everything a user needs:
#   - midigpt-REAPER source (scripts, effects, installers, launchers)
#
# Usage:
#   ./build_release.sh                                    # Uses defaults
#   ./build_release.sh --output=release.zip               # Custom output name
# ============================================================================

set -euo pipefail

# ── Config ──────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
OUTPUT=""
VERSION="$(date +%Y%m%d)"

# ── Colors ──────────────────────────────────────────────────────
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
BOLD='\033[1m'
NC='\033[0m'

info()  { echo -e "${BLUE}[INFO]${NC} $*"; }
ok()    { echo -e "${GREEN}[OK]${NC} $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $*"; }
fail()  { echo -e "\033[0;31m[ERROR]\033[0m $*"; exit 1; }

# ── Args ────────────────────────────────────────────────────────

for arg in "$@"; do
    case "$arg" in
        --output=*)   OUTPUT="${arg#*=}" ;;
        --help|-h)
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "  --output=PATH    Output zip path (default: MIDI-GPT-for-REAPER-YYYYMMDD.zip)"
            echo "  --help           Show this help"
            exit 0
            ;;
        *) warn "Unknown option: $arg" ;;
    esac
done

if [ -z "$OUTPUT" ]; then
    OUTPUT="${SCRIPT_DIR}/MIDI-GPT-for-REAPER-${VERSION}.zip"
fi

echo -e "${BOLD}"
echo "  ╔═══════════════════════════════════════════╗"
echo "  ║   MIDI-GPT for REAPER — Release Builder   ║"
echo "  ╚═══════════════════════════════════════════╝"
echo -e "${NC}"

# ── Build staging directory ─────────────────────────────────────

STAGING="$(mktemp -d /tmp/midigpt-release.XXXXXX)"
RELEASE_DIR="$STAGING/MIDI-GPT-for-REAPER"
mkdir -p "$RELEASE_DIR"

info "Staging directory: $STAGING"

# ── 1. Copy midigpt-REAPER source ──────────────────────────────

info "Copying midigpt-REAPER source..."

# ── Installers & launchers (root level) ──
for f in \
    "install.sh" \
    "install-windows.sh" \
    "install.ps1" \
    "Install - Mac.command" \
    "Install - Linux.sh" \
    "Install - Windows.bat" \
    "start_midigpt_server.sh" \
    "Start Server - Mac.command" \
    "Start Server - Windows.bat" \
    "VST.md" \
    "INSTRUMENTS.md" \
    ; do
    [ -f "$SCRIPT_DIR/$f" ] && cp "$SCRIPT_DIR/$f" "$RELEASE_DIR/$f"
done

# ── Documentation ──
cp "$SCRIPT_DIR/README.md" "$RELEASE_DIR/"
mkdir -p "$RELEASE_DIR/docs"
cp "$SCRIPT_DIR/docs/index.html" "$RELEASE_DIR/docs/"

# ── Python package metadata ──
cp "$SCRIPT_DIR/pyproject.toml" "$RELEASE_DIR/"

# ── Setup script (creates REAPER symlinks) ──
mkdir -p "$RELEASE_DIR/scripts"
cp "$SCRIPT_DIR/scripts/setup.py" "$RELEASE_DIR/scripts/"

# ── Source: Scripts (REAPER script, extraction) ──
mkdir -p "$RELEASE_DIR/src/Scripts/MIDI-GPT"
for f in REAPER_midigpt_infill.py midi_extraction.py; do
    cp "$SCRIPT_DIR/src/Scripts/MIDI-GPT/$f" "$RELEASE_DIR/src/Scripts/MIDI-GPT/$f"
done

# ── Source: Effects (JSFX) ──
mkdir -p "$RELEASE_DIR/src/Effects/MIDI-GPT"
for f in "MIDI-GPT Global Options.js" "MIDI-GPT Track Options (Yellow).js" "MIDI-GPT Track Options (Prism).js" "MIDI-GPT Track Options (Expressive).js"; do
    cp "$SCRIPT_DIR/src/Effects/MIDI-GPT/$f" "$RELEASE_DIR/src/Effects/MIDI-GPT/$f"
done

ok "Source copied"

# ── 1b. Rebuild docs/index.html with embedded README ───────────────────

info "Embedding README.md into docs/index.html..."
python3 -c "
import pathlib, re

root = pathlib.Path('$RELEASE_DIR')
readme = (root / 'README.md').read_text()
readme_safe = readme.replace('</script>', '<\\\\/script>')

html_path = root / 'docs' / 'index.html'
html = html_path.read_text()

script_re = re.compile(
    r'(<script id=\"readme-source\" type=\"text/plain\">)\n.*?\n(</script>)',
    re.DOTALL,
)
if script_re.search(html):
    html = script_re.sub(lambda m: f'{m.group(1)}\n{readme_safe}\n{m.group(2)}', html)
    html_path.write_text(html)
    print(f'docs/index.html updated ({len(readme)} chars)')
else:
    print('WARNING: could not find readme-source tag in docs/index.html')
"
ok "docs/index.html updated"

# ── 2. Create final release zip ────────────────────────────────

info "Creating release archive..."
rm -f "$OUTPUT"
(cd "$STAGING" && zip -r -q "$OUTPUT" "MIDI-GPT-for-REAPER/")

# ── Cleanup ─────────────────────────────────────────────────────

rm -rf "$STAGING"

# ── Summary ─────────────────────────────────────────────────────

RELEASE_SIZE="$(du -sh "$OUTPUT" | awk '{print $1}')"

echo ""
echo -e "${BOLD}════════════════════════════════════════════════════${NC}"
echo -e "${GREEN}${BOLD}  Release package created!${NC}"
echo -e "${BOLD}════════════════════════════════════════════════════${NC}"
echo ""
echo "  File: $OUTPUT"
echo "  Size: $RELEASE_SIZE"
echo ""
echo "  Contents:"
echo "    - midigpt-REAPER client scripts & JSFX"
echo "    - Installers & launchers"
echo ""
echo "  Users extract the zip and double-click the installer for their OS."
echo ""
