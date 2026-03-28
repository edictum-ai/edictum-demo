# Benchmarks

Performance measurement for Edictum behavior checks overhead.

## benchmark_adapters.py

Per-adapter overhead measurement across all 8 framework adapters. Tests 3 scenarios
(allowed, denied, postcondition) at N=200 iterations each, isolated from LLM latency.

```bash
python benchmark/benchmark_adapters.py
```

**Latest results (v0.13.0, Apple M-series):**

| Adapter | Median Overhead | p99 |
|---------|:-:|:-:|
| guard.run() (core) | 43.4 us | ~126 us |
| Claude Agent SDK | 42.8 us | ~107 us |
| LangChain | 42.7 us | ~117 us |
| OpenAI Agents | 42.5 us | ~132 us |
| Agno | 42.2 us | ~77 us |
| Semantic Kernel | 41.8 us | ~129 us |
| CrewAI | 41.6 us | ~119 us |
| Google ADK | 41.1 us | ~105 us |

All adapters add ~43us per tool call. The adapter layer adds zero measurable overhead
on top of the core check pipeline. At 43us vs 300-2000ms LLM round-trips,
checks add **0.009% of total latency**.

## benchmark_latency.py

End-to-end latency measurement with real OpenAI API calls. Measures 4 phases:

1. **Baseline** -- direct tool call (no LLM, no behavior checks)
2. **Check only** -- Edictum rule evaluation without LLM
3. **LLM only** -- OpenAI API call without behavior checks
4. **End-to-end** -- full agent loop with LLM + behavior checks

```bash
python benchmark/benchmark_latency.py
```

**Latest results:** ~43us check overhead = 0.009% of a typical LLM round-trip.

## prompt_vs_rules.py

A -> B -> C customer journey benchmark comparing three deployment stages:

- **A (Today)**: Bloated system prompt with behavior rules in natural language. LLM self-polices.
- **B (Day-one)**: Clean prompt, Edictum in observe mode. Full visibility, zero behavior change.
- **C (Production)**: Clean prompt, Edictum in enforce mode. Deterministic rule enforcement.

```bash
python benchmark/prompt_vs_rules.py               # all scenarios
python benchmark/prompt_vs_rules.py --quick        # default scenario only
python benchmark/prompt_vs_rules.py --runs 3       # repeat for non-determinism evidence
```

Requires `OPENAI_API_KEY` in `.env`.

## What the benchmarks prove

1. **Zero overhead** -- ~43us per tool call across all 8 adapters, 0.009% of LLM latency
2. **No adapter penalty** -- all adapters converge to the same ~43us; the framework integration layer is free
3. **Rules are deterministic** -- same input always produces the same behavior decision, unlike prompt engineering
4. **Deploy observe mode tomorrow** -- zero risk, full audit trail, then flip to enforce when confident
