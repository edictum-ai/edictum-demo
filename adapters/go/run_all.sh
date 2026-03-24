#!/usr/bin/env bash
# Run all Go adapter demos and report results.
#
# Usage: ./run_all.sh
#        ./run_all.sh demo-langchaingo   # run a single demo

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

DEMOS=("demo-langchaingo" "demo-adkgo" "demo-anthropic")
PASSED=0
FAILED=0

if [[ $# -gt 0 ]]; then
    DEMOS=("$1")
fi

echo "========================================"
echo "  Edictum Go Adapter Demos"
echo "========================================"
echo ""

for demo in "${DEMOS[@]}"; do
    echo "--- Running $demo ---"
    # Uses go run (recompiles each time). For faster iteration, build first:
    #   go build -o bin/ ./demo-langchaingo/ ./demo-adkgo/ ./demo-anthropic/
    if go run "./$demo/"; then
        echo "  [OK] $demo completed successfully"
        PASSED=$((PASSED + 1))
    else
        echo "  [FAIL] $demo failed"
        FAILED=$((FAILED + 1))
    fi
    echo ""
done

echo "========================================"
echo "  Results: $PASSED passed, $FAILED failed"
echo "========================================"

if [[ $FAILED -gt 0 ]]; then
    exit 1
fi
