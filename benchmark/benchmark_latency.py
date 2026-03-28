#!/usr/bin/env python3
"""
Edictum Latency Benchmark — Real LLM Calls
===========================================

Measures governance overhead precisely, then shows it in context of a
real OpenAI agent loop.

Four phases:
  1. BASELINE       — Direct tool call, no LLM, no governance (N=100, µs)
  2. GOVERNANCE ONLY — guard.run() around tool call, no LLM (N=100, ms)
  3. LLM CALL ONLY  — Single OpenAI API call, no tool execution (N=5, ms)
  4. END-TO-END     — OpenAI API + governed tool execution (N=5, seconds)

The key metric is Phase 2: the isolated governance overhead.
Phase 4 shows it's negligible compared to LLM latency.

Usage:
    python benchmark/benchmark_latency.py          # requires OPENAI_API_KEY
    python benchmark/benchmark_latency.py --quick   # skip LLM phases
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import tempfile
import time
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

from edictum import Edictum, EdictumDenied, Principal


# --- Mock clinical data -----------------------------------------------------------

TRIAL_SUMMARY = {
    "trial_id": "NCT-2024-7891",
    "phase": "Phase III",
    "indication": "Type 2 Diabetes Mellitus",
    "compound": "CG-4582",
    "status": "Active, enrolling",
    "sites": 42,
    "enrolled": 1847,
}

ADVERSE_EVENTS_DETAILED = [
    {
        "event_id": "AE-003-017",
        "patient": "PAT-28491",
        "narrative": "Patient PAT-28491, Margaret Chen, age 67. Patient SSN 847-29-1038.",
    },
]


def query_clinical_data(dataset: str, **kwargs: object) -> str:
    """Mock tool that returns clinical data by dataset name."""
    if dataset == "trial_summary":
        return json.dumps(TRIAL_SUMMARY, indent=2)
    elif dataset == "adverse_events_detailed":
        return json.dumps(ADVERSE_EVENTS_DETAILED, indent=2)
    else:
        return json.dumps({"error": f"Unknown dataset: {dataset}"})


# --- OpenAI tool schema -----------------------------------------------------------

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "query_clinical_data",
            "description": (
                "Query clinical trial databases. "
                "Available datasets: trial_summary, adverse_events_summary, adverse_events_detailed"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "dataset": {"type": "string", "description": "Which dataset to query"},
                },
                "required": ["dataset"],
            },
        },
    },
]


# --- YAML rules (inline) ------------------------------------------------------

CONTRACTS_YAML = """\
apiVersion: edictum/v1
kind: Ruleset

metadata:
  name: benchmark-rules
  description: Inline rules for latency benchmarking

defaults:
  mode: enforce

observability:
  stdout: false

rules:
  - id: restrict-patient-data
    type: pre
    tool: query_clinical_data
    when:
      all:
        - args.dataset: { in: [adverse_events_detailed, patient_records] }
        - principal.role: { not_in: [pharmacovigilance, clinical_data_manager] }
    then:
      effect: deny
      message: "Access to {args.dataset} requires pharmacovigilance role."
      tags: [access-control]

  - id: pii-detection
    type: post
    tool: "*"
    when:
      output.text: { matches: '\\b\\d{3}-\\d{2}-\\d{4}\\b' }
    then:
      effect: warn
      message: "Possible SSN detected in output"
      tags: [pii]

  - id: session-limits
    type: session
    limits:
      max_tool_calls: 50
    then:
      effect: deny
      message: "Session limit exceeded"
"""


# --- Scenarios --------------------------------------------------------------------

SCENARIOS = [
    {
        "name": "Query allowed (pharma role)",
        "dataset": "trial_summary",
        "principal": Principal(role="pharmacovigilance"),
        "expected": "ALLOWED",
        "llm_prompt": {
            "system": "You are a pharmacovigilance assistant. Use query_clinical_data to answer.",
            "user": "Get the trial summary for the active clinical trial.",
        },
    },
    {
        "name": "Query denied (researcher)",
        "dataset": "adverse_events_detailed",
        "principal": Principal(role="researcher"),
        "expected": "DENIED",
        "llm_prompt": {
            "system": "You are a research assistant. Use query_clinical_data to answer.",
            "user": "Get the detailed adverse events data.",
        },
    },
    {
        "name": "Allowed + PII warning",
        "dataset": "adverse_events_detailed",
        "principal": Principal(role="pharmacovigilance"),
        "expected": "ALLOWED+PII_WARN",
        "llm_prompt": {
            "system": "You are a pharmacovigilance assistant. Use query_clinical_data to answer.",
            "user": "Get the detailed adverse events data.",
        },
    },
]


# --- Helpers ----------------------------------------------------------------------

def write_temp_yaml() -> str:
    fd, path = tempfile.mkstemp(suffix=".yaml")
    with os.fdopen(fd, "w") as f:
        f.write(CONTRACTS_YAML)
    return path


def fmt_us(us: float) -> str:
    if us < 1000:
        return f"{us:.1f} us"
    else:
        return f"{us / 1000:.2f} ms"


def median(values: list[float]) -> float:
    s = sorted(values)
    n = len(s)
    if n % 2 == 1:
        return s[n // 2]
    return (s[n // 2 - 1] + s[n // 2]) / 2


# gpt-4.1 pricing (USD per 1M tokens)
PRICE_INPUT = 2.00
PRICE_OUTPUT = 8.00


def token_cost(prompt_tokens: int, completion_tokens: int) -> float:
    return (prompt_tokens * PRICE_INPUT + completion_tokens * PRICE_OUTPUT) / 1_000_000


# --- Benchmark --------------------------------------------------------------------

async def benchmark(skip_llm: bool = False):
    yaml_path = write_temp_yaml()

    N_LOCAL = 100
    N_LLM = 15

    try:
        # ==================================================================
        # Phase 1: BASELINE — direct tool call, no LLM, no governance
        # ==================================================================
        print("=" * 70)
        print(f"  Phase 1: BASELINE — direct tool call (N={N_LOCAL})")
        print("=" * 70)
        print()

        baseline_us: dict[str, float] = {}

        for s in SCENARIOS:
            times_ns = []
            for _ in range(N_LOCAL):
                start = time.perf_counter_ns()
                query_clinical_data(dataset=s["dataset"])
                times_ns.append(time.perf_counter_ns() - start)

            med_us = median(times_ns) / 1000
            baseline_us[s["name"]] = med_us
            print(f"  {s['name']:<35} {fmt_us(med_us):>10}")

        print()

        # ==================================================================
        # Phase 2: GOVERNANCE ONLY — guard.run() around tool, no LLM
        # ==================================================================
        print("=" * 70)
        print(f"  Phase 2: GOVERNANCE ONLY — guard.run() + tool (N={N_LOCAL})")
        print(f"  This isolates the pure governance overhead.")
        print("=" * 70)
        print()

        governed_us: dict[str, float] = {}

        for s in SCENARIOS:
            guard = Edictum.from_yaml(yaml_path)
            times_ns = []

            for i in range(N_LOCAL):
                start = time.perf_counter_ns()
                try:
                    await guard.run(
                        tool_name="query_clinical_data",
                        args={"dataset": s["dataset"]},
                        tool_callable=query_clinical_data,
                        principal=s["principal"],
                        session_id=f"bench-{i}",
                    )
                except EdictumDenied:
                    pass
                times_ns.append(time.perf_counter_ns() - start)

            med_us = median(times_ns) / 1000
            governed_us[s["name"]] = med_us
            overhead_us = med_us - baseline_us[s["name"]]
            print(f"  {s['name']:<35} {fmt_us(med_us):>10}  (overhead: {fmt_us(overhead_us)})")

        print()

        # ==================================================================
        # Governance overhead summary
        # ==================================================================
        print("=" * 70)
        print("  GOVERNANCE OVERHEAD (Phase 2 - Phase 1)")
        print("=" * 70)
        print()

        overheads_us = []
        for s in SCENARIOS:
            name = s["name"]
            base = baseline_us[name]
            gov = governed_us[name]
            overhead = gov - base
            overheads_us.append(overhead)
            print(f"  {name:<35}  baseline {fmt_us(base):>10}  governed {fmt_us(gov):>10}  overhead {fmt_us(overhead):>10}")

        avg_overhead_us = sum(overheads_us) / len(overheads_us)
        print()
        print(f"  Average governance overhead: {fmt_us(avg_overhead_us)}")
        print()

        if not skip_llm:
            if not os.getenv("OPENAI_API_KEY"):
                print("  Skipping LLM phases: OPENAI_API_KEY not set")
                print("=" * 70)
                return

            from openai import OpenAI
            client = OpenAI()

            # ==================================================================
            # Phase 3: LLM CALL ONLY — measure API latency baseline
            # ==================================================================
            print("=" * 70)
            print(f"  Phase 3: LLM CALL ONLY — OpenAI API round-trip (N={N_LLM})")
            print("=" * 70)
            print()

            llm_times_ms = []
            total_prompt = 0
            total_completion = 0
            for i in range(N_LLM):
                start = time.perf_counter()
                resp = client.chat.completions.create(
                    model="gpt-4.1",
                    messages=[
                        {"role": "system", "content": SCENARIOS[0]["llm_prompt"]["system"]},
                        {"role": "user", "content": SCENARIOS[0]["llm_prompt"]["user"]},
                    ],
                    tools=TOOLS,
                    max_tokens=200,
                )
                elapsed_ms = (time.perf_counter() - start) * 1000
                llm_times_ms.append(elapsed_ms)
                u = resp.usage
                total_prompt += u.prompt_tokens
                total_completion += u.completion_tokens
                print(f"    Run {i + 1}: {elapsed_ms:>6.0f} ms  ({u.prompt_tokens}+{u.completion_tokens} tokens)")

            med_llm_ms = median(llm_times_ms)
            p3_cost = token_cost(total_prompt, total_completion)
            print(f"\n  Median LLM round-trip: {med_llm_ms:.0f} ms")
            print(f"  Tokens (phase 3):     {total_prompt} prompt + {total_completion} completion = {total_prompt + total_completion}")
            print(f"  Cost (phase 3):       ${p3_cost:.4f}")
            print()

            # ==================================================================
            # Phase 4: END-TO-END — LLM + governed tool for each scenario
            # ==================================================================
            print("=" * 70)
            print(f"  Phase 4: END-TO-END — LLM + governed tool (N={N_LLM})")
            print("=" * 70)
            print()

            p4_prompt = 0
            p4_completion = 0
            for s in SCENARIOS:
                guard = Edictum.from_yaml(yaml_path)
                times_ms = []

                for i in range(N_LLM):
                    session_id = f"e2e-{s['name']}-{i}"
                    start = time.perf_counter()

                    response = client.chat.completions.create(
                        model="gpt-4.1",
                        messages=[
                            {"role": "system", "content": s["llm_prompt"]["system"]},
                            {"role": "user", "content": s["llm_prompt"]["user"]},
                        ],
                        tools=TOOLS,
                        max_tokens=200,
                    )

                    u = response.usage
                    p4_prompt += u.prompt_tokens
                    p4_completion += u.completion_tokens

                    choice = response.choices[0]
                    if choice.message.tool_calls:
                        for tc in choice.message.tool_calls:
                            args = json.loads(tc.function.arguments)
                            try:
                                await guard.run(
                                    tool_name=tc.function.name,
                                    args=args,
                                    tool_callable=query_clinical_data,
                                    principal=s["principal"],
                                    session_id=session_id,
                                )
                            except EdictumDenied:
                                pass

                    elapsed_ms = (time.perf_counter() - start) * 1000
                    times_ms.append(elapsed_ms)

                med_total = median(times_ms)
                gov_pct = (avg_overhead_us / 1000) / med_total * 100
                print(f"  {s['name']:<35}")
                print(f"    Median total:  {med_total:>8.0f} ms")
                print(f"    Governance:    {avg_overhead_us / 1000:>8.2f} ms  ({gov_pct:.2f}% of total)")
                print(f"    Expected:      {s['expected']}")
                print()

            p4_cost = token_cost(p4_prompt, p4_completion)

            # ==================================================================
            # Final summary
            # ==================================================================
            # ==============================================================
            # Final summary
            # ==============================================================
            grand_prompt = total_prompt + p4_prompt
            grand_completion = total_completion + p4_completion
            grand_cost = p3_cost + p4_cost
            total_calls = N_LLM + N_LLM * len(SCENARIOS)

            print("=" * 70)
            print("  SUMMARY")
            print("=" * 70)
            print()
            print(f"  Governance overhead:       {fmt_us(avg_overhead_us):>10}  (median, N={N_LOCAL})")
            print(f"  LLM round-trip:            {med_llm_ms:>7.0f} ms  (median, N={N_LLM})")
            print(f"  Governance / LLM:          {(avg_overhead_us / 1000) / med_llm_ms * 100:>7.2f} %")
            print()
            print(f"  ── Token Usage ──")
            print(f"  API calls:        {total_calls}")
            print(f"  Prompt tokens:    {grand_prompt:,}")
            print(f"  Completion tokens:{grand_completion:,}")
            print(f"  Total tokens:     {grand_prompt + grand_completion:,}")
            print(f"  Est. cost:        ${grand_cost:.4f}  (gpt-4.1 @ ${PRICE_INPUT}/1M in, ${PRICE_OUTPUT}/1M out)")
            print(f"  Cost per call:    ${grand_cost / total_calls:.5f}")
            print()
            print(f"  Edictum governance adds {fmt_us(avg_overhead_us)} per tool call.")
            print(f"  At {med_llm_ms:.0f} ms per LLM round-trip, that's {(avg_overhead_us / 1000) / med_llm_ms * 100:.2f}% overhead.")
            print("=" * 70)

        else:
            print("  --quick: LLM phases skipped")
            print("=" * 70)

    finally:
        os.unlink(yaml_path)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--quick", action="store_true", help="Skip LLM phases (local-only benchmark)")
    args = parser.parse_args()
    asyncio.run(benchmark(skip_llm=args.quick))
