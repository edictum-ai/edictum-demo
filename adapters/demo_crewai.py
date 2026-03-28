"""
Edictum CrewAI Adapter Demo
============================

Demonstrates Edictum governance using the CrewAI adapter with global
before/after tool-call hooks. Exercises ALL contract types: pre/post/
session/sandbox, deny/redact/warn/approve, principal/RBAC, observe mode,
tool classification, and console integration.

Usage:
    python adapters/demo_crewai.py
    python adapters/demo_crewai.py --mode observe
    python adapters/demo_crewai.py --console
    python adapters/demo_crewai.py --quick --role admin
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from edictum import Edictum
from edictum.adapters.crewai import CrewAIAdapter
from edictum.approval import LocalApprovalBackend
from crewai import Agent, Task, Crew
from crewai.tools import tool as crewai_tool

sys.path.insert(0, str(Path(__file__).parent))

from shared_v2 import (  # noqa: E402
    get_weather as _get_weather,
    search_web as _search_web,
    read_file as _read_file,
    send_email as _send_email,
    update_record as _update_record,
    delete_record as _delete_record,
    RULES_PATH,
    SCENARIOS,
    QUICK_SCENARIOS,
    create_console_guard,
    classify_result,
    mark_sink,
    get_local_sink,
    parse_args,
    make_principal,
    print_banner,
    print_scenario,
    print_result,
    print_audit_summary,
)


# ─── CrewAI tool wrappers ──────────────────────────────────────────────────
# CrewAI normalizes tool names: the @crewai_tool decorator name becomes the
# tool's display name, but the function name is what matters for contracts.
# Using snake_case function names ensures they match contract tool names
# after CrewAIAdapter._normalize_tool_name() processing.

@crewai_tool
def get_weather(city: str) -> str:
    """Get current weather for a city."""
    return _get_weather(city)


@crewai_tool
def search_web(query: str) -> str:
    """Search the web for information."""
    return _search_web(query)


@crewai_tool
def read_file(path: str) -> str:
    """Read a file from the filesystem."""
    return _read_file(path)


@crewai_tool
def send_email(to: str, subject: str, body: str) -> str:
    """Send an email to a recipient."""
    return _send_email(to, subject, body)


@crewai_tool
def update_record(record_id: str, data: str, confirmed: bool = False) -> str:
    """Update a record in the database."""
    return _update_record(record_id, data, confirmed)


@crewai_tool
def delete_record(record_id: str) -> str:
    """Delete a record from the database."""
    return _delete_record(record_id)


ALL_TOOLS = [get_weather, search_web, read_file, send_email, update_record, delete_record]

TOOL_MAP = {
    "get_weather": get_weather,
    "search_web": search_web,
    "read_file": read_file,
    "send_email": send_email,
    "update_record": update_record,
    "delete_record": delete_record,
}


# ─── Main ───────────────────────────────────────────────────────────────────

async def main():
    args = parse_args("CrewAI")
    principal = make_principal(args.role)
    scenarios = QUICK_SCENARIOS if args.quick else SCENARIOS

    # ── Create governance guard ──────────────────────────────────────────
    if args.console:
        guard = await create_console_guard(agent_id="edictum-crewai-agent")
    else:
        guard = Edictum.from_yaml(
            str(RULES_PATH),
            mode="observe" if args.mode == "observe" else None,
        )
    sink = get_local_sink(guard)

    # ── CrewAI adapter ───────────────────────────────────────────────────
    adapter = CrewAIAdapter(guard, principal=principal)

    pii_warnings: list[dict] = []

    def on_postcondition_warn(result, findings):
        pii_warnings.append({"findings": [f.message for f in findings]})

    adapter.register(on_postcondition_warn=on_postcondition_warn)

    # ── Agent ────────────────────────────────────────────────────────────
    agent = Agent(
        role="Assistant",
        goal="Execute tool calls as instructed",
        backstory="You are a helpful assistant that follows instructions precisely.",
        tools=ALL_TOOLS,
        llm="gpt-4.1-mini",
        verbose=False,
    )

    # ── Banner ───────────────────────────────────────────────────────────
    print_banner("CrewAI", args.mode, console=args.console)

    # ── Run scenarios ────────────────────────────────────────────────────
    for i, (desc, tool_name, tool_args, expected) in enumerate(scenarios, 1):
        print_scenario(i, len(scenarios), desc)

        args_str = ", ".join(
            f'{k}="{v}"' if isinstance(v, str) else f"{k}={v}"
            for k, v in tool_args.items()
        )
        prompt = (
            f"Call the {tool_name} tool with these exact arguments: {args_str}. "
            f"Do not call any other tools."
        )

        mark_sink(sink)

        try:
            task = Task(
                description=prompt,
                expected_output="The tool result",
                agent=agent,
            )
            crew = Crew(agents=[agent], tasks=[task], verbose=False)
            result = crew.kickoff()

            # Use audit-based classification first, fallback to output parsing
            action, detail = classify_result(sink, tool_name, expected)
            if action:
                print_result(action, detail)
            else:
                output = str(result.raw) if hasattr(result, "raw") else str(result)
                if output.startswith("DENIED:"):
                    print_result("DENIED", output[7:].strip())
                elif "[REDACTED]" in output:
                    print_result("REDACTED", "PII detected and redacted in output")
                elif expected == "approval":
                    print_result("APPROVAL", output[:100])
                else:
                    print_result("ALLOWED", f"{tool_name} executed")
        except Exception as e:
            err = str(e)[:100]
            if expected == "approval":
                print_result("APPROVAL", err)
            else:
                print_result("DENIED", err)

    # ── PII warnings ────────────────────────────────────────────────────
    if pii_warnings:
        print(f"\n{'─' * 60}")
        print("  PII WARNINGS")
        print(f"{'─' * 60}")
        for idx, w in enumerate(pii_warnings, 1):
            for finding in w["findings"]:
                print(f"  {idx}. {finding}")

    # ── Summary ──────────────────────────────────────────────────────────
    if sink:
        print_audit_summary(sink)
    else:
        print(f"\n{'=' * 60}")
        print("  (Audit events sent to edictum-console)")

    # ── Cleanup ──────────────────────────────────────────────────────────
    if args.console:
        await guard.close()

    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
