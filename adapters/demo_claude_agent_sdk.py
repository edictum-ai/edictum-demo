"""
Edictum Claude Agent SDK Adapter Demo
======================================

Demonstrates Edictum governance using the Claude Agent SDK with hook-based
integration. Exercises ALL rule types via directed tool calls: pre/post/
session/sandbox rules, deny/redact/warn/approve effects, RBAC, and observe mode.

Uses custom MCP tools via @tool decorator + create_sdk_mcp_server, with edictum
hooks bridged into the SDK's HookMatcher system.

Usage:
    python adapters/demo_claude_agent_sdk.py
    python adapters/demo_claude_agent_sdk.py --mode observe
    python adapters/demo_claude_agent_sdk.py --console
    python adapters/demo_claude_agent_sdk.py --quick --role admin
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
    since_last_mark,
    get_local_sink,
    parse_args,
    make_principal,
    print_banner,
    print_scenario,
    print_result,
    print_audit_summary,
)

from edictum.adapters.claude_agent_sdk import ClaudeAgentSDKAdapter  # noqa: E402

try:
    from claude_agent_sdk import (  # noqa: E402
        ClaudeAgentOptions,
        ClaudeSDKClient,
        HookMatcher,
        tool,
        create_sdk_mcp_server,
    )
except ImportError:
    print("ERROR: claude-agent-sdk not installed.")
    print()
    print("Install with:")
    print("  pip install claude-agent-sdk")
    sys.exit(1)


# ─── MCP Tools via @tool decorator ──────────────────────────────────────────

@tool("get_weather", "Get current weather for a city", {"city": str})
async def mcp_get_weather(args):
    return {"content": [{"type": "text", "text": _get_weather(args["city"])}]}


@tool("search_web", "Search the web for information", {"query": str})
async def mcp_search_web(args):
    return {"content": [{"type": "text", "text": _search_web(args["query"])}]}


@tool("read_file", "Read a file from the filesystem", {"path": str})
async def mcp_read_file(args):
    return {"content": [{"type": "text", "text": _read_file(args["path"])}]}


@tool("send_email", "Send an email", {"to": str, "subject": str, "body": str})
async def mcp_send_email(args):
    return {"content": [{"type": "text", "text": _send_email(args["to"], args["subject"], args["body"])}]}


@tool("update_record", "Update a database record", {"record_id": str, "data": str, "confirmed": bool})
async def mcp_update_record(args):
    return {"content": [{"type": "text", "text": _update_record(args["record_id"], args["data"], args.get("confirmed", False))}]}


@tool("delete_record", "Delete a database record", {"record_id": str})
async def mcp_delete_record(args):
    return {"content": [{"type": "text", "text": _delete_record(args["record_id"])}]}


ALL_MCP_TOOLS = [mcp_get_weather, mcp_search_web, mcp_read_file, mcp_send_email, mcp_update_record, mcp_delete_record]
TOOL_NAMES = ["get_weather", "search_web", "read_file", "send_email", "update_record", "delete_record"]


# ─── Hook bridge ─────────────────────────────────────────────────────────────

def make_hooks(adapter: ClaudeAgentSDKAdapter):
    """Bridge edictum adapter hooks into Claude SDK HookMatcher format.

    SDK hooks receive (input_data, tool_use_id, context) where
    input_data = {"tool_name": ..., "tool_input": ...}.

    Edictum adapter hooks expect (tool_name, tool_input, tool_use_id).
    """
    edictum_hooks = adapter.to_hook_callables()
    pre_hook = edictum_hooks["pre_tool_use"]
    post_hook = edictum_hooks["post_tool_use"]

    async def pre_tool_use(input_data, tool_use_id, context):
        # SDK uses mcp__server__toolname format, extract the actual tool name
        raw_name = input_data.get("tool_name", "")
        tool_name = raw_name.split("__")[-1] if "__" in raw_name else raw_name
        tool_input = input_data.get("tool_input", {})
        return await pre_hook(tool_name, tool_input, tool_use_id)

    async def post_tool_use(input_data, tool_use_id, context):
        tool_response = input_data.get("tool_result", input_data.get("tool_output", ""))
        return await post_hook(tool_use_id=tool_use_id, tool_response=tool_response)

    return pre_tool_use, post_tool_use


# ─── Main ────────────────────────────────────────────────────────────────────

async def main():
    args = parse_args("Claude Agent SDK")
    principal = make_principal(args.role)
    scenarios = QUICK_SCENARIOS if args.quick else SCENARIOS

    # Create governance guard
    if args.console:
        guard = await create_console_guard(
            agent_id="edictum-claude-agent-sdk-agent",
            bundle_name="edictum-adapter-demos",
        )
    else:
        guard = create_standalone_guard(mode=args.mode)

    # Create adapter and bridge hooks
    adapter = ClaudeAgentSDKAdapter(guard, principal=principal)
    pre_hook, post_hook = make_hooks(adapter)

    # Create MCP server with our tools
    server = create_sdk_mcp_server(
        name="demo-tools",
        version="1.0.0",
        tools=ALL_MCP_TOOLS,
    )

    # Build allowed tool names (MCP format: mcp__server__toolname)
    allowed = [f"mcp__demo-tools__{name}" for name in TOOL_NAMES]

    # Configure SDK with edictum hooks
    options = ClaudeAgentOptions(
        model="claude-haiku-4-5-20251001",
        mcp_servers={"demo-tools": server},
        allowed_tools=allowed,
        hooks={
            "PreToolUse": [
                HookMatcher(matcher="*", hooks=[pre_hook]),
            ],
            "PostToolUse": [
                HookMatcher(matcher="*", hooks=[post_hook]),
            ],
        },
    )

    # Get audit sink for result classification
    sink = get_local_sink(guard)

    print_banner("Claude Agent SDK", args.mode, console=args.console)

    # Run scenarios
    async with ClaudeSDKClient(options=options) as client:
        for i, (desc, tool_name, tool_args, expected) in enumerate(scenarios, 1):
            print_scenario(i, len(scenarios), desc)

            mark_sink(sink)

            args_str = ", ".join(
                f'{k}="{v}"' if isinstance(v, str) else f"{k}={v}"
                for k, v in tool_args.items()
            )
            prompt = (
                f"Call the {tool_name} tool with these exact arguments: {args_str}. "
                f"Do not call any other tools. Do not explain, just call the tool."
            )

            try:
                await client.query(prompt)
                response_parts = []
                async for msg in client.receive_response():
                    text = str(msg) if msg else ""
                    if text:
                        response_parts.append(text)

                if sink:
                    # Filter out ToolSearch noise — only check our actual tool
                    recent = since_last_mark(sink)
                    tool_events = [e for e in recent if getattr(e, 'tool_name', None) == tool_name]

                    if not tool_events:
                        print_result("AGENT_SKIP", f"agent declined to call {tool_name} (expected: {expected})")
                    else:
                        action, detail = classify_result(sink, tool_name, expected)
                        if action:
                            print_result(action, detail)
                        else:
                            print_result("ALLOWED", f"{tool_name} executed")
                else:
                    # Console mode: no local audit, fall back to response text
                    response_text = " ".join(response_parts)
                    if "denied" in response_text.lower() or "blocked" in response_text.lower():
                        print_result("DENIED", f"{tool_name} denied (see console for details)")
                    elif "[REDACTED]" in response_text or "redacted" in response_text.lower():
                        print_result("REDACTED", "PII detected (see console for details)")
                    else:
                        print_result("ALLOWED", f"{tool_name} executed")

            except Exception as exc:
                if sink:
                    recent = since_last_mark(sink)
                    tool_events = [e for e in recent if getattr(e, 'tool_name', None) == tool_name]
                    if not tool_events:
                        print_result("AGENT_SKIP", f"agent declined to call {tool_name} (expected: {expected})")
                    else:
                        action, detail = classify_result(sink, tool_name, expected)
                        print_result(action or "ERROR", detail or str(exc)[:100])
                else:
                    print_result("ERROR", str(exc)[:100])

    # Audit summary
    if sink:
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
