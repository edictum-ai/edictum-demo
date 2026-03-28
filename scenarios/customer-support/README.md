# Customer Support Scenario

Demonstrates Edictum behavior checks for a customer support AI agent.

## What it demonstrates
- Data minimization: PII (emails, phones, addresses, partial card numbers) detected and redacted in all tool output
- Billing access control: only senior agents, billing specialists, and supervisors can view billing data
- Refund limits: refunds over $500 require supervisor or billing specialist role
- Escalation behavior: escalations require a documented reason
- Ticket lifecycle: only senior agents and supervisors can close/resolve tickets
- Session limits: caps on total tool calls and per-tool call limits

## Contracts

| Contract | Type | What it does |
|----------|------|-------------|
| `billing-access-control` | pre | Denies `lookup_customer` with billing data unless senior_agent/billing_specialist/supervisor |
| `refund-limit` | pre | Denies `process_refund` over $500 unless supervisor/billing_specialist |
| `escalation-requires-reason` | pre | Denies `escalate_ticket` without a documented reason |
| `ticket-update-authorized-roles` | pre | Denies closing/resolving tickets unless senior_agent/supervisor |
| `pii-in-output` | post | Warns on PII (email, phone, address, card) in any tool output |
| `pii-in-customer-lookup` | post | Warns on PII + SSN in customer lookup output |
| `session-limits` | session | 20 total calls, 5 lookups, 3 refunds, 2 escalations |

## Run

```bash
# CLI -- governed (uses LangChainAdapter)
python customer-support/support_agent.py
python customer-support/support_agent.py --role support_agent        # denied on billing
python customer-support/support_agent.py --role billing_specialist   # full billing access
python customer-support/support_agent.py --role supervisor           # full access + high refunds
python customer-support/support_agent.py --mode observe              # observe mode

# CLI -- unguarded (shows what happens without behavior checks)
python customer-support/support_agent_unguarded.py
python customer-support/support_agent_unguarded.py --test jailbreak
python customer-support/support_agent_unguarded.py --test data_harvesting
```
