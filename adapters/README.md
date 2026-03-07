# Framework Adapters

Same governance contracts, 8 different agent frameworks. Proves Edictum is framework-agnostic.

All demos use shared mock tools and contracts (`shared_v2.py`, `contracts.yaml`) that exercise
all edictum features: pre/post/session/sandbox contracts, deny/redact/warn/approve effects,
RBAC, observe mode, and HITL approval.

## Demos

| Framework | File | Adapter API | Integration |
|-----------|------|-------------|-------------|
| LangChain + LangGraph | `demo_langchain.py` | `adapter.as_tool_wrapper()` | Tool wrapper |
| OpenAI Agents SDK | `demo_openai_agents.py` | `adapter.as_guardrails()` | Input/output guardrails |
| Agno | `demo_agno.py` | `adapter.as_tool_hook()` | Tool hook |
| Semantic Kernel | `demo_semantic_kernel.py` | `adapter.register(kernel)` | Kernel filter |
| CrewAI | `demo_crewai.py` | `adapter.register()` | Step callback |
| Google ADK | `demo_google_adk.py` | `adapter.as_plugin()` | Runner plugin or agent callbacks |
| Claude Agent SDK | `demo_claude_agent_sdk.py` | `adapter.to_hook_callables()` | PreToolUse/PostToolUse hooks |
| Nanobot | *(on droplet)* | `GovernedToolRegistry` | Tool registry wrapper |

## Run

```bash
# Standalone mode (local YAML contracts)
python adapters/demo_langchain.py
python adapters/demo_openai_agents.py
python adapters/demo_agno.py
python adapters/demo_semantic_kernel.py
python adapters/demo_crewai.py
python adapters/demo_google_adk.py

# Claude Agent SDK (requires Docker -- see below)
./adapters/claude-agent-sdk/run.sh

# Options available for all demos
python adapters/demo_langchain.py --role admin     # Change principal role
python adapters/demo_langchain.py --mode observe   # Log but don't block
python adapters/demo_langchain.py --quick           # Skip rate limit + approval scenarios
python adapters/demo_langchain.py --console         # Connect to edictum-console server

# Google ADK also supports --callbacks for per-agent callback integration
python adapters/demo_google_adk.py --callbacks
```

### Required API keys

| Demo | Key |
|------|-----|
| LangChain, OpenAI Agents, SK, CrewAI | `OPENAI_API_KEY` |
| Agno | `OPENAI_API_KEY` |
| Google ADK | `GEMINI_API_KEY` |
| Claude Agent SDK | `ANTHROPIC_API_KEY` |
| Console mode (any demo) | `EDICTUM_API_KEY` |

### Claude Agent SDK (Docker)

The Claude Agent SDK launches Claude Code as a subprocess, so it cannot run inside
an existing Claude Code session. Use the provided Docker container:

```bash
# Build and run (from repo root)
docker build -f adapters/claude-agent-sdk/Dockerfile -t edictum-claude-sdk-demo .
docker run --rm -it -e ANTHROPIC_API_KEY="$ANTHROPIC_API_KEY" edictum-claude-sdk-demo

# Or use the convenience script
./adapters/claude-agent-sdk/run.sh --quick --role admin
```

## Governance Coverage

Every demo exercises the same 17 scenarios covering:

| Contract Type | Scenarios | Expected Outcome |
|---------------|-----------|------------------|
| Pre (deny) | Sensitive file paths, evil email domains | DENIED |
| Pre (RBAC) | Delete without admin role | DENIED |
| Pre (approve) | Unconfirmed record update | APPROVAL required |
| Pre (observe) | Email audit logging | Logged, not blocked |
| Post (redact) | PII in contacts file output | REDACTED (SSN, email, phone) |
| Sandbox | File path outside allowed dirs | DENIED |
| Session | 6th weather call exceeds limit | DENIED |

## Known Limitations

| Framework | Limitation |
|-----------|------------|
| **OpenAI Agents SDK** | Output guardrail is side-effect only -- cannot redact PII before the LLM sees it |
| **CrewAI** | ~3x token usage due to verbose internal prompt construction |
| **Agno** | No token usage metrics exposed by the framework |
| **Agno / CrewAI** | Console mode (`--console`) fails due to cross-event-loop bug ([#67](https://github.com/acartag7/edictum/issues/67)) -- sync frameworks create their own event loops, breaking the async httpx client from `Edictum.from_server()` |
| **Claude Agent SDK** | Must run in Docker container (nested Claude Code session detection) |
| **Google ADK** | Free tier rate limits vary by model; use `gemini-3.1-flash-lite-preview` |

## Hot Reload Test

Tests that contract changes deployed via the console propagate to connected agents
in real-time via SSE, without restarting the agent. No LLM calls -- uses `guard.run()`
directly, so it's fast, deterministic, and free.

```bash
# Basic (needs console on localhost:8000)
python adapters/test_hot_reload.py

# More agents, longer timeout
python adapters/test_hot_reload.py --agents 5 --timeout 30
```

Requires `EDICTUM_API_KEY` in `.env` and a running console. Admin credentials default to
`admin@demo.test` / `edictum2026` (override via `EDICTUM_ADMIN_EMAIL` / `EDICTUM_ADMIN_PASSWORD`).

### What it validates

| Check | Description |
|-------|-------------|
| Baseline governance | V1 contracts deny email to evil.com |
| SSE reload detected | `policy_version` changes after deploying V2 |
| Behavior changed | V2 (email rule removed) allows evil email |
| Second reload | `policy_version` changes again after re-deploying V1 |
| Behavior restored | V1 denies evil email again -- full round-trip |

The test uploads two contract variants (with/without an email deny rule), deploys them
in sequence, and verifies that multiple connected agents pick up each change via SSE
hot-reload within the timeout window.

## Integration Test

Run all adapters and validate governance results in one command:

```bash
# Quick standalone test (~3 min)
./adapters/run_all.sh

# Full test — all 17 scenarios (rate limit + approval)
./adapters/run_all.sh --full

# Console mode — needs edictum-console on localhost:8000
./adapters/run_all.sh --console

# Include Claude Agent SDK (Docker required)
./adapters/run_all.sh --with-docker

# Everything
./adapters/run_all.sh --full --with-docker --console
```

### Testing an edictum feature branch

```bash
# Test against your local edictum branch (auto-installs from ../edictum)
cd /path/to/edictum && git checkout my-feature
cd /path/to/edictum-demo
./adapters/run_all.sh --branch                   # standalone
./adapters/run_all.sh --branch --console          # + console mode

# Restore PyPI version when done
./adapters/run_all.sh --reset
```

Set `EDICTUM_REPO` to override the default path (`../edictum`):

```bash
EDICTUM_REPO=/other/path/to/edictum ./adapters/run_all.sh --branch
```

### What it validates

| Mode | Checks |
|------|--------|
| Standalone | Exact governance counts: 5D 1R 1O 5A (±1 for LLM flakiness) |
| Console | If #70 (TeeAuditSink) is fixed: validates counts. If not: flags `#70` and skips |
| Benchmark | Runs `benchmark_adapters.py`, reports core overhead per tool call |

### Detecting issue #70

In console mode, the script automatically detects whether `TeeAuditSink` (#70) is
implemented. If all results show ALLOWED with 0 denials, it reports:

```
  #70  — no local audit in console mode (all results show ALLOWED)
         governance runs server-side but classify_result() can't see events
```

Once #70 ships, the same script will automatically start validating console results.

See `FINDINGS.md` for detailed per-adapter integration notes.
