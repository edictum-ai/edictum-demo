from __future__ import annotations

from pathlib import Path

import pytest

from demos.hero.common import DEFAULT_TASK_PATH, HeroWorkspace, WORKFLOW_PATH
from edictum import Session, WorkflowRuntime, load_workflow
from edictum.envelope import create_envelope
from edictum.storage import MemoryBackend
from edictum.workflow.state import save_state
from edictum.workflow.result import WorkflowState


@pytest.mark.asyncio
async def test_docs_update_advances_into_push_pr(tmp_path: Path) -> None:
    runtime = WorkflowRuntime(load_workflow(WORKFLOW_PATH))
    session = Session("hero-docs-stage", MemoryBackend())
    await save_state(
        session,
        runtime.definition,
        WorkflowState(
            session_id="hero-docs-stage",
            active_stage="docs-update",
            completed_stages=[
                "read-analyze",
                "create-branch",
                "baseline-verify",
                "implement",
                "local-verify",
                "external-review",
            ],
        ),
    )

    decision = await runtime.evaluate(
        session,
        create_envelope("Bash", {"command": "git add ."}),
    )

    assert decision.action == "allow"
    assert decision.stage_id == "push-pr"


def test_workspace_review_finding_clears_after_second_pass(tmp_path: Path) -> None:
    workspace = HeroWorkspace.initialize(tmp_path, task_text=DEFAULT_TASK_PATH.read_text(encoding="utf-8"))
    workspace.edit_text(
        "src/hero_cli.py",
        "VERBOSE_FLAG = False\nVERBOSE_FLAG_COMPLETE = False\n",
        (
            "VERBOSE_FLAG = True\n"
            "VERBOSE_FLAG_COMPLETE = True\n"
            "# REVIEW_TODO: tighten the user-facing summary before approval\n"
        ),
    )
    assert workspace.current_review_findings() == [
        "src/hero_cli.py still carries the reviewer TODO marker"
    ]

    workspace.edit_text(
        "src/hero_cli.py",
        (
            "VERBOSE_FLAG = True\n"
            "VERBOSE_FLAG_COMPLETE = True\n"
            "# REVIEW_TODO: tighten the user-facing summary before approval\n"
        ),
        "VERBOSE_FLAG = True\nVERBOSE_FLAG_COMPLETE = True\n",
    )
    assert workspace.current_review_findings() == []
