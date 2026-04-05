"""Guarded child lane for the hero demo."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from demos.hero.common import (
    ChildRuntimeHandles,
    DEFAULT_TASK_PATH,
    HeroConfig,
    HeroWorkspace,
    LineageLangChainAdapter,
    ToolInvocationResult,
    build_child_runtime,
    build_session_id,
    close_child_runtime,
    make_principal,
    print_json,
    read_task_text,
)
from edictum.audit import AuditAction
from edictum.workflow.state import build_workflow_snapshot


class ChildToolDriver:
    """Run scripted tool calls through the real LangChain adapter."""

    def __init__(self, adapter: LineageLangChainAdapter, tools: dict[str, Any]) -> None:
        self._adapter = adapter
        self._tools = tools
        self._call_counter = 0
        self._wrapper = adapter.as_async_tool_wrapper()

    async def invoke(self, tool_name: str, **kwargs: Any) -> ToolInvocationResult:
        tool = self._tools[tool_name]
        request = SimpleNamespace(
            tool_call={
                "name": tool_name,
                "args": kwargs,
                "id": f"{tool_name.lower()}-{self._call_counter}",
            }
        )
        self._call_counter += 1

        async def handler(_: Any) -> Any:
            return await tool.ainvoke(kwargs)

        raw = await self._wrapper(request, handler)
        content = getattr(raw, "content", raw)
        if isinstance(content, str):
            text = content
        else:
            text = json.dumps(content, sort_keys=True)
        return ToolInvocationResult(
            tool_name=tool_name,
            args=dict(kwargs),
            text=text,
            denied=text.startswith("DENIED:"),
        )


def build_tools(workspace: HeroWorkspace) -> dict[str, Any]:
    from langchain_core.tools import tool

    @tool("Read")
    async def read_file(path: str) -> str:
        """Read a file from the deterministic hero workspace."""
        return workspace.read_text(path)

    @tool("Grep")
    async def grep_files(pattern: str) -> str:
        """Search for a regex pattern across workspace files."""
        return "\n".join(workspace.grep(pattern)) or "No matches"

    @tool("Glob")
    async def glob_files(pattern: str) -> str:
        """Return workspace files that match a glob pattern."""
        return json.dumps(workspace.glob_paths(pattern), sort_keys=True)

    @tool("Write")
    async def write_file(path: str, content: str) -> str:
        """Write a file inside the deterministic hero workspace."""
        workspace.write_text(path, content)
        return f"Wrote {path}"

    @tool("Edit")
    async def edit_file(path: str, old: str, new: str) -> str:
        """Replace one deterministic snippet in a workspace file."""
        workspace.edit_text(path, old, new)
        return f"Edited {path}"

    @tool("Bash")
    async def run_bash(command: str) -> str:
        """Run a deterministic bash simulation against the hero workspace."""
        return workspace.simulate_bash(command)

    tools = {
        "Read": read_file,
        "Grep": grep_files,
        "Glob": glob_files,
        "Write": write_file,
        "Edit": edit_file,
        "Bash": run_bash,
    }
    return tools


class HeroChild:
    def __init__(
        self,
        *,
        config: HeroConfig,
        run_dir: Path,
        task_path: Path,
        session_id: str,
        parent_session_id: str | None,
    ) -> None:
        self.config = config
        self.run_dir = run_dir
        self.task_path = task_path
        self.session_id = session_id
        self.parent_session_id = parent_session_id
        self.workspace = HeroWorkspace.initialize(run_dir, task_text=read_task_text(task_path))
        self.principal = make_principal("implementer", session_id)
        self.handles: ChildRuntimeHandles | None = None
        self.driver: ChildToolDriver | None = None
        self._tool_history: list[ToolInvocationResult] = []

    async def __aenter__(self) -> "HeroChild":
        self.handles = await build_child_runtime(
            config=self.config,
            session_id=self.session_id,
            parent_session_id=self.parent_session_id,
            principal=self.principal,
        )
        self.driver = ChildToolDriver(self.handles.adapter, build_tools(self.workspace))
        return self

    async def __aexit__(self, *exc: Any) -> None:
        assert self.handles is not None
        await close_child_runtime(self.handles)

    async def run(self) -> dict[str, Any]:
        assert self.handles is not None
        await self._bootstrap_context()
        while True:
            stage = await self._active_stage()
            if not stage:
                break
            if stage == "done":
                break
            if stage in {"baseline-verify", "implement"}:
                denied = await self._implementation_pass()
                if denied:
                    continue
            elif stage in {"local-verify", "external-review", "docs-update", "push-pr", "ci-green"}:
                denied = await self._delivery_pass()
                if denied:
                    continue
            else:
                raise RuntimeError(f"unexpected workflow stage {stage!r}")

        workflow = await self._workflow_snapshot()
        local_events = list(self.handles.guard.local_sink.events)
        return {
            "agent_id": self.config.child_agent_id,
            "session_id": self.session_id,
            "parent_session_id": self.parent_session_id,
            "run_dir": str(self.run_dir),
            "workflow": workflow,
            "workspace": HeroWorkspace.load(self.run_dir).to_summary(),
            "tool_history": [asdict(item) for item in self._tool_history],
            "audit_event_count": len(local_events),
            "audit_actions": [event.action.value for event in local_events],
            "blocked_reasons": [event.reason for event in local_events if event.action == AuditAction.CALL_DENIED],
        }

    async def _bootstrap_context(self) -> None:
        await self._invoke("Read", path="README.md")
        await self._invoke("Read", path="TASK.md")
        await self._invoke("Glob", pattern="src/*.py")
        await self._invoke("Bash", command=f"git switch -c hero/{self.session_id}")
        await self._invoke("Read", path="README.md")
        await self._invoke("Bash", command="python -m compileall src")

    async def _implementation_pass(self) -> bool:
        self.workspace = HeroWorkspace.load(self.run_dir)
        assert self.handles is not None
        self.driver = ChildToolDriver(self.handles.adapter, build_tools(self.workspace))
        source = self.workspace.read_text("src/hero_cli.py")
        self.workspace.increment_implement_pass()
        await self._invoke("Read", path="src/hero_cli.py")
        if "# REVIEW_TODO:" in source:
            await self._invoke(
                "Edit",
                path="src/hero_cli.py",
                old=(
                    "VERBOSE_FLAG = True\n"
                    "VERBOSE_FLAG_COMPLETE = True\n"
                    "# REVIEW_TODO: tighten the user-facing summary before approval\n"
                ),
                new="VERBOSE_FLAG = True\nVERBOSE_FLAG_COMPLETE = True\n",
            )
        elif "VERBOSE_FLAG = False\nVERBOSE_FLAG_COMPLETE = False\n" in source:
            await self._invoke(
                "Edit",
                path="src/hero_cli.py",
                old="VERBOSE_FLAG = False\nVERBOSE_FLAG_COMPLETE = False\n",
                new=(
                    "VERBOSE_FLAG = True\n"
                    "VERBOSE_FLAG_COMPLETE = True\n"
                    "# REVIEW_TODO: tighten the user-facing summary before approval\n"
                ),
            )
        else:
            raise RuntimeError("src/hero_cli.py is not in an expected implementation state")
        await self._invoke("Bash", command="git push origin HEAD --dry-run")
        verify = await self._invoke("Bash", command="python -m compileall src")
        return verify.denied

    async def _delivery_pass(self) -> bool:
        await self._invoke("Bash", command="git status --short")
        await self._invoke("Bash", command="git diff -- src/hero_cli.py")
        review_gate = await self._invoke(
            "Edit",
            path="README.md",
            old="The task is to add a deterministic `--verbose` flag and carry the change through review.\n",
            new=(
                "The task is to add a deterministic `--verbose` flag and carry the change through review.\n"
                "The CLI now documents a deterministic verbose path for the hero integration test.\n"
            ),
        )
        if review_gate.denied:
            return True
        await self._invoke("Bash", command="git add .")
        await self._invoke("Bash", command='git commit -m "feat: add deterministic verbose flag"')
        await self._invoke("Bash", command="git push origin HEAD")
        await self._invoke("Bash", command='gh pr create --title "Hero Demo" --body "Deterministic integration run"')
        await self._invoke("Bash", command="gh pr checks --watch")
        return False

    async def _active_stage(self) -> str:
        assert self.handles is not None
        state = await self.handles.workflow_runtime.state(self.handles.session)
        return state.active_stage

    async def _workflow_snapshot(self) -> dict[str, Any]:
        assert self.handles is not None
        state = await self.handles.workflow_runtime.state(self.handles.session)
        return build_workflow_snapshot(self.handles.workflow_runtime.definition, state)

    async def _invoke(self, tool_name: str, **kwargs: Any) -> ToolInvocationResult:
        assert self.driver is not None
        result = await self.driver.invoke(tool_name, **kwargs)
        self._tool_history.append(result)
        return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the guarded hero child lane")
    parser.add_argument("--api-url", default=None)
    parser.add_argument("--api-key", default=None)
    parser.add_argument("--task-path", type=Path, default=DEFAULT_TASK_PATH)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--session-id", default=None)
    parser.add_argument("--parent-session-id", default=None)
    parser.add_argument("--json", action="store_true", help="print only the final JSON summary")
    return parser.parse_args()


async def async_main(args: argparse.Namespace) -> dict[str, Any]:
    config = HeroConfig.from_env(api_url=args.api_url, api_key=args.api_key)
    session_id = args.session_id or build_session_id("hero-child")
    async with HeroChild(
        config=config,
        run_dir=args.run_dir,
        task_path=args.task_path,
        session_id=session_id,
        parent_session_id=args.parent_session_id,
    ) as child:
        return await child.run()


def main() -> int:
    args = parse_args()
    try:
        summary = asyncio.run(async_main(args))
    except Exception as exc:  # pragma: no cover - exercised in integration
        print_json({"ok": False, "error": str(exc), "type": "child_error"})
        return 1

    if args.json:
        print_json(summary)
    else:
        print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
