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

### Direct mode (no API key needed)

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

### LLM mode (requires OpenAI API key)

LLM mode sends real prompts to `gpt-4.1-mini` so the LLM decides which tool to call, then governance intercepts the call. This demonstrates the full end-to-end flow: **LLM -> adapter -> governance -> tool -> result**.

Set your API key in `../../.env` or as an environment variable:
```bash
export OPENAI_API_KEY=sk-...
```

Run all demos with LLM integration:
```bash
pnpm demo:all:llm
```

Run individual adapters with LLM:
```bash
pnpm demo:vercel-ai:llm
pnpm demo:langchain:llm
pnpm demo:openai-agents:llm
pnpm demo:claude-sdk:llm
```

#### How LLM mode works

- **Vercel AI demo** (native integration): Uses `generateText()` with `adapter.asCallbacks()` spread into the options. The adapter's `experimental_onToolCallStart` fires the precondition check, and `experimental_onToolCallFinish` fires the postcondition check. Denials throw `EdictumDenied` which aborts the tool execution.

- **LangChain / OpenAI Agents / Claude SDK demos** (guard.run integration): The LLM chooses which tool to call via `generateText()`, then the tool call is passed through `guard.run()` for governance enforcement. This proves the flow works end-to-end without requiring each framework's full SDK.

If `OPENAI_API_KEY` is not set when `--llm` is passed, the demos print a warning and fall back to direct mode.

## Expected Results

Each demo runs 16 scenarios (all non-approval scenarios) producing:
- 8 DENIED (sandbox violations x3, RBAC, evil email, sensitive files x2, rate limit)
- 8 ALLOWED (weather x5, web search, safe email, confirmed update; observe-mode email audit fires but does not block)

> **Note:** Scenarios 2 and 3 (read safe file, read contacts) are DENIED due to a
> sandbox wiring bug in the YAML compiler -- sandbox contracts always deny because
> the compiled stub is never replaced with actual path checking. In Python, these
> produce ALLOWED and REDACTED respectively.

## How It Works

Each demo:
1. Creates an `Edictum` guard from `contracts.yaml`
2. Shows the adapter setup code (how you would integrate with the real framework)
3. Runs governance scenarios (via `guard.run()` in direct mode, or via LLM in `--llm` mode)
4. Classifies results from audit events
5. Prints a governance summary with pass/fail validation
