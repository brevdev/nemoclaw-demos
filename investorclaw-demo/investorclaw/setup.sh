#!/bin/bash
# InvestorClaw Installation Script (Shell Wrapper)
#
# Detects OpenClaw, patches configuration, registers skill
#
# Usage:
#   ./skill/setup.sh              # Install
#   ./skill/setup.sh --rollback   # Uninstall
#   ./skill/setup.sh --dry-run    # Dry-run (no changes)

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}"
echo "═══════════════════════════════════════════════════════════════════"
echo "InvestorClaw Installation"
echo "═══════════════════════════════════════════════════════════════════"
echo -e "${NC}"

# Check Python
if ! command -v python3 &> /dev/null; then
    echo -e "${RED}❌ Python 3 not found${NC}"
    exit 1
fi

echo -e "${GREEN}✅ Python found: $(python3 --version)${NC}"
echo ""

# Run installer
python3 "$SCRIPT_DIR/installer.py" "$@"
exit_code=$?

if [ $exit_code -eq 0 ]; then
    echo -e "${GREEN}"
    echo "✅ Installation complete"
    echo -e "${NC}"
else
    echo -e "${RED}"
    echo "❌ Installation failed"
    echo -e "${NC}"
fi

exit $exit_code
