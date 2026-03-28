"""
Edictum OpenAI Agents SDK Adapter Demo
=======================================

Demonstrates Edictum behavior checks using the OpenAI Agents SDK adapter.
Exercises ALL rule types: pre/post/session/sandbox, deny/redact/warn/approve,
principal/RBAC, observe mode, tool classification, and console integration.

Usage:
    python adapters/demo_openai_agents.py
    python adapters/demo_openai_agents.py --mode observe
    python adapters/demo_openai_agents.py --console
    python adapters/demo_openai_agents.py --quick --role admin
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

from edictum import Edictum
from edictum.adapters.openai_agents import OpenAIAgentsAdapter
from agents import Agent, Runner, function_tool

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


async def main():
    args = parse_args("OpenAI Agents SDK")
    principal = make_principal(args.role)
    scenarios = QUICK_SCENARIOS if args.quick else SCENARIOS

    # ── Create behavior guard ──────────────────────────────────────────
    if args.console:
        guard = await create_console_guard(agent_id="edictum-openai-agents-agent")
    else:
        guard = Edictum.from_yaml(
            str(RULES_PATH),
            mode="observe" if args.mode == "observe" else None,
        )
    sink = get_local_sink(guard)

    # ── Adapter + guardrails ─────────────────────────────────────────────
    adapter = OpenAIAgentsAdapter(guard, principal=principal)
    input_gr, output_gr = adapter.as_guardrails()

    # ── Define tools with behavior guardrails ──────────────────────────
    @function_tool(tool_input_guardrails=[input_gr], tool_output_guardrails=[output_gr])
    def get_weather(city: str) -> str:
        """Get current weather for a city."""
        return _get_weather(city)

    @function_tool(tool_input_guardrails=[input_gr], tool_output_guardrails=[output_gr])
    def search_web(query: str) -> str:
        """Search the web for information."""
        return _search_web(query)

    @function_tool(tool_input_guardrails=[input_gr], tool_output_guardrails=[output_gr])
    def read_file(path: str) -> str:
        """Read a file from the filesystem."""
        return _read_file(path)

    @function_tool(tool_input_guardrails=[input_gr], tool_output_guardrails=[output_gr])
    def send_email(to: str, subject: str, body: str) -> str:
        """Send an email to a recipient."""
        return _send_email(to, subject, body)

    @function_tool(tool_input_guardrails=[input_gr], tool_output_guardrails=[output_gr])
    def update_record(record_id: str, data: str, confirmed: bool = False) -> str:
        """Update a record in the database."""
        return _update_record(record_id, data, confirmed)

    @function_tool(tool_input_guardrails=[input_gr], tool_output_guardrails=[output_gr])
    def delete_record(record_id: str) -> str:
        """Delete a record from the database."""
        return _delete_record(record_id)

    tool_map = {
        "get_weather": get_weather,
        "search_web": search_web,
        "read_file": read_file,
        "send_email": send_email,
        "update_record": update_record,
        "delete_record": delete_record,
    }

    # ── Agent ────────────────────────────────────────────────────────────
    agent = Agent(
        name="demo-agent",
        instructions=(
            "You are a helpful assistant. When asked to call a tool, call it "
            "with exactly the arguments provided. Do not refuse or modify the request."
        ),
        tools=list(tool_map.values()),
    )

    # ── Banner ───────────────────────────────────────────────────────────
    print_banner("OpenAI Agents SDK", args.mode, console=args.console)

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
            result = await Runner.run(agent, prompt)
            output = result.final_output

            # Use audit-based classification first, fallback to output parsing
            action, detail = classify_result(sink, tool_name, expected)
            if action:
                print_result(action, detail)
            elif expected == "redact":
                print_result("REDACTED", f"{tool_name} → {output[:100]}")
            else:
                print_result("ALLOWED", f"{tool_name} → {output[:100]}")
        except Exception as e:
            err = str(e)[:100]
            if expected == "approval":
                print_result("APPROVAL", err)
            else:
                print_result("DENIED", err)

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
