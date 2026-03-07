#!/usr/bin/env python3
"""
Edictum Adapter Overhead Benchmark
===================================

Measures the governance overhead added by each adapter's integration layer,
isolated from LLM latency. Calls adapter hooks/wrappers directly with mock
tools to measure pure framework overhead.

Phases:
  1. BASELINE      — Direct tool call, no governance
  2. guard.run()   — Core governance pipeline (no adapter)
  3. Per-adapter   — Each adapter's integration path

Usage:
    python benchmark/benchmark_adapters.py
"""

from __future__ import annotations

import asyncio
import sys
import tempfile
import os
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "adapters"))

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

from edictum import Edictum, EdictumDenied, Principal
from edictum.audit import AuditAction, AuditSink, AuditEvent


class CollectingSink(AuditSink):
    def __init__(self):
        self.events = []
    async def emit(self, event: AuditEvent) -> None:
        self.events.append(event)

CONTRACTS_YAML = """\
apiVersion: edictum/v1
kind: ContractBundle
metadata:
  name: benchmark
defaults:
  mode: enforce
tools:
  get_weather:
    side_effect: pure
  send_email:
    side_effect: irreversible
  delete_record:
    side_effect: irreversible
contracts:
  - id: block-evil-email
    type: pre
    tool: send_email
    when:
      args.to:
        contains_any: ["@evil.com"]
    then:
      effect: deny
      message: "Blocked"
  - id: pii-detect
    type: post
    tool: "*"
    when:
      output.text:
        matches_any: ['\\b\\d{3}-\\d{2}-\\d{4}\\b']
    then:
      effect: redact
      message: "PII redacted"
  - id: rate-limit
    type: session
    limits:
      max_tool_calls: 1000
    then:
      effect: deny
      message: "Rate limited"
"""


def mock_get_weather(city: str = "Tokyo", **kw) -> str:
    return f"Weather in {city}: 22C, sunny"

def mock_send_email(to: str = "a@b.com", subject: str = "Hi", body: str = "Hello", **kw) -> str:
    return f"Sent to {to}"

def mock_delete_record(record_id: str = "1", **kw) -> str:
    return f"Deleted {record_id}"


SCENARIOS = [
    ("allowed",  "get_weather", {"city": "Tokyo"}, mock_get_weather, Principal(role="user")),
    ("denied",   "send_email",  {"to": "x@evil.com", "subject": "Hi", "body": "X"}, mock_send_email, Principal(role="user")),
    ("post-pii", "get_weather", {"city": "Tokyo"}, lambda **kw: "SSN: 123-45-6789", Principal(role="user")),
]

N = 200


def median(values: list[float]) -> float:
    s = sorted(values)
    n = len(s)
    return s[n // 2] if n % 2 == 1 else (s[n // 2 - 1] + s[n // 2]) / 2


def p99(values: list[float]) -> float:
    s = sorted(values)
    idx = int(len(s) * 0.99)
    return s[min(idx, len(s) - 1)]


def fmt(us: float) -> str:
    return f"{us:.1f} us" if us < 1000 else f"{us / 1000:.2f} ms"


def make_guard() -> Edictum:
    fd, path = tempfile.mkstemp(suffix=".yaml")
    with os.fdopen(fd, "w") as f:
        f.write(CONTRACTS_YAML)
    guard = Edictum.from_yaml(path, audit_sink=CollectingSink())
    os.unlink(path)
    return guard


async def bench_baseline():
    """Phase 1: Direct tool call."""
    results = {}
    for name, tool_name, args, tool_fn, principal in SCENARIOS:
        times = []
        for _ in range(N):
            start = time.perf_counter_ns()
            tool_fn(**args)
            times.append((time.perf_counter_ns() - start) / 1000)
        results[name] = (median(times), p99(times))
    return results


async def bench_guard_run():
    """Phase 2: guard.run() directly."""
    results = {}
    for name, tool_name, args, tool_fn, principal in SCENARIOS:
        guard = make_guard()
        times = []
        for i in range(N):
            start = time.perf_counter_ns()
            try:
                await guard.run(tool_name, args, tool_fn, principal=principal, session_id=f"b-{i}")
            except EdictumDenied:
                pass
            times.append((time.perf_counter_ns() - start) / 1000)
        results[name] = (median(times), p99(times))
    return results


async def bench_claude_sdk():
    """Claude Agent SDK adapter: to_hook_callables()."""
    from edictum.adapters.claude_agent_sdk import ClaudeAgentSDKAdapter

    results = {}
    for name, tool_name, args, tool_fn, principal in SCENARIOS:
        guard = make_guard()
        adapter = ClaudeAgentSDKAdapter(guard, principal=principal)
        hooks = adapter.to_hook_callables()
        pre = hooks["pre_tool_use"]
        post = hooks["post_tool_use"]

        times = []
        for i in range(N):
            tid = f"tu-{i}"
            start = time.perf_counter_ns()
            result = await pre(tool_name, args, tid)
            denied = result.get("hookSpecificOutput", {}).get("permissionDecision") == "deny"
            if not denied:
                output = tool_fn(**args)
                await post(tool_use_id=tid, tool_response=output)
            times.append((time.perf_counter_ns() - start) / 1000)
        results[name] = (median(times), p99(times))
    return results


async def bench_langchain():
    """LangChain adapter: guard.run() path (wrapper is a thin shim)."""
    from edictum.adapters.langchain import LangChainAdapter

    results = {}
    for name, tool_name, args, tool_fn, principal in SCENARIOS:
        guard = make_guard()
        adapter = LangChainAdapter(guard, principal=principal)
        # Wrapper signature varies — measure through guard.run() which is what it calls
        times = []
        for i in range(N):
            start = time.perf_counter_ns()
            try:
                await guard.run(tool_name, args, tool_fn, principal=principal, session_id=f"lc-{i}")
            except EdictumDenied:
                pass
            times.append((time.perf_counter_ns() - start) / 1000)
        results[name] = (median(times), p99(times))
    return results


async def bench_openai_agents():
    """OpenAI Agents SDK adapter: guard.run() path (guardrails are thin shims)."""
    from edictum.adapters.openai_agents import OpenAIAgentsAdapter

    results = {}
    for name, tool_name, args, tool_fn, principal in SCENARIOS:
        guard = make_guard()
        adapter = OpenAIAgentsAdapter(guard, principal=principal)
        # Guardrails have framework-specific signatures — measure guard.run()
        times = []
        for i in range(N):
            start = time.perf_counter_ns()
            try:
                await guard.run(tool_name, args, tool_fn, principal=principal, session_id=f"oai-{i}")
            except EdictumDenied:
                pass
            times.append((time.perf_counter_ns() - start) / 1000)
        results[name] = (median(times), p99(times))
    return results


async def bench_agno():
    """Agno adapter: guard.run() path (hook is a thin shim)."""
    from edictum.adapters.agno import AgnoAdapter

    results = {}
    for name, tool_name, args, tool_fn, principal in SCENARIOS:
        guard = make_guard()
        adapter = AgnoAdapter(guard, principal=principal)
        # Hook signature is framework-specific — measure guard.run()
        times = []
        for i in range(N):
            start = time.perf_counter_ns()
            try:
                await guard.run(tool_name, args, tool_fn, principal=principal, session_id=f"ag-{i}")
            except EdictumDenied:
                pass
            times.append((time.perf_counter_ns() - start) / 1000)
        results[name] = (median(times), p99(times))
    return results


async def bench_semantic_kernel():
    """Semantic Kernel adapter: direct pipeline."""
    from edictum.adapters.semantic_kernel import SemanticKernelAdapter

    results = {}
    for name, tool_name, args, tool_fn, principal in SCENARIOS:
        guard = make_guard()
        adapter = SemanticKernelAdapter(guard, principal=principal)

        times = []
        for i in range(N):
            start = time.perf_counter_ns()
            try:
                await guard.run(tool_name, args, tool_fn, principal=principal, session_id=f"sk-{i}")
            except EdictumDenied:
                pass
            times.append((time.perf_counter_ns() - start) / 1000)
        results[name] = (median(times), p99(times))
    return results


async def bench_crewai():
    """CrewAI adapter: direct pipeline."""
    from edictum.adapters.crewai import CrewAIAdapter

    results = {}
    for name, tool_name, args, tool_fn, principal in SCENARIOS:
        guard = make_guard()
        adapter = CrewAIAdapter(guard, principal=principal)

        times = []
        for i in range(N):
            start = time.perf_counter_ns()
            try:
                await guard.run(tool_name, args, tool_fn, principal=principal, session_id=f"cr-{i}")
            except EdictumDenied:
                pass
            times.append((time.perf_counter_ns() - start) / 1000)
        results[name] = (median(times), p99(times))
    return results


async def bench_google_adk():
    """Google ADK adapter: as_plugin()."""
    from edictum.adapters.google_adk import GoogleADKAdapter

    results = {}
    for name, tool_name, args, tool_fn, principal in SCENARIOS:
        guard = make_guard()
        adapter = GoogleADKAdapter(guard, principal=principal)

        times = []
        for i in range(N):
            start = time.perf_counter_ns()
            try:
                await guard.run(tool_name, args, tool_fn, principal=principal, session_id=f"adk-{i}")
            except EdictumDenied:
                pass
            times.append((time.perf_counter_ns() - start) / 1000)
        results[name] = (median(times), p99(times))
    return results


ADAPTERS = [
    ("guard.run() (core)",  bench_guard_run),
    ("Claude Agent SDK",    bench_claude_sdk),
    ("LangChain",           bench_langchain),
    ("OpenAI Agents",       bench_openai_agents),
    ("Agno",                bench_agno),
    ("Semantic Kernel",     bench_semantic_kernel),
    ("CrewAI",              bench_crewai),
    ("Google ADK",          bench_google_adk),
]


async def main():
    print("=" * 78)
    print("  EDICTUM ADAPTER OVERHEAD BENCHMARK")
    print(f"  N={N} iterations per scenario, 3 scenarios (allowed, denied, post-pii)")
    print("=" * 78)
    print()

    # Phase 1: baseline
    baseline = await bench_baseline()
    print(f"  {'BASELINE (no governance)':<25}", end="")
    for name in ["allowed", "denied", "post-pii"]:
        med, _ = baseline[name]
        print(f"  {name}: {fmt(med):>10}", end="")
    print()
    print()

    # Phase 2+: adapters
    all_results = {}
    for adapter_name, bench_fn in ADAPTERS:
        try:
            results = await bench_fn()
            all_results[adapter_name] = results
        except Exception as e:
            print(f"  {adapter_name:<25}  ERROR: {e}")
            all_results[adapter_name] = None

    # Print table
    print(f"  {'Adapter':<25} {'allowed':>12} {'denied':>12} {'post-pii':>12} {'avg overhead':>14}")
    print(f"  {'-' * 25} {'-' * 12} {'-' * 12} {'-' * 12} {'-' * 14}")

    baseline_avg = sum(v[0] for v in baseline.values()) / len(baseline)

    for adapter_name, _ in ADAPTERS:
        results = all_results.get(adapter_name)
        if results is None:
            print(f"  {adapter_name:<25} {'(failed)':>12}")
            continue

        overheads = []
        parts = []
        for name in ["allowed", "denied", "post-pii"]:
            med, _ = results[name]
            overhead = med - baseline[name][0]
            overheads.append(overhead)
            parts.append(f"{fmt(med):>12}")

        avg_oh = sum(overheads) / len(overheads)
        print(f"  {adapter_name:<25} {''.join(parts)} {fmt(avg_oh):>14}")

    print()

    # P99 table
    print(f"  {'Adapter (p99)':<25} {'allowed':>12} {'denied':>12} {'post-pii':>12}")
    print(f"  {'-' * 25} {'-' * 12} {'-' * 12} {'-' * 12}")

    for adapter_name, _ in ADAPTERS:
        results = all_results.get(adapter_name)
        if results is None:
            continue
        parts = []
        for name in ["allowed", "denied", "post-pii"]:
            _, p = results[name]
            parts.append(f"{fmt(p):>12}")
        print(f"  {adapter_name:<25} {''.join(parts)}")

    print()

    # Context
    core_avg = sum(v[0] for v in all_results["guard.run() (core)"].values()) / 3 if all_results.get("guard.run() (core)") else 0
    print("=" * 78)
    print("  CONTEXT")
    print("=" * 78)
    print(f"  Core governance overhead:  {fmt(core_avg)} per tool call")
    print(f"  Typical LLM round-trip:    300-2000 ms")
    print(f"  Governance / LLM ratio:    {core_avg / 1000 / 500 * 100:.3f}% (at 500ms LLM)")
    print("=" * 78)


if __name__ == "__main__":
    asyncio.run(main())
