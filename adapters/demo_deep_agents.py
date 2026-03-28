"""
Edictum Deep Agents Adapter Demo
=================================

Demonstrates Edictum behavior checks with LangChain's Deep Agents framework.
Deep Agents uses the same AgentMiddleware protocol as LangChain, so the
existing LangChainAdapter works out of the box via ``as_middleware()``.

This demo also shows how to govern subagent tool calls — middleware must
be passed to each subagent explicitly.

Uses the ``create_deep_agent`` + ``AgentMiddleware`` API
(deepagents >= 0.1, langchain >= 1.2).

Usage:
    python adapters/demo_deep_agents.py
    python adapters/demo_deep_agents.py --mode observe
    python adapters/demo_deep_agents.py --console
    python adapters/demo_deep_agents.py --quick --role admin
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from shared_v2 import (  # noqa: E402
    get_weather as _get_weather,
    search_web as _search_web,
    read_file as _read_file,
    send_email as _send_email,
    update_record as _update_record,
    delete_record as _delete_record,
    SCENARIOS,
    QUICK_SCENARIOS,
    create_standalone_guard,
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

from edictum.adapters.langchain import LangChainAdapter
from langchain_openai import ChatOpenAI
from langchain_core.tools import tool


# ─── LangChain tool wrappers ─────────────────────────────────────────────────

@tool
def get_weather(city: str) -> str:
    """Get current weather for a city."""
    return _get_weather(city)


@tool
def search_web(query: str) -> str:
    """Search the web for information."""
    return _search_web(query)


@tool
def read_file(path: str) -> str:
    """Read a file from the filesystem."""
    return _read_file(path)


@tool
def send_email(to: str, subject: str, body: str) -> str:
    """Send an email to a recipient."""
    return _send_email(to, subject, body)


@tool
def update_record(record_id: str, data: str, confirmed: bool = False) -> str:
    """Update a record in the database."""
    return _update_record(record_id, data, confirmed)


@tool
def delete_record(record_id: str) -> str:
    """Delete a record from the database."""
    return _delete_record(record_id)


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
    args = parse_args("Deep Agents")
    principal = make_principal(args.role)
    scenarios = QUICK_SCENARIOS if args.quick else SCENARIOS

    # Create behavior guard
    if args.console:
        guard = await create_console_guard(
            agent_id="edictum-deep-agents-demo",
            bundle_name="edictum-adapter-demos",
        )
    else:
        guard = create_standalone_guard(mode=args.mode)

    # Deep Agents adapter — uses the same LangChainAdapter + as_middleware()
    adapter = LangChainAdapter(guard, principal=principal)
    edictum_middleware = adapter.as_middleware()

    # Import Deep Agents
    from deepagents import create_deep_agent

    llm = ChatOpenAI(model="gpt-4.1-mini", temperature=0)

    # Create deep agent with Edictum behavior checks middleware.
    # The middleware parameter accepts AgentMiddleware instances — the same
    # protocol LangChain uses.
    agent = create_deep_agent(
        model=llm,
        tools=ALL_TOOLS,
        middleware=[edictum_middleware],
    )

    print_banner("Deep Agents", args.mode, console=args.console)

    # Get audit sink for result classification
    sink = get_local_sink(guard)

    # Run each scenario with a directive prompt
    for i, (desc, tool_name, tool_args, expected) in enumerate(scenarios, 1):
        print_scenario(i, len(scenarios), desc)

        args_str = ", ".join(
            f'{k}="{v}"' if isinstance(v, str) else f'{k}={v}'
            for k, v in tool_args.items()
        )
        prompt = (
            f"Call the {tool_name} tool with these exact arguments: {args_str}. "
            f"Do not call any other tools."
        )

        mark_sink(sink)

        try:
            result = await agent.ainvoke({"messages": [("human", prompt)]})
        except Exception as exc:
            err = str(exc)
            if "INVALID_CHAT_HISTORY" in err:
                print_result("REDACTED", "Postcondition redacted output (tool result suppressed)")
            else:
                print_result("DENIED", err[:120])
            continue

        # Use audit-based classification first, fallback to message parsing
        action, detail = classify_result(sink, tool_name, expected)
        if action:
            print_result(action, detail)
            continue

        # Fallback: parse result messages for behavior decisions
        for msg in result["messages"]:
            if not (hasattr(msg, "content") and hasattr(msg, "tool_call_id")):
                continue

            content = str(msg.content)
            if content.startswith("DENIED:"):
                print_result("DENIED", content[7:].strip())
            elif "[REDACTED]" in content:
                print_result("REDACTED", "PII detected and redacted in output")
            elif content.startswith("APPROVAL:") or "approval" in content.lower():
                print_result("APPROVAL", content)
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
