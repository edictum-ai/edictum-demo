"""
Edictum Semantic Kernel Adapter Demo
======================================

Demonstrates Edictum behavior checks using the Semantic Kernel adapter with
AUTO_FUNCTION_INVOCATION kernel filters. Exercises ALL rule types via
directed tool calls: pre/post/session/sandbox rules, deny/redact/warn/
approve effects, RBAC, and observe mode.

Usage:
    python adapters/demo_semantic_kernel.py
    python adapters/demo_semantic_kernel.py --mode observe
    python adapters/demo_semantic_kernel.py --console
    python adapters/demo_semantic_kernel.py --quick --role admin
"""

from __future__ import annotations

import asyncio
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

from edictum.adapters.semantic_kernel import SemanticKernelAdapter
from semantic_kernel import Kernel
from semantic_kernel.functions import kernel_function
from semantic_kernel.connectors.ai.open_ai import OpenAIChatCompletion
from semantic_kernel.agents import ChatCompletionAgent
from semantic_kernel.contents import ChatHistory


# ─── Semantic Kernel plugin ──────────────────────────────────────────────────

class DemoPlugin:
    """Wraps shared mock tools as Semantic Kernel kernel functions."""

    @kernel_function(name="get_weather", description="Get current weather for a city.")
    def get_weather(self, city: str) -> str:
        return _get_weather(city)

    @kernel_function(name="search_web", description="Search the web for information.")
    def search_web(self, query: str) -> str:
        return _search_web(query)

    @kernel_function(name="read_file", description="Read a file from the filesystem.")
    def read_file(self, path: str) -> str:
        return _read_file(path)

    @kernel_function(name="send_email", description="Send an email to a recipient.")
    def send_email(self, to: str, subject: str, body: str) -> str:
        return _send_email(to, subject, body)

    @kernel_function(name="update_record", description="Update a record in the database.")
    def update_record(self, record_id: str, data: str, confirmed: bool = False) -> str:
        return _update_record(record_id, data, confirmed)

    @kernel_function(name="delete_record", description="Delete a record from the database.")
    def delete_record(self, record_id: str) -> str:
        return _delete_record(record_id)


# ─── Main ────────────────────────────────────────────────────────────────────

async def main():
    args = parse_args("Semantic Kernel")
    principal = make_principal(args.role)
    scenarios = QUICK_SCENARIOS if args.quick else SCENARIOS

    # Create behavior guard
    if args.console:
        guard = await create_console_guard(
            agent_id="edictum-sk-agent",
            bundle_name="edictum-adapter-demos",
        )
    else:
        guard = create_standalone_guard(mode=args.mode)

    # Semantic Kernel setup
    kernel = Kernel()
    kernel.add_plugin(DemoPlugin(), plugin_name="demo")

    # Edictum adapter — registers AUTO_FUNCTION_INVOCATION filter on kernel
    adapter = SemanticKernelAdapter(guard, principal=principal)
    adapter.register(kernel)

    # LLM service + agent
    service = OpenAIChatCompletion(service_id="openai", ai_model_id="gpt-4.1-mini")
    kernel.add_service(service)

    agent = ChatCompletionAgent(
        kernel=kernel,
        service=service,
        name="demo-agent",
        instructions=(
            "You are a helpful assistant. When asked to call a tool, call it "
            "with the exact arguments provided. Do not call any other tools."
        ),
    )

    print_banner("Semantic Kernel", args.mode, console=args.console)

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

        mark_sink(sink)

        try:
            history = ChatHistory()
            history.add_user_message(prompt)

            response_text = ""
            async for message in agent.invoke(history):
                response_text = str(message.content) if message.content else ""

            # Use audit-based classification first, fallback to output parsing
            action, detail = classify_result(sink, tool_name, expected)
            if action:
                print_result(action, detail)
            elif "DENIED:" in response_text:
                denied_part = response_text.split("DENIED:", 1)[1].strip()
                print_result("DENIED", denied_part[:100])
            elif "[REDACTED]" in response_text:
                print_result("REDACTED", "PII detected and redacted in output")
            elif "approval" in response_text.lower():
                print_result("APPROVAL", response_text[:100])
            else:
                print_result("ALLOWED", f"{tool_name} executed")

        except Exception as exc:
            exc_str = str(exc)
            if "DENIED:" in exc_str:
                denied_part = exc_str.split("DENIED:", 1)[1].strip()
                print_result("DENIED", denied_part[:100])
            else:
                print_result("DENIED", exc_str[:100])

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
