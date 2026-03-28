# Pharmacovigilance Scenario

Clinical trial pharmacovigilance agent governed by Edictum. Uses LangGraph's `create_react_agent` with `ToolNode(wrap_tool_call=adapter.as_tool_wrapper())` for behavior integration. Demonstrates HIPAA/PII protection, role-based access, change control, audit trails, and regulatory compliance rules.

## Files

| File | Description |
|------|-------------|
| `pharma_rules.yaml` | YAML rule bundle (`edictum/v1`) |
| `pharma_agent.py` | CLI agent -- `LangChainAdapter` + `create_react_agent` |
| `pharma_agent_unguarded.py` | Same agent, no behavior checks (for comparison) |
| `pharma_web_demo.py` | FastAPI + SSE real-time web UI |

## Run

```bash
# CLI -- governed
python scenarios/pharma/pharma_agent.py
python scenarios/pharma/pharma_agent.py --role researcher   # gets denied on patient data
python scenarios/pharma/pharma_agent.py --observe            # observe mode

# CLI -- unguarded (shows what happens without behavior checks)
python scenarios/pharma/pharma_agent_unguarded.py
python scenarios/pharma/pharma_agent_unguarded.py --test jailbreak

# Web demo
python scenarios/pharma/pharma_web_demo.py
# open http://localhost:8787
```

## Contracts

| Contract | Type | What it does |
|----------|------|-------------|
| `restrict-patient-data` | pre | Blocks access to detailed patient records without proper role |
| `no-unblinding` | pre | Prevents unblinding treatment arms |
| `case-report-requires-ticket` | pre | Requires a tracking ticket for case report modifications |
| `case-report-authorized-roles` | pre | Only pharmacovigilance and clinical data managers can update reports |
| `pii-in-any-output` | post | Detects PII (SSN, patient names, email, phone) in all tool output |
| `regulatory-export-pii` | post | Flags regulatory exports containing PII |
| `session-limits` | session | Caps tool calls per session |

## What it demonstrates

- **Access control**: Researcher role is denied access to detailed adverse event records
- **Change control**: Case report updates require a CAPA/deviation tracking ticket
- **PII detection + redaction**: Patient identifiers (SSN, names, email) are detected in tool output and redacted before the LLM sees them
- **Regulatory compliance**: Exports are scanned for PII before submission
- **Audit trail**: Every behavior decision is logged with full context
- **Observe mode**: Logs would-deny events without blocking
