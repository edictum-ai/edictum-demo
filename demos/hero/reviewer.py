"""Separate reviewer lane for the hero demo."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from demos.hero.common import (
    DEFAULT_TASK_PATH,
    HeroApiClient,
    HeroConfig,
    HeroWorkspace,
    ReviewOutcome,
    SessionAwareApprovalBackend,
    apply_workflow_reset,
    build_session_id,
    make_principal,
    print_json,
)
from edictum.server import EdictumServerClient


async def run_reviewer(args: argparse.Namespace) -> ReviewOutcome:
    config = HeroConfig.from_env(api_url=args.api_url, api_key=args.api_key)
    reviewer_session_id = args.reviewer_session_id or build_session_id("hero-review")
    principal = make_principal("reviewer", reviewer_session_id)
    workspace = HeroWorkspace.load(args.run_dir)
    findings = workspace.current_review_findings()

    async with HeroApiClient(config) as api:
        if findings:
            client = EdictumServerClient(
                config.api_url,
                config.api_key,
                agent_id=config.reviewer_agent_id,
                env=config.environment,
                allow_insecure=True,
            )
            backend = SessionAwareApprovalBackend(client, default_session_id=reviewer_session_id, poll_interval=0.25)
            try:
                reset_request = await backend.request_approval(
                    tool_name="workflow_reset",
                    tool_args={"target_stage": "implement"},
                    message="Review findings require rework from implement stage",
                    timeout=60,
                    principal={"service_id": principal.service_id, "role": principal.role},
                    metadata={"rule_name": "workflow_reset"},
                )
                await api.decide_approval(
                    reset_request.approval_id,
                    decision="approved",
                    decided_by="hero-reviewer",
                    decided_via="hero-review-lane",
                    reason="Auto-approved reset for the deterministic hero demo",
                )
                await backend.wait_for_decision(reset_request.approval_id, timeout=5)
            finally:
                await client.close()

            workflow = await apply_workflow_reset(
                config=config,
                run_dir=args.run_dir,
                child_session_id=args.child_session_id,
                parent_session_id=args.parent_session_id,
                target_stage="implement",
                actor_principal=principal,
            )
            await api.decide_approval(
                args.pending_approval_id,
                decision="rejected",
                decided_by="hero-reviewer",
                decided_via="hero-review-lane",
                reason="Review findings require a reset to implement",
            )
            return ReviewOutcome(
                reviewer_session_id=reviewer_session_id,
                reviewer_agent_id=config.reviewer_agent_id,
                pending_approval_id=args.pending_approval_id,
                findings=findings,
                action="requested-reset",
                reset_approval_id=reset_request.approval_id,
                rejected=True,
                workflow=workflow,
            )

        await api.decide_approval(
            args.pending_approval_id,
            decision="approved",
            decided_by="hero-reviewer",
            decided_via="hero-review-lane",
            reason="External review found no new issues",
        )
        _, workflow = await api.workflow_state(agent_id=config.child_agent_id, session_id=args.child_session_id)
        return ReviewOutcome(
            reviewer_session_id=reviewer_session_id,
            reviewer_agent_id=config.reviewer_agent_id,
            pending_approval_id=args.pending_approval_id,
            findings=[],
            action="approved-external-review",
            approved=True,
            workflow=workflow,
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the separate hero reviewer lane")
    parser.add_argument("--api-url", default=None)
    parser.add_argument("--api-key", default=None)
    parser.add_argument("--task-path", type=Path, default=DEFAULT_TASK_PATH)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--child-session-id", required=True)
    parser.add_argument("--parent-session-id", default=None)
    parser.add_argument("--pending-approval-id", required=True)
    parser.add_argument("--reviewer-session-id", default=None)
    parser.add_argument("--json", action="store_true", help="print only the final JSON summary")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        outcome = asyncio.run(run_reviewer(args))
    except Exception as exc:  # pragma: no cover - exercised in integration
        print_json({"ok": False, "error": str(exc), "type": "reviewer_error"})
        return 1

    payload = outcome.to_dict()
    if args.json:
        print_json(payload)
    else:
        print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
