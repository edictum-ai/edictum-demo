"""
Edictum Google ADK Adapter Demo
================================

Demonstrates Edictum behavior checks using the Google ADK adapter with plugin-based
integration. Exercises ALL rule types via directed tool calls: pre/post/
session/sandbox rules, deny/redact/warn/approve effects, RBAC, and observe mode.

Two integration paths are shown:
  - **Plugin path** (default): ``adapter.as_plugin()`` for Runner(plugins=[...]).
    Governs ALL tools across ALL agents. Recommended for most use cases.
  - **Callback path** (alternative): ``adapter.as_agent_callbacks()`` for per-agent
    scoping or live/streaming mode. Shown in ``run_callback_demo()``.

Usage:
    python adapters/demo_google_adk.py
    python adapters/demo_google_adk.py --mode observe
    python adapters/demo_google_adk.py --console
    python adapters/demo_google_adk.py --quick --role admin
    python adapters/demo_google_adk.py --callbacks   # use agent callback path
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
    get_local_sink,
    parse_args,
    make_principal,
    print_banner,
    print_scenario,
    print_result,
    print_audit_summary,
)

try:
    from edictum.adapters.google_adk import GoogleADKAdapter  # noqa: E402
except ImportError:
    print("ERROR: Google ADK adapter not available.")
    print("The ADK adapter requires edictum with ADK support and the google-adk package.")
    print()
    print("Install with:")
    print("  pip install edictum[google-adk]   # once adapter is released")
    print("  pip install google-adk            # ADK runtime")
    print()
    print("If the adapter PR is still open, install edictum from the feature branch:")
    print("  pip install git+https://github.com/edictum-ai/edictum@feat/google-adk-adapter")
    sys.exit(1)

try:
    from google.adk.agents import LlmAgent  # noqa: E402
    from google.adk.runners import Runner  # noqa: E402
    from google.adk.sessions import InMemorySessionService  # noqa: E402
    from google.genai import types as genai_types  # noqa: E402
except ImportError:
    print("ERROR: google-adk package not installed.")
    print()
    print("Install with:")
    print("  pip install google-adk")
    sys.exit(1)


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

AGENT_INSTRUCTION = (
    "You are a helpful assistant. When asked to use a tool, "
    "call it with the exact arguments provided. Do not call any other tools."
)


# ─── Plugin path (recommended) ───────────────────────────────────────────────

async def run_plugin_demo(guard, principal, scenarios, mode: str, console: bool):
    """Run the demo using the plugin integration path (Runner-level behavior checks)."""
    adapter = GoogleADKAdapter(guard, principal=principal)
    plugin = adapter.as_plugin()

    agent = LlmAgent(
        name="demo_agent",
        model="gemini-3.1-flash-lite-preview",
        instruction=AGENT_INSTRUCTION,
        tools=ALL_TOOLS,
    )

    session_service = InMemorySessionService()
    runner = Runner(
        agent=agent,
        app_name="edictum-demo",
        session_service=session_service,
        plugins=[plugin],
    )

    sink = get_local_sink(guard)
    print_banner("Google ADK (plugin)", mode, console=console)
    await _run_scenarios(runner, session_service, scenarios, sink)


# ─── Callback path (alternative) ─────────────────────────────────────────────

async def run_callback_demo(guard, principal, scenarios, mode: str, console: bool):
    """Run the demo using the agent callback integration path (per-agent behavior checks)."""
    adapter = GoogleADKAdapter(guard, principal=principal)
    before_cb, after_cb, _error_cb = adapter.as_agent_callbacks()

    agent = LlmAgent(
        name="demo_agent",
        model="gemini-3.1-flash-lite-preview",
        instruction=AGENT_INSTRUCTION,
        tools=ALL_TOOLS,
        before_tool_callback=before_cb,
        after_tool_callback=after_cb,
    )

    session_service = InMemorySessionService()
    runner = Runner(
        agent=agent,
        app_name="edictum-demo",
        session_service=session_service,
    )

    sink = get_local_sink(guard)
    print_banner("Google ADK (callbacks)", mode, console=console)
    await _run_scenarios(runner, session_service, scenarios, sink)


# ─── Shared scenario runner ──────────────────────────────────────────────────

async def _run_scenarios(runner: Runner, session_service: InMemorySessionService, scenarios, sink=None):
    """Send each scenario as a user message and inspect the response."""
    session = await session_service.create_session(
        app_name="edictum-demo", user_id="demo-user"
    )

    for i, (desc, tool_name, tool_args, expected) in enumerate(scenarios, 1):
        print_scenario(i, len(scenarios), desc)

        mark_sink(sink)

        args_str = ", ".join(
            f'{k}="{v}"' if isinstance(v, str) else f"{k}={v}"
            for k, v in tool_args.items()
        )
        prompt = (
            f"Call the {tool_name} tool with these exact arguments: {args_str}. "
            f"Do not call any other tools."
        )

        content = genai_types.Content(
            parts=[genai_types.Part(text=prompt)], role="user"
        )

        response_parts: list[str] = []
        try:
            async for event in runner.run_async(
                user_id="demo-user",
                session_id=session.id,
                new_message=content,
            ):
                if event.content and event.content.parts:
                    for part in event.content.parts:
                        if hasattr(part, "text") and part.text:
                            response_parts.append(part.text)
        except Exception as exc:
            print_result("DENIED", str(exc))
            continue

        # Use audit-based classification first, fallback to output parsing
        action, detail = classify_result(sink, tool_name, expected)
        if action:
            print_result(action, detail)
            continue

        response_text = " ".join(response_parts)

        if "DENIED:" in response_text:
            denied_msg = response_text.split("DENIED:", 1)[1].strip().split("\n")[0]
            print_result("DENIED", denied_msg)
        elif "[REDACTED]" in response_text:
            print_result("REDACTED", "PII detected and redacted in output")
        elif "approval" in response_text.lower():
            print_result("APPROVAL", response_text[:80])
        else:
            print_result("ALLOWED", f"{tool_name} executed")


# ─── Main ────────────────────────────────────────────────────────────────────

async def main():
    # Extend standard args with --callbacks flag
    import argparse

    parser = argparse.ArgumentParser(description="Edictum Google ADK Demo")
    parser.add_argument(
        "--mode", default="enforce", choices=["enforce", "observe"],
        help="Governance mode (default: enforce)",
    )
    parser.add_argument(
        "--console", action="store_true",
        help="Use edictum-console instead of local YAML",
    )
    parser.add_argument(
        "--quick", action="store_true",
        help="Run quick subset of scenarios (skip rate limit + approval)",
    )
    parser.add_argument(
        "--role", default="analyst", choices=["analyst", "admin", "viewer"],
        help="Principal role (default: analyst)",
    )
    parser.add_argument(
        "--callbacks", action="store_true",
        help="Use agent callback path instead of plugin path",
    )
    args = parser.parse_args()

    principal = make_principal(args.role)
    scenarios = QUICK_SCENARIOS if args.quick else SCENARIOS

    # Create behavior guard
    if args.console:
        guard = await create_console_guard(
            agent_id="edictum-adk-agent",
            bundle_name="edictum-adapter-demos",
        )
    else:
        guard = create_standalone_guard(mode=args.mode)

    try:
        if args.callbacks:
            await run_callback_demo(guard, principal, scenarios, args.mode, args.console)
        else:
            await run_plugin_demo(guard, principal, scenarios, args.mode, args.console)

        # Audit summary
        sink = get_local_sink(guard)
        if sink is None and not args.console:
            for attr in ("audit_sink", "_sink"):
                if hasattr(guard, attr):
                    sink = getattr(guard, attr)
                    break
        if sink is not None:
            print_audit_summary(sink)
        else:
            print(f"\n{'=' * 60}")
            print("  GOVERNANCE SUMMARY")
            print(f"{'=' * 60}")
            print("  (Audit data sent to edictum-console server)")
            print()
    finally:
        if args.console and hasattr(guard, "close"):
            await guard.close()


if __name__ == "__main__":
    asyncio.run(main())
