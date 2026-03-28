# Edictum Demo Repository

Full scenario demos, adversarial tests, benchmarks, and observability setup for
[Edictum](https://github.com/edictum-ai/edictum) -- runtime contracts for AI agents.

**Docs:** [docs.edictum.ai](https://docs.edictum.ai)
**PyPI:** [pypi.org/project/edictum](https://pypi.org/project/edictum/)

## What's here

### Scenarios

Real-world governance scenarios demonstrating Edictum in different industries.

| Scenario | Directory | Description |
|----------|-----------|-------------|
| **Pharmacovigilance** | `scenarios/pharma/` | Clinical trial agent with patient data protection, change control, PII detection |
| **DevOps** | `scenarios/devops/` | Infrastructure agent with blast radius limits, secret protection |
| **Fintech** | `scenarios/fintech/` | Trading agent with trade limits, account access control, regulatory compliance |
| **Customer Support** | `scenarios/customer-support/` | Support agent with data minimization, refund limits, escalation control |

Each scenario includes a governed agent AND an unguarded baseline for comparison.

### Framework Adapters

Same governance contracts, 8 different agent frameworks. Proves Edictum is framework-agnostic.

| Framework | Demo | Adapter API |
|-----------|------|-------------|
| LangChain + LangGraph | `adapters/demo_langchain.py` | `adapter.as_tool_wrapper()` |
| OpenAI Agents SDK | `adapters/demo_openai_agents.py` | `adapter.as_guardrails()` |
| Agno | `adapters/demo_agno.py` | `adapter.as_tool_hook()` |
| Semantic Kernel | `adapters/demo_semantic_kernel.py` | `adapter.register(kernel)` |
| CrewAI | `adapters/demo_crewai.py` | `adapter.register()` |
| Google ADK | `adapters/demo_google_adk.py` | `adapter.as_plugin()` |
| Claude Agent SDK | `adapters/demo_claude_agent_sdk.py` | `adapter.to_hook_callables()` |
| Nanobot | *(on droplet)* | `GovernedToolRegistry` |

### Hot Reload Test

Validates that contract changes deployed via the console reach connected agents in
real-time via SSE -- no agent restart needed. Fast, deterministic, no LLM calls.

```bash
python adapters/test_hot_reload.py                   # needs console on localhost:8000
python adapters/test_hot_reload.py --agents 5         # test with more concurrent agents
```

### Adversarial Testing

Tests whether governance holds under adversarial conditions across multiple LLMs.

```bash
python adversarial/test_adversarial.py --model gpt-4.1
python adversarial/test_adversarial.py --model deepseek
python adversarial/test_adversarial.py --model qwen
```

### Benchmarks

```bash
python benchmark/benchmark_adapters.py         # Per-adapter overhead: ~43us across all 8
python benchmark/benchmark_latency.py          # End-to-end with real LLM calls
python benchmark/prompt_vs_rules.py         # Prompt engineering vs contracts
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
# Run a scenario
python scenarios/pharma/pharma_agent.py
python scenarios/fintech/fintech_agent.py
python scenarios/customer-support/support_agent.py

# Run with a different role (denied access)
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
  scenarios/
    pharma/                     # Clinical trial pharmacovigilance
    devops/                     # File organizer with blast radius limits
    fintech/                    # Trading compliance
    customer-support/           # Support agent with data minimization
  adapters/                     # 8 framework comparison demos
  adversarial/                  # Multi-model adversarial tests
  benchmark/                    # Adapter overhead + latency + prompt-vs-contracts
  observability/                # OTel config + Grafana dashboard
  docs/                         # Adapter development insights
  examples/                     # Claude Agent SDK demo
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
| `EDICTUM_MODEL` | Override LLM model for DevOps/SDK demos |
| `EDICTUM_OTEL_CONSOLE` | Set to `1` for console OTel output |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | OTLP endpoint for Grafana Cloud |
| `OTEL_EXPORTER_OTLP_HEADERS` | URL-encoded auth headers |
