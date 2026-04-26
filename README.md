# Edictum Demo Repository

This repo contains demos that show how Edictum bounds AI agent agency across real workflows.

[Edictum](https://github.com/edictum-ai/edictum) is the agency control layer for production AI agents. Agent frameworks build the agent. Edictum bounds the agency.

Edictum turns documented agent profiles into executable runtime boundaries: ordered Workflow Gates, runtime rules, approvals, recorded evidence, and behavioral conformance audit trails.

Edictum makes any agency level defensible. Medium Agency is the enterprise demand center right now, but the demos also cover narrower and higher-risk profiles.

Measurement boundary: these demos show behavioral conformance to a declared profile. They do not replace output-quality evals for accuracy, relevance, coherence, or answer quality.

**Docs:** [docs.edictum.ai](https://docs.edictum.ai)
**PyPI:** [pypi.org/project/edictum](https://pypi.org/project/edictum/)

## Demo narrative

Without Edictum, the agent can jump ahead. With Edictum, the same agent must operate inside its declared profile.

## What's here

### Primary Demo: Workflow Gates

`demos/hero/` is the primary deterministic end-to-end demo for the agency-control story:
parent agent -> bounded child agent -> review reset -> approval -> `done`.

It demonstrates:

- read-before-write
- verification-before-push
- approval-before-critical-transition
- blocked action
- recorded evidence
- final behavioral conformance audit trail

Use it when you want to show ordered process, runtime enforcement, approvals,
lineage, and repeatability without depending on live LLM behavior.

Start here: `demos/hero/README.md`

### Agent Profiles

Real-world profiles demonstrating how Edictum turns declared agent behavior into runtime boundaries.

| Agent profile | Directory | Declared agency boundary |
|---------------|-----------|--------------------------|
| **Pharmacovigilance** | `scenarios/pharma/` | Read/write with sensitive data boundaries |
| **DevOps** | `scenarios/devops/` | Read/write with high-risk operation approvals |
| **Fintech** | `scenarios/fintech/` | Write limits and compliance reporting |
| **Customer Support** | `scenarios/customer-support/` | Medium Agency with refund approval threshold |

Each profile includes an Edictum-bounded agent and the same agent without Edictum for comparison.

### Framework Adapters

Same agency boundaries, 8 different agent frameworks. This proves Edictum is framework-agnostic.

| Framework | Demo |
|-----------|------|
| LangChain + LangGraph | `adapters/demo_langchain.py` |
| OpenAI Agents SDK | `adapters/demo_openai_agents.py` |
| Agno | `adapters/demo_agno.py` |
| Semantic Kernel | `adapters/demo_semantic_kernel.py` |
| CrewAI | `adapters/demo_crewai.py` |
| Google ADK | `adapters/demo_google_adk.py` |
| Claude Agent SDK | `adapters/demo_claude_agent_sdk.py` |
| Nanobot | *(on droplet)* |

### Workflow Gates SDK Demos

Two more deterministic single-agent demos prove the same Workflow Gates story
outside Python:

| Demo | Directory | Stack |
|------|-----------|-------|
| TypeScript Vercel AI SDK | `demos/ts-vercel-ai/` | `@edictum/vercel-ai` + `@edictum/server` |
| Go ADK-style adapter | `demos/go-adk/` | `adapter/adkgo` + `server` |

Both run against the same `workflows/coding-guard.yaml` file and end in `done`
with a blocked action, one approval, and a final workflow snapshot from the API.

### Hot Reload Test

Validates that runtime rule changes deployed via the console reach connected agents in
real time via SSE -- no agent restart needed. Fast, deterministic, no LLM calls.

```bash
python adapters/test_hot_reload.py                   # needs console on localhost:8000
python adapters/test_hot_reload.py --agents 5         # test with more concurrent agents
```

### Adversarial Testing

Tests whether runtime enforcement holds under adversarial conditions across multiple LLMs.

```bash
python adversarial/test_adversarial.py --model gpt-4.1
python adversarial/test_adversarial.py --model deepseek
python adversarial/test_adversarial.py --model qwen
```

### Benchmarks

```bash
python benchmark/benchmark_adapters.py         # Per-adapter overhead: ~43us across all 8
python benchmark/benchmark_latency.py          # End-to-end with real LLM calls
python benchmark/prompt_vs_rules.py            # Prompt engineering vs runtime rules
```

### Observability

OTel -> Grafana Cloud pipeline with pre-built dashboard. See `observability/README.md`.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Copy .env.example to .env and add your API keys
cp .env.example .env
```

Required API keys:
- `OPENAI_API_KEY` -- for GPT-4.1 agent demos (LangChain, OpenAI Agents, SK, CrewAI, Agno)
- `GEMINI_API_KEY` -- for Google ADK demo
- `ANTHROPIC_API_KEY` -- for Claude Agent SDK demo
- `OPENROUTER_API_KEY` -- for DeepSeek/Qwen adversarial tests and DevOps demos
- `EDICTUM_API_KEY` -- for edictum-console connected mode (optional)
- `OTEL_EXPORTER_OTLP_ENDPOINT` + `OTEL_EXPORTER_OTLP_HEADERS` -- for Grafana Cloud (optional)

## Quick start

```bash
# Run the primary deterministic Workflow Gates hero demo
# See demos/hero/README.md for the required local edictum-api setup first
.venv/bin/python -m demos.hero.run --summary

# Run a profile
python scenarios/pharma/pharma_agent.py
python scenarios/fintech/fintech_agent.py
python scenarios/customer-support/support_agent.py

# Run the deterministic TypeScript Workflow Gates demo
cd demos/ts-vercel-ai && pnpm install && pnpm start

# Run the deterministic Go Workflow Gates demo
cd demos/go-adk && go run .

# Run with a different role (blocked access)
python adapters/demo_langchain.py --role researcher

# Run in observe mode (log, don't block)
python adapters/demo_langchain.py --mode observe

# Run adversarial tests
python adversarial/test_adversarial.py

# Run benchmark
python benchmark/benchmark_latency.py
```

## Structure

```
edictum-demo/
  demos/hero/                   # Python Workflow Gates hero demo
  demos/ts-vercel-ai/           # TypeScript Workflow Gates demo
  demos/go-adk/                 # Go Workflow Gates demo
  scenarios/
    pharma/                     # Pharmacovigilance profile
    devops/                     # DevOps profile
    fintech/                    # Trading compliance profile
    customer-support/           # Customer support profile
  adapters/                     # 8 framework comparison demos
  adversarial/                  # Multi-model adversarial tests
  benchmark/                    # Adapter overhead + latency + prompt-vs-rules
  observability/                # OTel config + Grafana dashboard
  examples/                     # Claude Agent SDK demo
  workflows/                    # Shared Workflow Gates definitions
```

## Env vars

| Variable | Description |
|----------|-------------|
| `OPENAI_API_KEY` | OpenAI API key (LangChain, OpenAI Agents, SK, CrewAI, Agno, scenarios) |
| `GEMINI_API_KEY` | Google Gemini API key (Google ADK demo) |
| `ANTHROPIC_API_KEY` | Anthropic API key (Claude Agent SDK demo) |
| `OPENROUTER_API_KEY` | OpenRouter API key (DevOps, adversarial tests) |
| `EDICTUM_API_KEY` | API key for edictum-console connected mode |
| `EDICTUM_URL` | edictum-console server URL (default: `http://localhost:8000`) |
| `EDICTUM_ADMIN_EMAIL` | Console admin email for hot reload test (default: `admin@demo.test`) |
| `EDICTUM_ADMIN_PASSWORD` | Console admin password for hot reload test (default: `edictum2026`) |

> **Warning:** The default admin credentials above are for local demo/testing only. Never use default credentials in production. Always generate strong, unique passwords for any non-local deployment.

| Variable | Description |
|----------|-------------|
| `EDICTUM_MODEL` | Override LLM model for DevOps/SDK demos |
| `EDICTUM_OTEL_CONSOLE` | Set to `1` for console OTel output |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | OTLP endpoint for Grafana Cloud |
| `OTEL_EXPORTER_OTLP_HEADERS` | URL-encoded auth headers |
