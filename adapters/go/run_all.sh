#!/usr/bin/env bash
# Run all Go adapter demos and report results.
#
# Usage: ./run_all.sh
#        ./run_all.sh demo-langchaingo   # run a single demo
#        ./run_all.sh --llm              # run all demos with LLM integration
#        LLM=1 ./run_all.sh             # same as --llm

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

DEMOS=("demo-langchaingo" "demo-adkgo" "demo-anthropic")
PASSED=0
FAILED=0
LLM_FLAG=""

# Check for --llm flag or LLM=1 env var
if [[ "${LLM:-}" == "1" || "${1:-}" == "--llm" ]]; then
    LLM_FLAG="--llm"
    # If --llm was the first arg, shift it so demo selection still works
    if [[ "${1:-}" == "--llm" ]]; then
        shift
    fi
fi

if [[ $# -gt 0 ]]; then
    DEMOS=("$1")
fi

echo "========================================"
echo "  Edictum Go Adapter Demos"
if [[ -n "$LLM_FLAG" ]]; then
    echo "  Mode: LLM (gpt-4.1-mini)"
fi
echo "========================================"
echo ""

for demo in "${DEMOS[@]}"; do
    echo "--- Running $demo $LLM_FLAG ---"
    # Uses go run (recompiles each time). For faster iteration, build first:
    #   go build -o bin/ ./demo-langchaingo/ ./demo-adkgo/ ./demo-anthropic/
    if go run "./$demo/" $LLM_FLAG; then
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
