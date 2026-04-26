# Customer Support Agent Profile

Declared profile: Medium Agency with refund approval threshold.

This profile models a customer support agent that can inspect cases, look up customers, process bounded refunds, and escalate tickets inside runtime boundaries for billing data, PII, refund amount, escalation reason, and ticket lifecycle.

## What It Demonstrates

- Data minimization: PII is detected and redacted in all tool output
- Billing access boundary: only senior agents, billing specialists, and supervisors can view billing data
- Refund threshold: refunds over $500 require supervisor or billing specialist authority
- Escalation boundary: escalations require a documented reason
- Ticket lifecycle boundary: only senior agents and supervisors can close or resolve tickets
- Session boundary: total tool calls and per-tool calls are capped
- Behavioral conformance: the demo measures whether the agent stays inside the declared profile, not answer quality

## Runtime Rules

| Rule | Type | What it does |
|------|------|-------------|
| `billing-access-control` | pre | Blocks `lookup_customer` with billing data unless senior_agent/billing_specialist/supervisor |
| `refund-limit` | pre | Blocks `process_refund` over $500 unless supervisor/billing_specialist |
| `escalation-requires-reason` | pre | Blocks `escalate_ticket` without a documented reason |
| `ticket-update-authorized-roles` | pre | Blocks closing/resolving tickets unless senior_agent/supervisor |
| `pii-in-output` | post | Warns on PII in any tool output |
| `pii-in-customer-lookup` | post | Warns on PII + SSN in customer lookup output |
| `session-limits` | session | 20 total calls, 5 lookups, 3 refunds, 2 escalations |

## Run

```bash
# CLI -- with Edictum
python customer-support/support_agent.py
python customer-support/support_agent.py --role support_agent        # blocked on billing
python customer-support/support_agent.py --role billing_specialist   # full billing access
python customer-support/support_agent.py --role supervisor           # full access + high refunds
python customer-support/support_agent.py --mode observe              # observe mode

# CLI -- without Edictum
python customer-support/support_agent_unguarded.py
python customer-support/support_agent_unguarded.py --test jailbreak
python customer-support/support_agent_unguarded.py --test data_harvesting
```
