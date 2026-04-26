# Pharmacovigilance Agent Profile

Declared profile: read/write with sensitive data boundaries.

This profile models a clinical trial pharmacovigilance agent that can inspect cases, update reports, and prepare exports only inside runtime boundaries for patient data, role access, change control, and evidence capture.

## Files

| File | Description |
|------|-------------|
| `pharma_rules.yaml` | YAML runtime rules bundle (`edictum/v1`) |
| `pharma_agent.py` | Edictum-bounded CLI agent using `LangChainAdapter` + `create_react_agent` |
| `pharma_agent_unguarded.py` | Same agent without Edictum for comparison |
| `pharma_web_demo.py` | FastAPI + SSE real-time web UI |

## Run

```bash
# CLI -- with Edictum
python scenarios/pharma/pharma_agent.py
python scenarios/pharma/pharma_agent.py --role researcher   # blocked on patient data
python scenarios/pharma/pharma_agent.py --observe            # observe mode

# CLI -- without Edictum
python scenarios/pharma/pharma_agent_unguarded.py
python scenarios/pharma/pharma_agent_unguarded.py --test jailbreak

# Web demo
python scenarios/pharma/pharma_web_demo.py
# open http://localhost:8787
```

## Runtime Rules

| Rule | Type | What it does |
|------|------|-------------|
| `restrict-patient-data` | pre | Blocks access to detailed patient records without proper role |
| `no-unblinding` | pre | Prevents unblinding treatment arms |
| `case-report-requires-ticket` | pre | Requires a tracking ticket for case report modifications |
| `case-report-authorized-roles` | pre | Only pharmacovigilance and clinical data managers can update reports |
| `pii-in-any-output` | post | Detects PII in all tool output |
| `regulatory-export-pii` | post | Flags regulatory exports containing PII |
| `session-limits` | session | Caps tool calls per session |

## What It Demonstrates

- **Sensitive data boundary**: researcher access is blocked for detailed adverse event records
- **Change control**: case report updates require a CAPA/deviation tracking ticket
- **PII handling**: patient identifiers are detected and redacted before the LLM sees them
- **Regulatory export boundary**: exports are scanned before submission
- **Evidence trail**: every runtime decision is logged with context
- **Behavioral conformance**: the demo measures whether the agent stays inside the declared profile, not answer quality
