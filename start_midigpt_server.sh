#!/usr/bin/env bash
# ============================================================================
# MIDI-GPT HTTP Server Launcher (macOS / Linux)
#
# Starts the stateless FastAPI HTTP server for REAPER generation.
# By default, runs the yellow_medium model on port 3456.
#
# Usage:
#   ./start_midigpt_server.sh                                    # yellow_medium (default)
#   ./start_midigpt_server.sh --pretrained prism_medium          # Prism model
#   ./start_midigpt_server.sh --pretrained expressive_medium     # Expressive model
#   ./start_midigpt_server.sh --ckpt path/to/model.safetensors   # Local checkpoint
# ============================================================================

# cd to the directory containing this script
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR" || exit 1

# Activate the virtual environment
if [ -f ".venv/bin/activate" ]; then
    source .venv/bin/activate
else
    echo "ERROR: Virtual environment not found at .venv/"
    echo "Please run the installer first."
    echo ""
    read -rp "Press Enter to close..."
    exit 1
fi

echo ""
echo "  ╔══════════════════════════════════════╗"
echo "  ║      MIDI-GPT Server Starting...     ║"
echo "  ╚══════════════════════════════════════╝"
echo ""
echo "  Keep this window open while using MIDI-GPT in REAPER."
echo "  Press Ctrl+C to stop the server."
echo ""

# Default parameters: run 'yellow' model on port 3456 if no arguments are provided.
# If arguments are passed (e.g. --pretrained prism_medium or --ckpt ...), forward them.
if [ $# -eq 0 ]; then
    midigpt-http --pretrained yellow_medium --port 3456
else
    midigpt-http --port 3456 "$@"
fi
status=$?

# Keep window open on error
echo ""
echo "Server stopped."
# 130 = Ctrl+C. Anything else at startup is most often the model download:
# the checkpoints on Hugging Face need an account that accepted the license.
if [ $status -ne 0 ] && [ $status -ne 130 ]; then
    echo ""
    echo "If the message above mentions a gated repo, 401 or 403: accept the license at"
    echo "https://huggingface.co/Metacreation/MIDI-GPT, then save a token with:"
    echo "  $SCRIPT_DIR/.venv/bin/hf auth login"
fi
read -rp "Press Enter to close..."
