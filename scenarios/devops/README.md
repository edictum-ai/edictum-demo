# DevOps Scenario

File organizer agent -- with and without Edictum governance. The agent organizes messy files into a clean directory structure. Without governance, it reads `.env` secrets and runs `rm -rf`. With Edictum, it hits guardrails and self-corrects.

Uses Python-based contracts (not YAML) with the plain OpenAI SDK via OpenRouter.

## Files

| File | Description |
|------|-------------|
| `rules.py` | Python-based governance contracts |
| `demo_with.py` | Governed agent (enforce or observe mode) |
| `demo_without.py` | Unguarded agent (the scary baseline) |

## Run

```bash
# Create test files
bash setup.sh

# Without governance (reads secrets, runs rm -rf)
python scenarios/devops/demo_without.py

# Reset and run with governance
bash setup.sh
python scenarios/devops/demo_with.py              # enforce mode
python scenarios/devops/demo_with.py --observe    # observe mode (log but don't block)
```

Requires `OPENROUTER_API_KEY` in `.env`.

## Rules

| Contract | Type | What it does |
|----------|------|-------------|
| `sensitive_reads` | Precondition (built-in) | Blocks reads of `.env`, `.ssh`, k8s secrets |
| `no_destructive_commands` | Precondition | Blocks `rm`, `rmdir`, `shred` |
| `require_target_dir` | Precondition | Forces `mv` targets under `/tmp/` |
| `limit_total_operations` | Session | Caps session at 25 tool calls |
| `check_bash_errors` | Postcondition | Warns when bash returns errors |

## What it demonstrates

- **Python rules**: Behavior defined in code with `@precondition`, `@postcondition`, `@session_contract` decorators
- **Secret protection**: Agent is blocked from reading `.env` files containing credentials
- **Blast radius limits**: Destructive commands (`rm -rf`) are denied; agent self-corrects to use `mv`
- **Path confinement**: File moves are restricted to the target directory
- **Session limits**: Runaway agent loops are capped at 25 operations
- **Self-correction**: When denied, the LLM reads the denial reason and adjusts its approach
