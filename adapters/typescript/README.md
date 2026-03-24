# Edictum TypeScript Adapter Demos

Demonstrates runtime contract enforcement using `@edictum/core` with 4 framework adapters:

| Demo | Adapter | Integration Point |
|------|---------|-------------------|
| `demo-vercel-ai.ts` | `@edictum/vercel-ai` | `experimental_onToolCallStart` / `experimental_onToolCallFinish` |
| `demo-langchain.ts` | `@edictum/langchain` | `wrapToolCall` middleware for ToolNode |
| `demo-openai-agents.ts` | `@edictum/openai-agents` | `inputGuardrail` / `outputGuardrail` |
| `demo-claude-sdk.ts` | `@edictum/claude-sdk` | `PreToolUse` / `PostToolUse` hooks |

All demos share the same `contracts.yaml` (at `../contracts.yaml`) and exercise 16 governance scenarios: precondition denials, sandbox enforcement, RBAC, PII redaction, rate limiting, and more.

## Prerequisites

- Node.js 20+
- pnpm
- `edictum-ts` repo cloned alongside `edictum-demo`:
  ```
  project/
    edictum-demo/
    edictum-ts/
  ```

## Setup

1. Build edictum-ts first (assumes sibling repo layout):
   ```bash
   cd ../../../edictum-ts   # or wherever edictum-ts is cloned
   pnpm install
   pnpm build
   ```

   > **Note:** `package.json` uses `file:` references assuming `edictum-demo/` and
   > `edictum-ts/` are siblings under the same parent directory. If your layout
   > differs, adjust the paths in `package.json`.

2. Install demo dependencies:
   ```bash
   pnpm install
   ```

## Run

Run all 4 adapter demos:
```bash
pnpm demo:all
```

Run individual adapters:
```bash
pnpm demo:vercel-ai
pnpm demo:langchain
pnpm demo:openai-agents
pnpm demo:claude-sdk
```

## Expected Results

Each demo runs 16 scenarios (all non-approval scenarios) producing:
- 6 DENIED (sandbox violations, RBAC, evil email, sensitive files, rate limit)
- 1 REDACTED (PII in contacts.json output)
- 9 ALLOWED (weather x5, web search, safe files, safe email, confirmed update; observe-mode email audit fires but does not block)

## How It Works

Each demo:
1. Creates an `Edictum` guard from `contracts.yaml`
2. Shows the adapter setup code (how you would integrate with the real framework)
3. Runs governance scenarios using `guard.run()` (framework-agnostic pipeline test)
4. Classifies results from audit events
5. Prints a governance summary with pass/fail validation
