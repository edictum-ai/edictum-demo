# TypeScript Workflow Gates Demo

Deterministic single-agent Workflow Gates demo using the Vercel AI SDK adapter.

It uses:
- `@edictum/core`
- `@edictum/server`
- `@edictum/vercel-ai`
- the shared [`coding-guard.yaml`](../../workflows/coding-guard.yaml) workflow

This demo does not call a real LLM. It drives tool calls programmatically so the
run is repeatable.

## Setup

Start the local API first. Use [`demos/hero/README.md`](../hero/README.md) for the
bootstrap flow.

Then create a local env file:

```bash
cp .env.example .env
```

Set:

```bash
EDICTUM_URL=http://127.0.0.1:8080
EDICTUM_API_KEY=edk_your_key_here
```

## Run

```bash
pnpm install
pnpm start
```

Compile-only check:

```bash
pnpm build
```

## Expected Result

The run should:
- trigger one blocked action during implementation
- request and auto-approve one review gate
- finish with `active_stage: "done"`
- print a JSON summary with `succeeded: true`
