# Fintech Agent Profile

Declared profile: write limits and compliance reporting.

This profile models a trading desk agent that can read account context, place bounded trades, and generate compliance reports only when the declared runtime boundaries are satisfied.

## What It Demonstrates

- **Write limit** -- trades over 1,000 shares are blocked without manager approval
- **Account access boundary** -- full profile and transaction history are restricted by role
- **Restricted account boundary** -- frozen or investigated accounts are inaccessible
- **Compliance reporting boundary** -- an audit ticket is required for report generation
- **PII handling** -- SSN/EIN, account numbers, emails, and phones are redacted
- **Session boundary** -- total tool calls and per-tool calls are capped
- **Behavioral conformance** -- the demo measures whether the agent stays inside the declared profile, not answer quality

## Runtime Rules

| Rule | Type | What it does |
|------|------|--------------|
| `trade-size-limit` | pre | Blocks `execute_trade` when quantity > 1000 without `trade_approval` claim |
| `account-access-control` | pre | Blocks full account data access for non-privileged roles |
| `no-restricted-accounts` | pre | Blocks all access to restricted/frozen accounts |
| `compliance-report-requires-ticket` | pre | Requires audit ticket ref for compliance reports |
| `pii-in-output` | post | Warns on SSN, account numbers, email, phone in any tool output |
| `pii-in-compliance-report` | post | Warns on PII in compliance reports |
| `session-limits` | session | Max 15 tool calls, max 5 trades, max 2 compliance reports |

## Run

```bash
# Edictum-bounded agent (default: compliance_officer role)
python fintech/fintech_agent.py

# Different roles
python fintech/fintech_agent.py --role analyst            # blocked on full account data
python fintech/fintech_agent.py --role senior_trader       # full access with trade approval
python fintech/fintech_agent.py --role risk_manager        # full access

# With audit ticket, enabling compliance reports
python fintech/fintech_agent.py --ticket AUD-2025-118

# Observe mode, log but do not block
python fintech/fintech_agent.py --mode observe

# Custom task
python fintech/fintech_agent.py --task "Execute a trade of 2000 shares of NVDA for ACC-847291"

# Same agent without Edictum
python fintech/fintech_agent_unguarded.py
python fintech/fintech_agent_unguarded.py --test jailbreak
python fintech/fintech_agent_unguarded.py --test data_laundering
```
