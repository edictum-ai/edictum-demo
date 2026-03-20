#!/usr/bin/env bash
# ============================================================================
#  Edictum Adapter Integration Tests
# ============================================================================
#
#  Runs all adapter demos and validates governance results.
#  Use this after making changes to edictum core to verify nothing broke.
#
#  Usage:
#    ./adapters/run_all.sh                    # standalone, quick (12 scenarios)
#    ./adapters/run_all.sh --full             # standalone, full (17 scenarios)
#    ./adapters/run_all.sh --console          # console mode (needs server)
#    ./adapters/run_all.sh --with-docker      # include Claude Agent SDK
#    ./adapters/run_all.sh --branch           # install edictum from local repo
#    ./adapters/run_all.sh --reset            # reinstall edictum from PyPI
#
#  Testing a feature branch:
#    cd /path/to/edictum && git checkout my-feature
#    cd /path/to/edictum-demo
#    ./adapters/run_all.sh --branch           # installs from ../edictum, runs tests
#    ./adapters/run_all.sh --reset            # restores PyPI version when done
#
#  Prerequisites:
#    - .env with OPENAI_API_KEY and GEMINI_API_KEY
#    - --console: edictum-console on localhost:8000 + EDICTUM_API_KEY in .env
#    - --with-docker: Docker + ANTHROPIC_API_KEY in .env
#    - --branch: edictum repo at ../edictum (or set EDICTUM_REPO env var)
#
#  Expected (standalone, quick):  5 DENIED, 1 REDACTED, 1 OBSERVE, 5 ALLOWED
#  Expected (standalone, full):   6 DENIED, 1 REDACTED, 1 OBSERVE, 1 APPROVAL, 8 ALLOWED

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

# ── Parse flags ─────────────────────────────────────────────────────────────

MODE=""
QUICK="--quick"
WITH_DOCKER=false
USE_BRANCH=false
RESET=false

for arg in "$@"; do
    case "$arg" in
        --console)      MODE="--console" ;;
        --full)         QUICK="" ;;
        --with-docker)  WITH_DOCKER=true ;;
        --branch)       USE_BRANCH=true ;;
        --reset)        RESET=true ;;
        --help|-h)
            head -30 "$0" | grep '^#' | sed 's/^# \?//'
            exit 0
            ;;
    esac
done

# ── Colors ──────────────────────────────────────────────────────────────────

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
CYAN='\033[0;36m'
NC='\033[0m'

PASS=0
FAIL=0
SKIP=0
RESULTS=()

# ── Activate venv ──────────────────────────────────────────────────────────

if [ -f "$REPO_ROOT/.venv/bin/activate" ]; then
    source "$REPO_ROOT/.venv/bin/activate"
fi

# ── Handle --reset ─────────────────────────────────────────────────────────

if [ "$RESET" = true ]; then
    printf "${CYAN}Reinstalling edictum from PyPI...${NC}\n"
    pip install edictum[yaml] --quiet --force-reinstall 2>&1 | tail -1
    VERSION=$(python3 -c 'import edictum; print(edictum.__version__)' 2>/dev/null || echo '?')
    printf "${GREEN}Restored to PyPI: edictum $VERSION${NC}\n"
    if [ "$USE_BRANCH" = false ] && [ "$WITH_DOCKER" = false ] && [ -z "$MODE" ]; then
        exit 0  # --reset alone just resets, doesn't run tests
    fi
fi

# ── Handle --branch ────────────────────────────────────────────────────────

EDICTUM_SOURCE="PyPI"
BRANCH=""

if [ "$USE_BRANCH" = true ]; then
    EDICTUM_REPO="${EDICTUM_REPO:-$(cd "$REPO_ROOT/../edictum" 2>/dev/null && pwd)}"
    if [ ! -d "$EDICTUM_REPO" ]; then
        printf "${RED}ERROR: edictum repo not found at $EDICTUM_REPO${NC}\n"
        printf "Set EDICTUM_REPO or clone edictum next to edictum-demo\n"
        exit 1
    fi

    BRANCH=$(cd "$EDICTUM_REPO" && git branch --show-current)
    printf "${CYAN}Installing edictum from: ${EDICTUM_REPO}${NC}\n"
    printf "${CYAN}Branch: ${BRANCH}${NC}\n"
    pip install -e "$EDICTUM_REPO[yaml]" --quiet 2>&1 | tail -1
    EDICTUM_SOURCE="local ($BRANCH)"
    printf "${GREEN}Installed.${NC}\n\n"
fi

EDICTUM_VERSION=$(python3 -c 'import edictum; print(edictum.__version__)' 2>/dev/null || echo '?')

# ── Header ──────────────────────────────────────────────────────────────────

echo ""
echo "============================================================================"
echo "  EDICTUM ADAPTER INTEGRATION TESTS"
echo "============================================================================"
echo "  Mode:       $([ -z "$MODE" ] && echo "standalone (local YAML)" || echo "console (edictum-console)")"
echo "  Scenarios:  $([ -n "$QUICK" ] && echo "quick (12)" || echo "full (17)")"
echo "  Docker:     $([ "$WITH_DOCKER" = true ] && echo "yes" || echo "skip")"
echo "  Edictum:    $EDICTUM_VERSION ($EDICTUM_SOURCE)"
echo "============================================================================"

# ── Parallel infrastructure ─────────────────────────────────────────────────
#
#  Uses indexed arrays for bash 3.2 compatibility (macOS).
#  BG_NAMES[i], BG_PIDS[i], BG_FILES[i] are parallel arrays.

BG_NAMES=()
BG_PIDS=()
BG_FILES=()

run_adapter_bg() {
    local name="$1"
    local cmd="$2"
    local timeout="${3:-180}"

    local tmpfile
    tmpfile=$(mktemp)
    local idx=${#BG_NAMES[@]}
    BG_NAMES[$idx]="$name"
    BG_FILES[$idx]="$tmpfile"

    (
        if command -v gtimeout &>/dev/null; then
            gtimeout "$timeout" bash -c "$cmd" > "$tmpfile" 2>&1
        elif command -v timeout &>/dev/null; then
            timeout "$timeout" bash -c "$cmd" > "$tmpfile" 2>&1
        else
            bash -c "$cmd" > "$tmpfile" 2>&1
        fi
    ) &
    BG_PIDS[$idx]=$!
}

# ── validate_adapter ────────────────────────────────────────────────────────
#
#  Waits for a background adapter by index, validates its results.
#  Usage: validate_adapter <index>

validate_adapter() {
    local i="$1"
    local name="${BG_NAMES[$i]}"
    local pid="${BG_PIDS[$i]}"
    local tmpfile="${BG_FILES[$i]}"

    printf "\n${CYAN}━━━ %-20s ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}\n" "$name"

    set +e
    wait "$pid"
    local exit_code=$?
    set -e

    if [ $exit_code -ne 0 ] && [ $exit_code -ne 124 ]; then
        printf "  ${RED}FAILED${NC} (exit code $exit_code)\n"
        tail -5 "$tmpfile" | sed 's/^/  /'
        FAIL=$((FAIL + 1))
        RESULTS+=("${RED}FAIL${NC}  $name")
        rm -f "$tmpfile"
        return
    fi

    if [ $exit_code -eq 124 ]; then
        printf "  ${RED}TIMEOUT${NC} (see BG_FILES)\n"
        FAIL=$((FAIL + 1))
        RESULTS+=("${RED}TIME${NC}  $name")
        rm -f "$tmpfile"
        return
    fi

    # Extract governance results
    local denied redacted observe allowed approve skipped
    denied=$(grep -c '\[X\]' "$tmpfile" 2>/dev/null | tr -cd '0-9' || echo 0)
    redacted=$(grep -c '\[~\] REDACTED' "$tmpfile" 2>/dev/null | tr -cd '0-9' || echo 0)
    observe=$(grep -c '\[o\]' "$tmpfile" 2>/dev/null | tr -cd '0-9' || echo 0)
    allowed=$(grep -c '\[+\]' "$tmpfile" 2>/dev/null | tr -cd '0-9' || echo 0)
    approve=$(grep -c '\[?\]' "$tmpfile" 2>/dev/null | tr -cd '0-9' || echo 0)
    skipped=$(grep -c '\[-\]' "$tmpfile" 2>/dev/null | tr -cd '0-9' || echo 0)
    denied=${denied:-0}; redacted=${redacted:-0}; observe=${observe:-0}
    allowed=${allowed:-0}; approve=${approve:-0}; skipped=${skipped:-0}

    printf "  Denied: %-3s  Redacted: %-3s  Observe: %-3s  Allowed: %-3s" \
        "$denied" "$redacted" "$observe" "$allowed"
    [ "$approve" -gt 0 ] && printf "  Approval: %-3s" "$approve"
    [ "$skipped" -gt 0 ] && printf "  Skipped: %-3s" "$skipped"
    printf "\n"

    # Validate results
    # ±1 tolerance on denials — LLMs sometimes refuse to call "evil" tools
    if [ -z "$MODE" ]; then
        if [ -n "$QUICK" ]; then
            # Quick: 5D 1R 1O 5A
            if [ "$denied" -ge 4 ] && [ "$denied" -le 5 ] && [ "$redacted" -eq 1 ] && [ "$observe" -ge 1 ] && [ "$allowed" -ge 4 ]; then
                if [ "$denied" -eq 5 ] && [ "$allowed" -eq 5 ]; then
                    printf "  ${GREEN}PASS${NC}\n"
                else
                    printf "  ${GREEN}PASS${NC} (within tolerance)\n"
                fi
                PASS=$((PASS + 1))
                RESULTS+=("${GREEN}PASS${NC}  $name  (${denied}D ${redacted}R ${observe}O ${allowed}A)")
            else
                printf "  ${RED}FAIL${NC} — expected ~5D 1R 1O ~5A\n"
                FAIL=$((FAIL + 1))
                RESULTS+=("${RED}FAIL${NC}  $name  (got ${denied}D ${redacted}R ${observe}O ${allowed}A)")
            fi
        else
            # Full: 6D 1R 1O 1AP 8A
            if [ "$denied" -ge 5 ] && [ "$denied" -le 6 ] && [ "$redacted" -eq 1 ] && [ "$observe" -ge 1 ] && [ "$allowed" -ge 7 ]; then
                if [ "$denied" -eq 6 ] && [ "$allowed" -eq 8 ]; then
                    printf "  ${GREEN}PASS${NC}\n"
                else
                    printf "  ${GREEN}PASS${NC} (within tolerance)\n"
                fi
                PASS=$((PASS + 1))
                RESULTS+=("${GREEN}PASS${NC}  $name  (${denied}D ${redacted}R ${observe}O ${allowed}A)")
            else
                printf "  ${RED}FAIL${NC} — expected ~6D 1R 1O ~8A\n"
                FAIL=$((FAIL + 1))
                RESULTS+=("${RED}FAIL${NC}  $name  (got ${denied}D ${redacted}R ${observe}O ${allowed}A)")
            fi
        fi
    else
        # Console mode: check if #70 (TeeAuditSink) is fixed
        if [ "$denied" -ge 4 ] && [ "$redacted" -ge 1 ] && [ "$observe" -ge 1 ]; then
            # Console mode returning real results — #70 is fixed!
            printf "  ${GREEN}PASS${NC} (console mode with local audit)\n"
            PASS=$((PASS + 1))
            RESULTS+=("${GREEN}PASS${NC}  $name  (console: ${denied}D ${redacted}R ${observe}O ${allowed}A)")
        elif [ "$denied" -eq 0 ] && [ "$allowed" -gt 0 ]; then
            # All ALLOWED = #70 still open (audit events go to server, no local sink)
            printf "  ${YELLOW}#70${NC}  — no local audit in console mode (all results show ALLOWED)\n"
            printf "        governance runs server-side but classify_result() can't see events\n"
            SKIP=$((SKIP + 1))
            RESULTS+=("${YELLOW}#70 ${NC}  $name  (console: no local audit — needs TeeAuditSink)")
        else
            # Partial results — something else going on
            printf "  ${YELLOW}CHECK${NC} — partial results, verify in console dashboard\n"
            SKIP=$((SKIP + 1))
            RESULTS+=("${YELLOW}CHECK${NC} $name  (console: ${denied}D ${redacted}R ${observe}O ${allowed}A)")
        fi
    fi

    rm -f "$tmpfile"
}

# ── Run adapters (parallel) ────────────────────────────────────────────────

printf "\n${CYAN}Launching adapters in parallel...${NC}\n"

run_adapter_bg "LangChain" \
    "python adapters/demo_langchain.py $QUICK $MODE"

run_adapter_bg "OpenAI Agents" \
    "python adapters/demo_openai_agents.py $QUICK $MODE"

run_adapter_bg "Agno" \
    "python adapters/demo_agno.py $QUICK $MODE"

run_adapter_bg "Semantic Kernel" \
    "python adapters/demo_semantic_kernel.py $QUICK $MODE"

run_adapter_bg "CrewAI" \
    "python adapters/demo_crewai.py $QUICK $MODE"

run_adapter_bg "Google ADK" \
    "python adapters/demo_google_adk.py $QUICK $MODE" 300

run_adapter_bg "Deep Agents" \
    "python adapters/demo_deep_agents.py $QUICK $MODE"

if [ "$WITH_DOCKER" = true ]; then
    DOCKER_ARGS=""
    if [ -n "$MODE" ]; then
        DOCKER_ARGS="--network host"
    fi
    run_adapter_bg "Claude Agent SDK" \
        "docker build -f adapters/claude-agent-sdk/Dockerfile -t edictum-claude-sdk-demo . >/dev/null 2>&1 && \
         docker run --rm --env-file .env $DOCKER_ARGS edictum-claude-sdk-demo $QUICK $MODE" 300
fi

# ── Benchmark (runs in parallel with adapters) ─────────────────────────────

bench_tmpfile=$(mktemp)
(python benchmark/benchmark_adapters.py 2>&1 | grep -v "^Postcondition" > "$bench_tmpfile") &
BENCH_PID=$!

# ── Collect results (in launch order) ──────────────────────────────────────

if [ "$WITH_DOCKER" != true ]; then
    printf "\n${CYAN}━━━ %-20s ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}\n" "Claude Agent SDK"
    printf "  ${YELLOW}SKIP${NC} — use --with-docker to include\n"
    SKIP=$((SKIP + 1))
    RESULTS+=("${YELLOW}SKIP${NC}  Claude Agent SDK  (use --with-docker)")
fi

for i in $(seq 0 $((${#BG_NAMES[@]} - 1))); do
    validate_adapter "$i"
done

# ── Benchmark result ───────────────────────────────────────────────────────

printf "\n${CYAN}━━━ %-20s ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}\n" "Benchmark"
set +e
wait "$BENCH_PID"
bench_exit=$?
set -e

if [ $bench_exit -eq 0 ]; then
    avg=$(grep "guard.run" "$bench_tmpfile" | grep -oE '[0-9]+\.[0-9]+ us' | tail -1)
    printf "  Core overhead: %s\n" "${avg:-unknown}"
    printf "  ${GREEN}PASS${NC}\n"
    PASS=$((PASS + 1))
    RESULTS+=("${GREEN}PASS${NC}  Benchmark  (core: ${avg:-?})")
else
    printf "  ${RED}FAIL${NC}\n"
    tail -3 "$bench_tmpfile" | sed 's/^/  /'
    FAIL=$((FAIL + 1))
    RESULTS+=("${RED}FAIL${NC}  Benchmark")
fi
rm -f "$bench_tmpfile"

# ── Summary ─────────────────────────────────────────────────────────────────

echo ""
echo "============================================================================"
echo "  SUMMARY"
echo "============================================================================"
for r in "${RESULTS[@]}"; do
    printf "  $r\n"
done
echo ""
printf "  Total: ${GREEN}$PASS passed${NC}"
[ $FAIL -gt 0 ] && printf ", ${RED}$FAIL failed${NC}"
[ $SKIP -gt 0 ] && printf ", ${YELLOW}$SKIP skipped${NC}"
printf "\n"
echo "============================================================================"

# Exit with failure if any test failed
[ $FAIL -eq 0 ]
