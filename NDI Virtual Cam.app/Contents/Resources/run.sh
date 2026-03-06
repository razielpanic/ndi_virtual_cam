#!/bin/bash
# Launch the NDI Virtual Camera Bridge (bundled version)
# This script bootstraps a venv, installs dependencies, and runs the app.
# It lives inside the .app bundle at Contents/Resources/run.sh.

# Resolve the directory this script lives in (Contents/Resources/)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# .venv lives in Application Support (not inside the bundle — that would
# break code signing and bloat the .app)
APP_SUPPORT="$HOME/Library/Application Support/NDI Virtual Cam"
VENV_DIR="$APP_SUPPORT/.venv"

# ---------------------------------------------------------------------------
# 1. Find Python 3.10+ (check versioned binaries first, then generic python3)
# ---------------------------------------------------------------------------
PYTHON=""
for candidate in python3.13 python3.12 python3.11 python3.10 python3; do
    if command -v "$candidate" &> /dev/null; then
        if "$candidate" -c "import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)" 2>/dev/null; then
            PYTHON="$candidate"
            break
        fi
    fi
done

if [ -z "$PYTHON" ]; then
    echo "ERROR: Python 3.10+ not found."
    echo "Install via Homebrew:"
    echo "  brew install python@3.12"
    if command -v python3 &> /dev/null; then
        CURRENT_VER="$(python3 -c "import sys; print('.'.join(map(str, sys.version_info[:3])))" 2>/dev/null)"
        [ -n "$CURRENT_VER" ] && echo "  (found python3 $CURRENT_VER, but 3.10+ is required)"
    fi
    exit 1
fi

# ---------------------------------------------------------------------------
# 2. Create virtual environment if it does not exist
# ---------------------------------------------------------------------------
if [ ! -d "$VENV_DIR" ]; then
    echo "First run — setting up Python environment..."
    mkdir -p "$APP_SUPPORT"
    "$PYTHON" -m venv "$VENV_DIR"
    if [ $? -ne 0 ]; then
        echo "ERROR: Failed to create virtual environment."
        echo "Check that python3-venv is available."
        exit 1
    fi
fi

# ---------------------------------------------------------------------------
# 3. Install or update dependencies when requirements.txt changes
# ---------------------------------------------------------------------------
MARKER="$VENV_DIR/.deps-installed"
REQS="$SCRIPT_DIR/requirements.txt"

if [ ! -f "$MARKER" ] || [ "$REQS" -nt "$MARKER" ]; then
    echo "Installing dependencies..."
    "$VENV_DIR/bin/pip" install --quiet --disable-pip-version-check -r "$REQS"
    if [ $? -ne 0 ]; then
        echo "ERROR: Failed to install dependencies."
        echo "Check your internet connection and try again."
        exit 1
    fi
    touch "$MARKER"
fi

# ---------------------------------------------------------------------------
# 4. Verify critical imports before launching the GUI
# ---------------------------------------------------------------------------
# Check tkinter separately (Homebrew requires python-tk@3.xx)
if ! "$VENV_DIR/bin/python3" -c "import tkinter" 2>/dev/null; then
    PY_VER="$("$VENV_DIR/bin/python3" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")"
    echo "ERROR: tkinter not available for Python $PY_VER."
    echo "Install via Homebrew:"
    echo "  brew install python-tk@$PY_VER"
    exit 1
fi

# Check project dependencies
if ! "$VENV_DIR/bin/python3" -c "import cyndilib, pyvirtualcam, PIL, numpy" 2>/dev/null; then
    echo "ERROR: Dependencies installed but imports failed."
    echo "Try removing the environment and relaunching:"
    echo "  rm -rf \"$VENV_DIR\""
    exit 1
fi

# ---------------------------------------------------------------------------
# 5. Launch the application
# ---------------------------------------------------------------------------
# Create a named symlink so macOS shows "NDI Virtual Cam" in the menu bar
# instead of "python3" (macOS reads the executable basename for the app menu)
NAMED="$VENV_DIR/bin/NDI Virtual Cam"
[ -L "$NAMED" ] || ln -sf python3 "$NAMED"
exec "$NAMED" "$SCRIPT_DIR/src/ndi_to_vcam.py" "$@"
