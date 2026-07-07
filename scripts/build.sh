#!/usr/bin/env bash
# Build script for Linux / macOS
# Usage:  ./scripts/build.sh
#
# Prerequisites:
#   - Python 3.10+ with venv support
#   - (macOS only) Xcode Command Line Tools for code signing
#
# Output:  dist/CraftCloud  (Linux)  or  dist/CraftCloud.app  (macOS)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_DIR"

# ── Detect OS ───────────────────────────────────────────────────
case "$(uname -s)" in
    Linux*)  OS=linux   ;;
    Darwin*) OS=macos   ;;
    *)       echo "Unsupported OS: $(uname -s)" >&2; exit 1 ;;
esac
echo "==> Building for $OS"

# ── Python virtual environment ──────────────────────────────────
VENV_DIR="$PROJECT_DIR/.venv"
if [ ! -d "$VENV_DIR" ]; then
    echo "==> Creating virtual environment..."
    python3 -m venv "$VENV_DIR"
fi

# Activate (source-based, works on both Linux and macOS)
source "$VENV_DIR/bin/activate"

# ── Install / update dependencies ───────────────────────────────
echo "==> Installing dependencies..."
pip install -q --upgrade pip
pip install -q -r requirements.txt
pip install -q pyinstaller

# ── Platform-specific setup ─────────────────────────────────────
if [ "$OS" = macos ]; then
    # Ensure .icns icon exists (convert from PNG if needed)
    if [ ! -f resources/cc.icns ] && [ -f resources/cc512.png ]; then
        echo "==> Generating cc.icns from cc512.png..."
        mkdir -p /tmp/cc.iconset
        sips -z 16 16   resources/cc512.png --out /tmp/cc.iconset/icon_16x16.png      2>/dev/null || true
        sips -z 32 32   resources/cc512.png --out /tmp/cc.iconset/icon_16x16@2x.png   2>/dev/null || true
        sips -z 32 32   resources/cc512.png --out /tmp/cc.iconset/icon_32x32.png      2>/dev/null || true
        sips -z 64 64   resources/cc512.png --out /tmp/cc.iconset/icon_32x32@2x.png   2>/dev/null || true
        sips -z 128 128 resources/cc512.png --out /tmp/cc.iconset/icon_128x128.png    2>/dev/null || true
        sips -z 256 256 resources/cc512.png --out /tmp/cc.iconset/icon_128x128@2x.png 2>/dev/null || true
        sips -z 256 256 resources/cc512.png --out /tmp/cc.iconset/icon_256x256.png    2>/dev/null || true
        sips -z 512 512 resources/cc512.png --out /tmp/cc.iconset/icon_256x256@2x.png 2>/dev/null || true
        sips -z 512 512 resources/cc512.png --out /tmp/cc.iconset/icon_512x512.png    2>/dev/null || true
        iconutil -c icns /tmp/cc.iconset -o resources/cc.icns 2>/dev/null || {
            echo "==> WARNING: iconutil failed, using PNG fallback"
            cp resources/cc512.png resources/cc.icns
        }
        rm -rf /tmp/cc.iconset
    fi

    # ── ffmpeg (macOS) ────────────────────────────────────────
    if [ ! -f scripts/ffmpeg ]; then
        echo "==> Downloading ffmpeg..."
        curl -sL "https://evermeet.cx/ffmpeg/getrelease/zip" -o /tmp/ffmpeg.zip
        unzip -q /tmp/ffmpeg.zip -d scripts/
        rm /tmp/ffmpeg.zip
    fi
elif [ "$OS" = linux ]; then
    # ── ffmpeg (Linux) ────────────────────────────────────────
    if [ ! -f scripts/ffmpeg ]; then
        echo "==> Downloading ffmpeg..."
        curl -sL "https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz" -o /tmp/ffmpeg.tar.xz
        tar xf /tmp/ffmpeg.tar.xz -C /tmp
        cp /tmp/ffmpeg-*-amd64-static/ffmpeg scripts/ffmpeg
        rm -rf /tmp/ffmpeg.tar.xz /tmp/ffmpeg-*-amd64-static
    fi
fi

# ── Clean previous build ────────────────────────────────────────
echo "==> Cleaning previous build..."
rm -rf build dist

# ── Run PyInstaller ─────────────────────────────────────────────
echo "==> Running PyInstaller..."
pyinstaller --clean --noconfirm CraftCloud.spec

# ── Post-build ──────────────────────────────────────────────────
if [ "$OS" = macos ]; then
    TARGET="dist/CraftCloud.app"
    echo "==> macOS .app bundle:  $TARGET"
    # Remove quarantine attribute (if downloaded/transferred)
    xattr -cr "$TARGET" 2>/dev/null || true
elif [ "$OS" = linux ]; then
    TARGET="dist/CraftCloud"
    echo "==> Linux executable:  $TARGET"
    # Make executable
    chmod +x "$TARGET/CraftCloud" 2>/dev/null || true
fi

echo ""
echo "========================================"
echo "  Build complete: $TARGET"
echo "========================================"
