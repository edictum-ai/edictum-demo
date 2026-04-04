"""Unguarded parent lane for the hero demo."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from demos.hero.common import DEFAULT_TASK_PATH, HeroConfig, REPO_ROOT, build_session_id, print_json


def _parse_child_summary(stdout: bytes) -> dict[str, object]:
    text = stdout.decode("utf-8").strip()
    if not text:
        return {}
    for line in reversed(text.splitlines()):
        line = line.strip()
        if not line:
            continue
        try:
            return json.loads(line)
        except json.JSONDecodeError:
            continue
    raise RuntimeError("child process did not emit a JSON summary")


async def run_parent(args: argparse.Namespace) -> dict[str, object]:
    config = HeroConfig.from_env(api_url=args.api_url, api_key=args.api_key)
    parent_session_id = args.parent_session_id or build_session_id("hero-parent")
    child_session_id = args.child_session_id or build_session_id("hero-child")

    command = [
        sys.executable,
        "-m",
        "demos.hero.child",
        "--json",
        "--task-path",
        str(args.task_path.resolve()),
        "--run-dir",
        str(args.run_dir.resolve()),
        "--session-id",
        child_session_id,
        "--api-url",
        config.api_url,
        "--api-key",
        config.api_key,
    ]
    if parent_session_id:
        command.extend(["--parent-session-id", parent_session_id])

    process = await asyncio.create_subprocess_exec(
        *command,
        cwd=str(REPO_ROOT),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate()
    child_summary = _parse_child_summary(stdout)

    return {
        "agent_id": config.parent_agent_id,
        "parent_session_id": parent_session_id,
        "child_session_id": child_session_id,
        "child_exit_code": process.returncode,
        "child_summary": child_summary,
        "child_stderr": stderr.decode("utf-8").strip(),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the unguarded hero parent lane")
    parser.add_argument("--api-url", default=None)
    parser.add_argument("--api-key", default=None)
    parser.add_argument("--task-path", type=Path, default=DEFAULT_TASK_PATH)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--parent-session-id", default=None)
    parser.add_argument("--child-session-id", default=None)
    parser.add_argument("--json", action="store_true", help="print only the final JSON summary")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        summary = asyncio.run(run_parent(args))
    except Exception as exc:  # pragma: no cover - exercised in integration
        print_json({"ok": False, "error": str(exc), "type": "parent_error"})
        return 1

    if args.json:
        print_json(summary)
    else:
        print(json.dumps(summary, indent=2, sort_keys=True))

    child_exit_code = int(summary.get("child_exit_code", 1))
    return 0 if child_exit_code == 0 else child_exit_code


if __name__ == "__main__":
    sys.exit(main())
