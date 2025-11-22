#!/usr/bin/env bash
#
# Build the ticket-processor package using Flox
#
# This script builds the Nix package defined in .flox/pkgs/ticket-processor.nix
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

cd "$PROJECT_ROOT"

echo "═══════════════════════════════════════════════════════════════"
echo "Building ticket-processor package"
echo "═══════════════════════════════════════════════════════════════"
echo ""

# Check if .flox directory exists
if [ ! -d ".flox" ]; then
    echo "❌ Error: .flox directory not found"
    echo "   Make sure you're in the project root with a Flox environment"
    exit 1
fi

# Check if Nix expression exists
if [ ! -f ".flox/pkgs/ticket-processor.nix" ]; then
    echo "❌ Error: .flox/pkgs/ticket-processor.nix not found"
    exit 1
fi

echo "📦 Package: ticket-processor"
echo "📂 Nix expression: .flox/pkgs/ticket-processor.nix"
echo ""

# Build the package
echo "🔨 Building package..."
echo ""

if flox build .#ticket-processor; then
    echo ""
    echo "═══════════════════════════════════════════════════════════════"
    echo "✅ Build successful!"
    echo "═══════════════════════════════════════════════════════════════"
    echo ""
    echo "The package has been built and cached."
    echo ""
    echo "To use the package:"
    echo "  1. Add to manifest: ticket-processor.pkg-path = \"ticket-processor\""
    echo "  2. Run: flox activate"
    echo "  3. Execute: ticket-processor"
    echo ""
else
    echo ""
    echo "═══════════════════════════════════════════════════════════════"
    echo "❌ Build failed!"
    echo "═══════════════════════════════════════════════════════════════"
    echo ""
    echo "Check the error messages above for details."
    exit 1
fi
