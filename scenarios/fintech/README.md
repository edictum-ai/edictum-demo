# Fintech / Trading Compliance Scenario

Demonstrates Edictum governance for a trading desk AI agent.

## What it demonstrates

- **Trade size limits** -- trades over 1,000 shares denied without manager approval
- **Account access control** -- full profile / transaction history restricted by role
- **Restricted account blocking** -- frozen/investigated accounts completely inaccessible
- **Compliance report governance** -- audit ticket required for report generation
- **PII detection in financial data** -- SSN/EIN, account numbers, emails, phones redacted
- **Session rate limiting** -- caps on total tool calls and per-tool limits

## Rules

| Contract | Type | What it does |
|----------|------|--------------|
| `trade-size-limit` | pre | Denies `execute_trade` when quantity > 1000 without `trade_approval` claim |
| `account-access-control` | pre | Denies full account data access for non-privileged roles |
| `no-restricted-accounts` | pre | Blocks all access to restricted/frozen accounts |
| `compliance-report-requires-ticket` | pre | Requires audit ticket ref for compliance reports |
| `pii-in-output` | post | Warns on SSN, account numbers, email, phone in any tool output |
| `pii-in-compliance-report` | post | Warns on PII in compliance reports (extra regulatory-submission tag) |
| `session-limits` | session | Max 15 tool calls, max 5 trades, max 2 compliance reports |

## Run

```bash
# Governed agent (default: compliance_officer role)
python fintech/fintech_agent.py

# Different roles
python fintech/fintech_agent.py --role analyst            # denied on full account data
python fintech/fintech_agent.py --role senior_trader       # full access with trade approval
python fintech/fintech_agent.py --role risk_manager        # full access

# With audit ticket (enables compliance reports)
python fintech/fintech_agent.py --ticket AUD-2025-118

# Observe mode (log but don't block)
python fintech/fintech_agent.py --mode observe

# Custom task
python fintech/fintech_agent.py --task "Execute a trade of 2000 shares of NVDA for ACC-847291"

# Unguarded agent (shows violations)
python fintech/fintech_agent_unguarded.py
python fintech/fintech_agent_unguarded.py --test jailbreak
python fintech/fintech_agent_unguarded.py --test data_laundering
```
