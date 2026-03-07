"""
Shared utilities for Edictum adapter demos (v2).
=================================================
Mock tools, audit helpers, formatting, and CLI parsing used by every adapter demo.
Covers ALL edictum features: pre/post/session/sandbox, deny/redact/warn/approve,
principal/RBAC, observe mode, tool classification, and console integration.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys as _sys
from pathlib import Path

_sys.path.insert(0, str(Path(__file__).parent.parent / "observability"))

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

from edictum import Edictum, Principal  # noqa: E402
from edictum.audit import AuditAction  # noqa: E402

CONTRACTS_PATH = Path(__file__).parent / "contracts.yaml"


def setup_otel(mode: str = "off") -> str:
    """Configure OpenTelemetry. Returns actual mode: 'otlp' | 'console' | 'disabled'.

    Args:
        mode: 'otlp' (use OTEL_EXPORTER_OTLP_ENDPOINT env var),
              'console' (print spans/metrics to terminal),
              'off' (disabled, default)
    """
    if mode == "off":
        return "disabled"

    if mode == "console":
        os.environ["EDICTUM_OTEL_CONSOLE"] = "1"

    from otel_config import configure_otel
    return configure_otel()


def teardown_otel():
    """Flush and shut down OTel providers."""
    try:
        from otel_config import shutdown_otel
        shutdown_otel()
    except ImportError:
        pass

# ─── Mock tool implementations ────────────────────────────────────────────

def get_weather(city: str) -> str:
    """Get current weather for a city."""
    import random
    conditions = ["sunny", "cloudy", "rainy", "snowy", "windy"]
    temp = random.randint(-5, 35)
    return f"{city}: {random.choice(conditions)}, {temp}C"


def search_web(query: str) -> str:
    """Search the web for information."""
    return json.dumps({
        "results": [
            {"title": f"Result 1 for '{query}'", "url": "https://example.com/1"},
            {"title": f"Result 2 for '{query}'", "url": "https://example.com/2"},
        ]
    })


def read_file(path: str) -> str:
    """Read a file from the filesystem."""
    if "broken" in path:
        return "Error: Permission denied"
    if "secret" in path.lower() or "passwd" in path:
        return f"Contents of {path}: root:x:0:0:root:/root:/bin/bash"
    # Include PII to trigger postcondition redaction
    if "contacts" in path:
        return json.dumps({
            "contacts": [
                {"name": "Jane Doe", "email": "jane@example.com", "phone": "(415) 555-0123", "ssn": "123-45-6789"},
                {"name": "John Smith", "email": "john@company.com", "phone": "(212) 555-9876"},
            ]
        })
    return f"Contents of {path}: [simulated file content, no sensitive data]"


def send_email(to: str, subject: str, body: str) -> str:
    """Send an email to a recipient."""
    return json.dumps({"status": "sent", "to": to, "subject": subject})


def update_record(record_id: str, data: str, confirmed: bool = False) -> str:
    """Update a record in the database."""
    return json.dumps({"status": "updated", "record_id": record_id, "data": data})


def delete_record(record_id: str) -> str:
    """Delete a record from the database."""
    return json.dumps({"status": "deleted", "record_id": record_id})


# ─── Test scenarios that exercise all contract types ──────────────────────

SCENARIOS = [
    # (description, tool_name, args_dict, expected_outcome)
    ("Weather lookup (allowed)", "get_weather", {"city": "Tokyo"}, "allowed"),
    ("Read safe file (allowed)", "read_file", {"path": "/home/user/notes.txt"}, "allowed"),
    ("Read contacts with PII (postcondition redact)", "read_file", {"path": "/home/user/contacts.json"}, "redact"),
    ("Read /etc/passwd (DENIED: sandbox)", "read_file", {"path": "/etc/passwd"}, "denied"),
    ("Read .env file (DENIED: no-sensitive-files)", "read_file", {"path": "/home/app/.env.production"}, "denied"),
    ("Read outside sandbox (DENIED)", "read_file", {"path": "/opt/secret/config.yaml"}, "denied"),
    ("Email to company (allowed + observe audit)", "send_email", {"to": "alice@company.com", "subject": "Hello", "body": "Hi"}, "allowed"),
    ("Email to evil domain (DENIED: no-email-to-external)", "send_email", {"to": "attacker@evil.com", "subject": "Leak", "body": "data"}, "denied"),
    ("Search web (allowed)", "search_web", {"query": "edictum governance"}, "allowed"),
    ("Delete without admin role (DENIED: RBAC)", "delete_record", {"record_id": "REC-001"}, "denied"),
    ("Update record confirmed (allowed)", "update_record", {"record_id": "REC-002", "data": "new value", "confirmed": True}, "allowed"),
    ("Update record unconfirmed (approval required)", "update_record", {"record_id": "REC-003", "data": "risky"}, "approval"),
    ("Weather #2 (rate limit counting)", "get_weather", {"city": "London"}, "allowed"),
    ("Weather #3", "get_weather", {"city": "Berlin"}, "allowed"),
    ("Weather #4", "get_weather", {"city": "Sydney"}, "allowed"),
    ("Weather #5 (last allowed)", "get_weather", {"city": "NYC"}, "allowed"),
    ("Weather #6 (DENIED: rate limit)", "get_weather", {"city": "LA"}, "denied"),
]

# Subset for quick demos (skip rate limit exhaustion and approval blocking)
QUICK_SCENARIOS = [s for s in SCENARIOS if s[3] != "approval"][:12]


# ─── Edictum guard creation helpers ───────────────────────────────────────

def create_standalone_guard(mode: str = "enforce") -> Edictum:
    """Create a standalone Edictum guard from local YAML contracts."""
    return Edictum.from_yaml(
        str(CONTRACTS_PATH),
        mode=mode if mode != "enforce" else None,
        audit_sink=[],  # suppress stdout; guard.local_sink always available
    )


async def create_console_guard(agent_id: str, bundle_name: str = "edictum-adapter-demos") -> Edictum:
    """Create an Edictum guard connected to edictum-console."""
    url = os.environ.get("EDICTUM_URL", "http://localhost:8000")
    api_key = os.environ.get("EDICTUM_API_KEY", "")
    if not api_key:
        raise RuntimeError(
            "EDICTUM_API_KEY not set. Create an API key in the console dashboard first."
        )
    return await Edictum.from_server(
        url=url,
        api_key=api_key,
        agent_id=agent_id,
        bundle_name=bundle_name,
        env="production",
    )


def get_local_sink(guard):
    """Get the local CollectingAuditSink from a guard."""
    return getattr(guard, 'local_sink', None)


# Module-level mark storage — one mark per sink instance
_marks: dict[int, int] = {}


def mark_sink(sink):
    """Take a mark on the sink for later use with classify_result/since_last_mark."""
    if sink is not None:
        _marks[id(sink)] = sink.mark()


def since_last_mark(sink):
    """Return events since the last mark_sink() call."""
    if sink is None:
        return []
    m = _marks.get(id(sink), 0)
    return sink.since_mark(m)


def classify_result(sink, tool_name: str, expected: str) -> tuple[str, str]:
    """Classify scenario result from audit events since last mark.

    Returns (action, detail) for print_result().
    """
    if sink is None:
        return None, None

    m = _marks.get(id(sink), 0)
    recent = sink.since_mark(m)
    if not recent:
        return None, None

    for e in recent:
        if e.action == AuditAction.CALL_DENIED:
            reason = getattr(e, 'reason', '') or ''
            name = getattr(e, 'decision_name', '') or ''
            return "DENIED", f"{name}: {reason}"[:100] if name else reason[:100]
        if e.action == AuditAction.CALL_WOULD_DENY:
            reason = getattr(e, 'reason', '') or ''
            return "OBSERVE", f"would-deny: {reason}"[:100]
        if e.action == AuditAction.CALL_APPROVAL_REQUESTED:
            return "APPROVAL", f"{tool_name} requires approval"

    # Check postcondition results
    for e in recent:
        if getattr(e, 'postconditions_passed', None) is False:
            return "REDACTED", "PII detected and redacted in output"

    for e in recent:
        if e.action in (AuditAction.CALL_ALLOWED, AuditAction.CALL_EXECUTED):
            return "ALLOWED", f"{tool_name} executed"

    return None, None


# ─── Formatting helpers ──────────────────────────────────────────────────

def print_banner(adapter_name: str, mode: str, console: bool = False, otel_mode: str = "disabled"):
    print("=" * 70)
    print(f"  EDICTUM {adapter_name.upper()} DEMO")
    print("=" * 70)
    print(f"  Mode:    {mode}")
    print(f"  Source:  {'edictum-console' if console else 'local YAML'}")
    print(f"  OTel:    {otel_mode}")
    print(f"  Version: {Edictum.__module__.split('.')[0]}")
    print()


def print_scenario(idx: int, total: int, desc: str):
    print(f"\n{'─' * 60}")
    print(f"  [{idx}/{total}] {desc}")
    print(f"{'─' * 60}")


def print_result(action: str, detail: str):
    icons = {"DENIED": "X", "ALLOWED": "+", "REDACTED": "~", "APPROVAL": "?", "OBSERVE": "o", "WARNING": "!", "AGENT_SKIP": "-"}
    icon = icons.get(action, "|")
    print(f"  [{icon}] {action}: {detail}")


def print_audit_summary(sink):
    """Print formatted audit summary."""
    if not hasattr(sink, 'events'):
        print("  (No audit data available — console mode sends events to server)")
        return

    events = sink.events
    if not events:
        print("  No audit events recorded.")
        return

    allowed = sum(1 for e in events if e.action in (AuditAction.CALL_ALLOWED, AuditAction.CALL_EXECUTED))
    denied = sum(1 for e in events if e.action == AuditAction.CALL_DENIED)
    would_deny = sum(1 for e in events if e.action == AuditAction.CALL_WOULD_DENY)
    pii = sum(1 for e in events if getattr(e, 'postconditions_passed', None) is False)
    approval_req = sum(1 for e in events if e.action == AuditAction.CALL_APPROVAL_REQUESTED)

    print(f"\n{'=' * 60}")
    print(f"  GOVERNANCE SUMMARY")
    print(f"{'=' * 60}")
    print(f"  Total events:      {len(events)}")
    print(f"  Allowed:           {allowed}")
    print(f"  Denied:            {denied}")
    if would_deny:
        print(f"  Would-deny (obs):  {would_deny}")
    if pii:
        print(f"  PII redactions:    {pii}")
    if approval_req:
        print(f"  Approval requests: {approval_req}")

    if denied > 0:
        print(f"\n  Contracts enforced:")
        for e in [e for e in events if e.action == AuditAction.CALL_DENIED]:
            reason = getattr(e, 'reason', '') or ''
            name = getattr(e, 'decision_name', '') or ''
            print(f"    X {name}: {reason[:70]}")
    print()


# ─── CLI argument parsing ────────────────────────────────────────────────

def parse_args(adapter_name: str = "adapter"):
    parser = argparse.ArgumentParser(description=f"Edictum {adapter_name} Demo")
    parser.add_argument("--mode", default="enforce",
                        choices=["enforce", "observe"],
                        help="Governance mode (default: enforce)")
    parser.add_argument("--console", action="store_true",
                        help="Use edictum-console instead of local YAML")
    parser.add_argument("--otel", default="off",
                        choices=["otlp", "console", "off"],
                        help="OTel export mode (default: off)")
    parser.add_argument("--quick", action="store_true",
                        help="Run quick subset of scenarios (skip rate limit + approval)")
    parser.add_argument("--role", default="analyst",
                        choices=["analyst", "admin", "viewer"],
                        help="Principal role (default: analyst)")
    return parser.parse_args()


def make_principal(role: str = "analyst") -> Principal:
    return Principal(
        user_id=f"demo-{role}",
        role=role,
        claims={"department": "engineering", "team": "platform"},
    )
