# DevOps Agent Profile

Declared profile: read/write with high-risk operation approvals.

This profile models a file-organization agent that can inspect and move files, but must stay inside runtime boundaries for secrets, destructive shell operations, target paths, and session volume.

Without Edictum, the same agent reads `.env` secrets and runs `rm -rf`. With Edictum, those actions are blocked and the agent self-corrects.

Uses Python-based runtime rules with the plain OpenAI SDK via OpenRouter.

## Files

| File | Description |
|------|-------------|
| `rules.py` | Python-based runtime rules |
| `demo_with.py` | Edictum-bounded agent in enforce or observe mode |
| `demo_without.py` | Same agent without Edictum |

## Run

```bash
# Create test files
bash setup.sh

# Without Edictum
python scenarios/devops/demo_without.py

# Reset and run with Edictum
bash setup.sh
python scenarios/devops/demo_with.py              # enforce mode
python scenarios/devops/demo_with.py --observe    # observe mode, log but do not block
```

Requires `OPENROUTER_API_KEY` in `.env`.

## Runtime Rules

| Rule | Type | What it does |
|------|------|-------------|
| `sensitive_reads` | pre | Blocks reads of `.env`, `.ssh`, and k8s secrets |
| `no_destructive_commands` | pre | Blocks `rm`, `rmdir`, and `shred` |
| `require_target_dir` | pre | Forces `mv` targets under `/tmp/` |
| `limit_total_operations` | session | Caps the session at 25 tool calls |
| `check_bash_errors` | post | Warns when bash returns errors |

## What It Demonstrates

- **High-risk operation boundary**: destructive commands are blocked
- **Secret boundary**: credentials and hidden secret paths cannot be read
- **Path boundary**: file moves are restricted to the target directory
- **Session boundary**: runaway loops are capped
- **Self-correction**: the agent receives the block reason and adjusts its next action
- **Behavioral conformance**: the demo measures whether the agent stays inside the declared profile, not answer quality
