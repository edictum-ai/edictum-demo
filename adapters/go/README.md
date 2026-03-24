# Edictum Go Adapter Demos

Demonstrates runtime contract enforcement using the [edictum-go](https://github.com/edictum-ai/edictum-go) SDK with three framework adapters.

## Adapters

| Demo | Adapter | Description |
|------|---------|-------------|
| `demo-langchaingo/` | LangChainGo | String-in/string-out tool wrapping |
| `demo-adkgo/` | Google ADK Go | `map[string]any` tool wrapping |
| `demo-anthropic/` | Anthropic SDK | `json.RawMessage` tool wrapping |

## Prerequisites

- Go 1.25+
- Clone edictum-go: `git clone https://github.com/edictum-ai/edictum-go.git`

## Setup

The `go.mod` uses a `replace` directive pointing to a local edictum-go checkout (assumes sibling repos). Update the path if your layout differs. When edictum-go is published, remove the `replace` directive and run `go mod tidy` to regenerate `go.sum`:

```
replace github.com/edictum-ai/edictum-go => /path/to/your/edictum-go
```

## Running

```bash
# Run a single demo
go run ./demo-langchaingo/
go run ./demo-adkgo/
go run ./demo-anthropic/

# Run all demos
chmod +x run_all.sh
./run_all.sh
```

## What each demo does

1. Loads contracts from `../contracts.yaml` (shared with Python demos)
2. Creates an Edictum guard with `enforce` mode and `analyst` role
3. Shows adapter-specific tool wrapping code
4. Runs 12 scenarios through the governance pipeline
5. Classifies results from audit events (not LLM text parsing)
6. Prints a governance summary

## Expected results (16 quick scenarios)

| # | Scenario | Expected | Notes |
|---|----------|----------|-------|
| 1 | Weather lookup | ALLOWED | |
| 2 | Read safe file | DENIED | Sandbox stub bug (should be ALLOWED) |
| 3 | Read contacts with PII | DENIED | Sandbox stub bug (should be REDACTED) |
| 4 | Read /etc/passwd | DENIED | Precondition: no-sensitive-files |
| 5 | Read .env file | DENIED | Precondition: no-sensitive-files |
| 6 | Read outside sandbox | DENIED | Sandbox stub bug (correct outcome, wrong reason) |
| 7 | Email to company | ALLOWED | Observe-mode audit fires but does not block |
| 8 | Email to evil domain | DENIED | Precondition: no-email-to-external |
| 9 | Search web | ALLOWED |  |
| 10 | Delete without admin | DENIED | RBAC: delete-requires-admin |
| 11 | Update confirmed | ALLOWED |  |
| 12 | Weather #2 | ALLOWED | Rate limit counting |
| 13 | Weather #3 | ALLOWED | |
| 14 | Weather #4 | ALLOWED | |
| 15 | Weather #5 (last) | ALLOWED | |
| 16 | Weather #6 | DENIED | Rate limit: max 5 per session |

8 denied, 0 redacted, 8 allowed.

> **Known issue:** edictum-go has a sandbox wiring bug — YAML sandbox contracts
> always deny because the compiled stub is never replaced with `sandbox.Check()`.
> Scenarios 2, 3, 6 are affected. In Python, these produce ALLOWED, REDACTED,
> and DENIED respectively. See shared/shared.go for details.

## Contracts

All demos share `../contracts.yaml` which exercises:
- **Pre contracts**: deny evil emails, block sensitive files, RBAC delete, approval for updates, observe-mode email audit
- **Post contracts**: redact PII, warn on file errors, deny credentials in output
- **Sandbox**: restrict read_file to /home/, /tmp/, /var/log/
- **Session**: rate limit weather (5/session), global limit (25/session)
