from __future__ import annotations

from pathlib import Path

import pytest

import demos.hero.common as hero_common
from demos.hero.child import build_tools
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


def test_hero_config_loads_dotenv_without_python_dotenv(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text(
        "EDICTUM_URL=http://127.0.0.1:18080\n"
        "EDICTUM_API_KEY=test-key\n",
        encoding="utf-8",
    )

    monkeypatch.delenv("EDICTUM_URL", raising=False)
    monkeypatch.delenv("EDICTUM_API_KEY", raising=False)
    monkeypatch.setattr(hero_common, "load_dotenv", None)
    monkeypatch.setattr(hero_common, "_REPO_ENV_PATH", env_path)
    monkeypatch.setattr(hero_common, "_REPO_ENV_LOADED", False)

    config = hero_common.HeroConfig.from_env()

    assert config.api_url == "http://127.0.0.1:18080"
    assert config.api_key == "test-key"


@pytest.mark.asyncio
async def test_build_tools_runs_without_langchain_core(tmp_path: Path) -> None:
    workspace = HeroWorkspace.initialize(tmp_path, task_text=DEFAULT_TASK_PATH.read_text(encoding="utf-8"))

    tools = build_tools(workspace)

    read_result = await tools["Read"].ainvoke({"path": "README.md"})
    bash_result = await tools["Bash"].ainvoke({"command": "python -m compileall src"})

    assert "Hero Workspace" in read_result
    assert "Compiling deterministic hero workspace" in bash_result
