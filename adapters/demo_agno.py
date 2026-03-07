"""
Edictum Agno Adapter Demo
==========================

Demonstrates Edictum governance using the Agno adapter with an Agno Agent.
Exercises ALL contract types via directed tool calls: pre/post/session/sandbox
contracts, deny/redact/warn/approve effects, RBAC, and observe mode.

Usage:
    python adapters/demo_agno.py
    python adapters/demo_agno.py --mode observe
    python adapters/demo_agno.py --console
    python adapters/demo_agno.py --quick --role admin
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from shared_v2 import (  # noqa: E402
    get_weather,
    search_web,
    read_file,
    send_email,
    update_record,
    delete_record,
    SCENARIOS,
    QUICK_SCENARIOS,
    create_standalone_guard,
    create_console_guard,
    classify_result,
    mark_sink,
    parse_args,
    make_principal,
    print_banner,
    print_scenario,
    print_result,
    print_audit_summary,
    get_local_sink,
)

from edictum.adapters.agno import AgnoAdapter  # noqa: E402
from agno.agent import Agent  # noqa: E402
from agno.models.openai import OpenAIChat  # noqa: E402


# ─── Tool registry for lookup by name ────────────────────────────────────────

TOOL_MAP = {
    "get_weather": get_weather,
    "search_web": search_web,
    "read_file": read_file,
    "send_email": send_email,
    "update_record": update_record,
    "delete_record": delete_record,
}

ALL_TOOLS = list(TOOL_MAP.values())


# ─── Main ────────────────────────────────────────────────────────────────────

async def main():
    args = parse_args("Agno")
    principal = make_principal(args.role)
    scenarios = QUICK_SCENARIOS if args.quick else SCENARIOS

    # Create governance guard
    if args.console:
        guard = await create_console_guard(
            agent_id="edictum-agno-agent",
            bundle_name="edictum-adapter-demos",
        )
    else:
        guard = create_standalone_guard(mode=args.mode)

    # Agno adapter — wrap-around hook intercepts every tool call
    adapter = AgnoAdapter(guard, principal=principal)
    hook = adapter.as_tool_hook()

    # Create Agno agent — plain functions are auto-wrapped by Agno
    agent = Agent(
        model=OpenAIChat(id="gpt-4.1-mini"),
        tools=ALL_TOOLS,
        tool_hooks=[hook],
        instructions=[
            "You are a helpful assistant. When asked to use a tool, "
            "call it with the exact arguments provided. Do not call any other tools."
        ],
    )

    print_banner("Agno", args.mode, console=args.console)

    # Get audit sink for result classification
    sink = get_local_sink(guard)

    # Run each scenario with a directive prompt
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

        if sink and hasattr(sink, 'mark'):
            mark_sink(sink)

        try:
            response = agent.run(prompt)
        except Exception as exc:
            print_result("DENIED", str(exc))
            continue

        # Use audit-based classification first, fallback to output parsing
        action, detail = classify_result(sink, tool_name, expected)
        if action:
            print_result(action, detail)
            continue

        # Fallback: extract tool results from agent response
        content = response.content if hasattr(response, "content") else str(response)

        if "DENIED:" in content:
            denied_msg = content.split("DENIED:", 1)[1].strip().split("\n")[0]
            print_result("DENIED", denied_msg)
        elif "[REDACTED]" in content:
            print_result("REDACTED", "PII detected and redacted in output")
        elif "approval" in content.lower():
            print_result("APPROVAL", content[:80])
        else:
            print_result("ALLOWED", f"{tool_name} executed")

    # Audit summary
    if not args.console:
        print_audit_summary(sink)
    else:
        print(f"\n{'=' * 60}")
        print("  GOVERNANCE SUMMARY")
        print(f"{'=' * 60}")
        print("  (Audit data sent to edictum-console server)")
        print()

    # Cleanup
    if args.console and hasattr(guard, "close"):
        await guard.close()


if __name__ == "__main__":
    asyncio.run(main())
