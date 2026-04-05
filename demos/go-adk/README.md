# Go Workflow Gates Demo

Deterministic single-agent Workflow Gates demo using the Go `adkgo` adapter.

It uses:
- `github.com/edictum-ai/edictum-go/guard`
- `github.com/edictum-ai/edictum-go/server`
- `github.com/edictum-ai/edictum-go/workflow`
- `github.com/edictum-ai/edictum-go/adapter/adkgo`
- the shared [`coding-guard.yaml`](../../workflows/coding-guard.yaml) workflow

This demo does not call a real LLM. It drives tool calls directly so the run is
predictable.

## Setup

Start the local API first. Use [`demos/hero/README.md`](../hero/README.md) for the
bootstrap flow.

Export:

```bash
export EDICTUM_URL=http://127.0.0.1:8080
export EDICTUM_API_KEY=edk_your_key_here
```

## Run

```bash
go run .
```

Compile-only check:

```bash
go build ./...
```

## Expected Result

The run should:
- trigger one blocked action during implementation
- request and auto-approve one review gate
- finish with `active_stage: "done"`
- print a JSON summary with `succeeded: true`
