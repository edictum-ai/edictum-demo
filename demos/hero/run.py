"""Repeatable runner for the parent -> child -> reviewer hero demo."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import tempfile
from pathlib import Path

from demos.hero.common import (
    DEFAULT_TASK_PATH,
    HeroApiClient,
    HeroConfig,
    REPO_ROOT,
    build_session_id,
    print_json,
    utc_now,
)
from demos.hero.reviewer import run_reviewer


def _parse_parent_summary(stdout: bytes) -> dict[str, object]:
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
    raise RuntimeError("parent process did not emit a JSON summary")


async def _wait_for_process(process: asyncio.subprocess.Process, timeout: float) -> bool:
    try:
        await asyncio.wait_for(process.wait(), timeout=timeout)
        return True
    except TimeoutError:
        return False


async def run_one(args: argparse.Namespace, *, run_index: int, config: HeroConfig) -> dict[str, object]:
    base_dir = Path(args.base_dir)
    base_dir.mkdir(parents=True, exist_ok=True)
    run_dir = base_dir / f"run-{run_index:02d}-{build_session_id('workdir')}"
    run_dir.mkdir(parents=True, exist_ok=True)

    parent_session_id = build_session_id(f"hero-parent-{run_index}")
    child_session_id = build_session_id(f"hero-child-{run_index}")
    review_outcomes: list[dict[str, object]] = []
    handled_approvals: set[str] = set()
    stage_history: list[dict[str, str]] = []
    workflow_state_source = "events"
    last_stage = "__missing__"

    async with HeroApiClient(config) as api:
        if args.wait_for_api:
            await api.wait_for_health(timeout_seconds=args.wait_for_api)

        parent_command = [
            sys.executable,
            "-m",
            "demos.hero.parent",
            "--json",
            "--task-path",
            str(args.task_path.resolve()),
            "--run-dir",
            str(run_dir.resolve()),
            "--parent-session-id",
            parent_session_id,
            "--child-session-id",
            child_session_id,
            "--api-url",
            config.api_url,
            "--api-key",
            config.api_key,
        ]
        parent_process = await asyncio.create_subprocess_exec(
            *parent_command,
            cwd=str(REPO_ROOT),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        while True:
            source, workflow = await api.workflow_state(agent_id=config.child_agent_id, session_id=child_session_id)
            workflow_state_source = source
            active_stage = ""
            if workflow:
                active_stage = str(workflow.get("active_stage", ""))
            if active_stage != last_stage:
                stage_history.append({"timestamp": utc_now(), "stage": active_stage, "source": source})
                last_stage = active_stage

            approvals = await api.list_approvals(
                agent_id=config.child_agent_id,
                session_id=child_session_id,
                status="pending",
            )
            for approval in approvals:
                approval_id = str(approval["id"])
                if approval_id in handled_approvals:
                    continue
                handled_approvals.add(approval_id)
                outcome = await run_reviewer(
                    argparse.Namespace(
                        api_url=config.api_url,
                        api_key=config.api_key,
                        task_path=args.task_path,
                        run_dir=run_dir,
                        child_session_id=child_session_id,
                        parent_session_id=parent_session_id,
                        pending_approval_id=approval_id,
                        reviewer_session_id=build_session_id(f"hero-review-{run_index}"),
                    )
                )
                review_outcomes.append(outcome.to_dict())

            if await _wait_for_process(parent_process, config.poll_interval):
                break

        stdout, stderr = await parent_process.communicate()
        parent_summary = _parse_parent_summary(stdout)
        final_events = await api.list_events(agent_id=config.child_agent_id, session_id=child_session_id, limit=1000)
        final_approvals = await api.list_approvals(session_id=child_session_id)
        _, final_workflow = await api.workflow_state(agent_id=config.child_agent_id, session_id=child_session_id)

    child_summary = parent_summary.get("child_summary") if isinstance(parent_summary.get("child_summary"), dict) else {}
    child_workflow = child_summary.get("workflow") if isinstance(child_summary, dict) else None
    effective_final_workflow = child_workflow or final_workflow
    end_to_end_ok = (
        parent_process.returncode == 0
        and isinstance(child_summary, dict)
        and bool(effective_final_workflow)
        and effective_final_workflow.get("active_stage", "") in {"", "done"}
    )
    blocked_event_seen = any(event.get("action") == "call_blocked" for event in final_events)
    reset_count = sum(1 for outcome in review_outcomes if outcome["action"] == "requested-reset")

    summary = {
        "run_index": run_index,
        "run_dir": str(run_dir),
        "parent_session_id": parent_session_id,
        "child_session_id": child_session_id,
        "parent_summary": parent_summary,
        "parent_stderr": stderr.decode("utf-8").strip(),
        "review_outcomes": review_outcomes,
        "workflow_state_source": workflow_state_source,
        "stage_history": stage_history,
        "event_count": len(final_events),
        "approval_count": len(final_approvals),
        "api_final_workflow": final_workflow,
        "child_reported_workflow": child_workflow,
        "final_workflow": effective_final_workflow,
        "blocked_event_seen": blocked_event_seen,
        "reset_count": reset_count,
        "end_to_end_ok": end_to_end_ok,
    }
    return summary


async def async_main(args: argparse.Namespace) -> dict[str, object]:
    config = HeroConfig.from_env(api_url=args.api_url, api_key=args.api_key)
    config.poll_interval = args.poll_interval
    runs: list[dict[str, object]] = []
    for run_index in range(1, args.runs + 1):
        runs.append(await run_one(args, run_index=run_index, config=config))
    return {
        "runs_requested": args.runs,
        "runs_completed": len(runs),
        "all_succeeded": all(bool(run["end_to_end_ok"]) for run in runs),
        "repeatable_multi_run_support": True,
        "runs": runs,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the repeatable hero demo harness")
    parser.add_argument("--api-url", default=None)
    parser.add_argument("--api-key", default=None)
    parser.add_argument("--task-path", type=Path, default=DEFAULT_TASK_PATH)
    parser.add_argument(
        "--base-dir",
        default=str(Path(tempfile.gettempdir()) / "edictum-hero-demo"),
        help="directory used for deterministic per-run workspaces",
    )
    parser.add_argument("--runs", type=int, default=1, help="how many full end-to-end runs to execute")
    parser.add_argument("--poll-interval", type=float, default=0.5)
    parser.add_argument(
        "--wait-for-api",
        type=float,
        default=15.0,
        help="seconds to wait for /v1/health before starting each run",
    )
    parser.add_argument("--keep-run-dirs", action="store_true")
    parser.add_argument("--json", action="store_true", help="print only the final JSON summary")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        summary = asyncio.run(async_main(args))
    except Exception as exc:  # pragma: no cover - exercised in integration
        print_json({"ok": False, "error": str(exc), "type": "runner_error"})
        return 1

    if args.json:
        print_json(summary)
    else:
        print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if summary.get("all_succeeded") else 1


if __name__ == "__main__":
    sys.exit(main())
