"""Shared support code for the repeatable hero demo."""

from __future__ import annotations

import asyncio
import base64
import copy
import difflib
import fnmatch
import json
import os
import re
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - optional in minimal environments
    load_dotenv = None

from edictum import Edictum, Principal, Session, WorkflowRuntime, load_workflow
from edictum.adapters.langchain import LangChainAdapter
from edictum.approval import ApprovalRequest
from edictum.audit import AuditAction, AuditEvent
from edictum.server import EdictumServerClient, ServerApprovalBackend, ServerAuditSink, ServerBackend
from edictum.server.client import EdictumServerError
from edictum.workflow.state import build_workflow_snapshot

REPO_ROOT = Path(__file__).resolve().parents[2]
HERO_ROOT = Path(__file__).resolve().parent
WORKFLOW_PATH = REPO_ROOT / "workflows" / "coding-guard.yaml"
DEFAULT_TASK_PATH = HERO_ROOT / "TASK.md"
DEFAULT_API_URL = "http://127.0.0.1:8080"
DEFAULT_ENVIRONMENT = "hero-demo"
STATE_FILE = ".hero_state.json"
BASELINE_FILE = ".hero_baseline.json"
_REPO_ENV_PATH = REPO_ROOT / ".env"
_REPO_ENV_LOADED = False


def _load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].lstrip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key or key in os.environ:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        os.environ[key] = value


def ensure_repo_env_loaded() -> None:
    global _REPO_ENV_LOADED
    if _REPO_ENV_LOADED:
        return
    if load_dotenv is not None:
        load_dotenv(_REPO_ENV_PATH)
    else:
        _load_env_file(_REPO_ENV_PATH)
    _REPO_ENV_LOADED = True


JsonDict = dict[str, Any]


def utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def build_session_id(prefix: str) -> str:
    token = uuid.uuid4().hex[:10]
    return f"{prefix}-{token}"


def read_task_text(task_path: Path | None = None) -> str:
    path = task_path or DEFAULT_TASK_PATH
    return path.read_text(encoding="utf-8").strip()


def print_json(payload: JsonDict) -> None:
    print(json.dumps(payload, sort_keys=True), flush=True)


@dataclass(slots=True)
class HeroConfig:
    api_url: str
    api_key: str
    environment: str = DEFAULT_ENVIRONMENT
    parent_agent_id: str = "hero-parent"
    child_agent_id: str = "hero-child"
    reviewer_agent_id: str = "hero-reviewer"
    poll_interval: float = 0.5

    @classmethod
    def from_env(cls, *, api_url: str | None = None, api_key: str | None = None) -> "HeroConfig":
        ensure_repo_env_loaded()
        effective_key = api_key or os.environ.get("EDICTUM_API_KEY", "")
        if not effective_key:
            raise RuntimeError("EDICTUM_API_KEY is required for the hero demo")
        return cls(
            api_url=(api_url or os.environ.get("EDICTUM_URL") or DEFAULT_API_URL).rstrip("/"),
            api_key=effective_key,
        )


@dataclass(slots=True)
class ToolInvocationResult:
    tool_name: str
    args: JsonDict
    text: str
    denied: bool


@dataclass(slots=True)
class ReviewOutcome:
    reviewer_session_id: str
    reviewer_agent_id: str
    pending_approval_id: str
    findings: list[str]
    action: str
    reset_approval_id: str | None = None
    approved: bool = False
    rejected: bool = False
    workflow: JsonDict | None = None

    def to_dict(self) -> JsonDict:
        return asdict(self)


@dataclass(slots=True)
class ChildRuntimeHandles:
    guard: Edictum
    adapter: "LineageLangChainAdapter"
    backend: ServerBackend
    client: EdictumServerClient
    audit_sink: ServerAuditSink
    workflow_runtime: WorkflowRuntime
    session: Session


class LineageLangChainAdapter(LangChainAdapter):
    """Expose lineage setters without patching the upstream adapter."""

    def set_parent_session_id(self, parent_session_id: str | None) -> None:
        self._parent_session_id = parent_session_id


class SessionAwareApprovalBackend(ServerApprovalBackend):
    """Fill in session_id and rule_name until the upstream adapter does."""

    def __init__(
        self,
        client: EdictumServerClient,
        *,
        default_session_id: str,
        poll_interval: float = 0.5,
    ) -> None:
        super().__init__(client, poll_interval=poll_interval)
        self._default_session_id = default_session_id

    async def request_approval(
        self,
        tool_name: str,
        tool_args: JsonDict,
        message: str,
        *,
        timeout: int = 300,
        timeout_action: str = "block",
        principal: dict | None = None,
        metadata: dict[str, Any] | None = None,
        session_id: str | None = None,
    ) -> ApprovalRequest:
        effective_session_id = session_id or self._default_session_id
        rule_name = tool_name
        if metadata and isinstance(metadata.get("rule_name"), str):
            rule_name = metadata["rule_name"]
        body: JsonDict = {
            "agent_id": self._client.agent_id,
            "tool_name": tool_name,
            "tool_args": tool_args,
            "message": message,
            "rule_name": rule_name,
            "timeout": timeout,
            "timeout_action": timeout_action,
        }
        if effective_session_id:
            body["session_id"] = effective_session_id
        response = await self._client.post("/v1/approvals", body)
        request = ApprovalRequest(
            approval_id=response["id"],
            tool_name=tool_name,
            tool_args=tool_args,
            message=message,
            timeout=timeout,
            timeout_action=timeout_action,
            principal=principal,
            metadata=metadata or {},
            session_id=effective_session_id,
        )
        self._pending[response["id"]] = request
        return request


class EncodedServerBackend(ServerBackend):
    """Translate Edictum session keys into the API's stricter key format."""

    def _transport_key(self, key: str) -> str:
        parts = key.split(":", 2)
        if len(parts) == 3 and parts[0] == "s":
            session_id = parts[1]
            counter = parts[2]
        else:
            session_id = "legacy"
            counter = key
        encoded_counter = base64.urlsafe_b64encode(counter.encode("utf-8")).decode("ascii").rstrip("=")
        return f"{session_id}:{encoded_counter}"

    async def _request(self, method: str, path: str, **kwargs: Any) -> JsonDict:
        client = self._client._ensure_client()
        response = await client.request(method, path, **kwargs)
        if response.status_code >= 400:
            raise EdictumServerError(response.status_code, response.text)
        if not response.content:
            return {}
        return dict(response.json())

    async def get(self, key: str) -> str | None:
        try:
            response = await self._request("GET", f"/v1/sessions/{self._transport_key(key)}")
            return response.get("value")
        except EdictumServerError as exc:
            if exc.status_code == 404:
                return None
            raise

    async def set(self, key: str, value: str) -> None:
        await self._request("PUT", f"/v1/sessions/{self._transport_key(key)}", json={"value": value})

    async def delete(self, key: str) -> None:
        try:
            await self._request("DELETE", f"/v1/sessions/{self._transport_key(key)}")
        except EdictumServerError as exc:
            if exc.status_code != 404:
                raise

    async def increment(self, key: str, amount: float = 1) -> float:
        response = await self._request(
            "POST",
            f"/v1/sessions/{self._transport_key(key)}/increment",
            json={"amount": amount},
        )
        return response["value"]

    async def batch_get(self, keys: list[str]) -> dict[str, str | None]:
        if not keys:
            return {}
        encoded = {key: self._transport_key(key) for key in keys}
        try:
            response = await self._request(
                "POST",
                "/v1/sessions/batch",
                json={"keys": list(encoded.values())},
            )
            values = response.get("values", {})
            return {key: values.get(encoded_key) for key, encoded_key in encoded.items()}
        except EdictumServerError as exc:
            if exc.status_code not in {404, 405}:
                raise
            result: dict[str, str | None] = {}
            for key in keys:
                result[key] = await self.get(key)
            return result


class HeroServerAuditSink(ServerAuditSink):
    """Bridge current Python SDK actions onto the API's narrower action set."""

    def _map_action(self, action: Any) -> str:
        if action == "call_executed":
            return "call_allowed"
        if action == "call_failed":
            return "call_blocked"
        return super()._map_action(action)


class HeroApiClient:
    """Small query/decision client for the runner and reviewer."""

    def __init__(self, config: HeroConfig) -> None:
        self._config = config
        self._client = httpx.AsyncClient(
            base_url=config.api_url,
            headers={"Authorization": f"Bearer {config.api_key}"},
            timeout=10.0,
        )
        self._workflow_state_supported: bool | None = None

    async def __aenter__(self) -> "HeroApiClient":
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.close()

    async def close(self) -> None:
        await self._client.aclose()

    async def wait_for_health(self, timeout_seconds: float = 30.0) -> None:
        deadline = asyncio.get_running_loop().time() + timeout_seconds
        last_error: Exception | None = None
        while asyncio.get_running_loop().time() < deadline:
            try:
                response = await self._client.get("/v1/health")
                response.raise_for_status()
                return
            except Exception as exc:  # pragma: no cover - exercised in integration
                last_error = exc
                await asyncio.sleep(0.5)
        raise RuntimeError(f"edictum-api did not become healthy: {last_error}") from last_error

    async def list_events(
        self,
        *,
        agent_id: str | None = None,
        session_id: str | None = None,
        parent_session_id: str | None = None,
        limit: int = 500,
    ) -> list[JsonDict]:
        params: JsonDict = {"limit": limit}
        if agent_id:
            params["agent_id"] = agent_id
        if session_id:
            params["session_id"] = session_id
        if parent_session_id:
            params["parent_session_id"] = parent_session_id
        response = await self._client.get("/v1/events", params=params)
        response.raise_for_status()
        body = response.json()
        return list(body.get("events", []))

    async def list_approvals(
        self,
        *,
        agent_id: str | None = None,
        session_id: str | None = None,
        status: str | None = None,
    ) -> list[JsonDict]:
        params: JsonDict = {}
        if agent_id:
            params["agent_id"] = agent_id
        if session_id:
            params["session_id"] = session_id
        if status:
            params["status"] = status
        response = await self._client.get("/v1/approvals", params=params)
        response.raise_for_status()
        body = response.json()
        return list(body.get("approvals", []))

    async def get_approval(self, approval_id: str) -> JsonDict:
        response = await self._client.get(f"/v1/approvals/{approval_id}")
        response.raise_for_status()
        return dict(response.json())

    async def decide_approval(
        self,
        approval_id: str,
        *,
        decision: str,
        decided_by: str,
        decided_via: str,
        reason: str,
    ) -> None:
        response = await self._client.post(
            f"/v1/approvals/{approval_id}/decide",
            json={
                "decision": decision,
                "decided_by": decided_by,
                "decided_via": decided_via,
                "reason": reason,
            },
        )
        response.raise_for_status()

    async def workflow_state(self, *, agent_id: str, session_id: str) -> tuple[str, JsonDict | None]:
        if self._workflow_state_supported is not False:
            response = await self._client.get(
                f"/v1/agents/{agent_id}/workflow-state",
                params={"session_id": session_id},
            )
            if response.status_code == 200:
                self._workflow_state_supported = True
                return "endpoint", dict(response.json())
            if response.status_code not in {404, 405}:
                response.raise_for_status()
        events = await self.list_events(agent_id=agent_id, session_id=session_id)
        if self._workflow_state_supported is None and events:
            self._workflow_state_supported = False
        for event in reversed(events):
            workflow = event.get("workflow")
            if isinstance(workflow, dict):
                return "events", copy.deepcopy(workflow)
        return "events", None


class HeroWorkspace:
    """Deterministic workspace that the child tools operate on."""

    def __init__(self, root: Path, baseline: dict[str, str], state: JsonDict) -> None:
        self.root = root
        self._baseline = baseline
        self._state = state

    @classmethod
    def initialize(cls, root: Path, *, task_text: str) -> "HeroWorkspace":
        root.mkdir(parents=True, exist_ok=True)
        baseline_path = root / BASELINE_FILE
        state_path = root / STATE_FILE
        if baseline_path.exists() and state_path.exists():
            return cls.load(root)

        files = {
            "README.md": (
                "# Hero Workspace\n\n"
                "This workspace simulates a small CLI project used by the Edictum hero demo.\n"
                "The task is to add a deterministic `--verbose` flag and carry the change through review.\n"
            ),
            "TASK.md": task_text + "\n",
            "src/hero_cli.py": (
                "from __future__ import annotations\n\n"
                "VERBOSE_FLAG = False\n"
                "VERBOSE_FLAG_COMPLETE = False\n\n"
                "def run(verbose: bool = False) -> str:\n"
                "    if verbose:\n"
                "        return \"debug: verbose mode active\"\n"
                "    return \"ok\"\n"
            ),
            "tests/test_hero_cli.py": (
                "from src.hero_cli import VERBOSE_FLAG_COMPLETE, run\n\n"
                "def test_verbose_flag_path() -> None:\n"
                "    assert run(verbose=True).startswith(\"debug:\")\n"
                "    assert VERBOSE_FLAG_COMPLETE is True\n"
            ),
        }
        for relative_path, content in files.items():
            path = root / relative_path
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")

        baseline_path.write_text(json.dumps(files, indent=2, sort_keys=True), encoding="utf-8")
        state = {
            "branch_name": "master",
            "implement_pass": 0,
            "review_reset_count": 0,
            "staged_paths": [],
            "last_commit": "",
            "pushed": False,
            "pr_number": None,
            "pr_url": "",
            "ci_green": False,
            "created_at": utc_now(),
            "updated_at": utc_now(),
        }
        state_path.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")
        return cls(root=root, baseline=files, state=state)

    @classmethod
    def load(cls, root: Path) -> "HeroWorkspace":
        baseline = json.loads((root / BASELINE_FILE).read_text(encoding="utf-8"))
        state = json.loads((root / STATE_FILE).read_text(encoding="utf-8"))
        return cls(root=root, baseline=dict(baseline), state=dict(state))

    def to_summary(self) -> JsonDict:
        return {
            "root": str(self.root),
            "branch_name": self.branch_name,
            "implement_pass": self.implement_pass,
            "review_reset_count": self.review_reset_count,
            "changed_files": self.changed_files(),
            "pushed": bool(self._state.get("pushed")),
            "pr_url": self._state.get("pr_url", ""),
            "ci_green": bool(self._state.get("ci_green")),
        }

    @property
    def branch_name(self) -> str:
        return str(self._state.get("branch_name", "master"))

    @property
    def implement_pass(self) -> int:
        return int(self._state.get("implement_pass", 0))

    @property
    def review_reset_count(self) -> int:
        return int(self._state.get("review_reset_count", 0))

    def _save_state(self) -> None:
        self._state["updated_at"] = utc_now()
        (self.root / STATE_FILE).write_text(json.dumps(self._state, indent=2, sort_keys=True), encoding="utf-8")

    def _resolve(self, relative_path: str) -> Path:
        if not relative_path:
            raise ValueError("relative_path is required")
        candidate = (self.root / relative_path).resolve()
        root_resolved = self.root.resolve()
        if candidate != root_resolved and root_resolved not in candidate.parents:
            raise ValueError(f"path {relative_path!r} escapes the hero workspace")
        return candidate

    def read_text(self, relative_path: str) -> str:
        return self._resolve(relative_path).read_text(encoding="utf-8")

    def write_text(self, relative_path: str, content: str) -> None:
        path = self._resolve(relative_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        self._save_state()

    def edit_text(self, relative_path: str, old: str, new: str) -> None:
        content = self.read_text(relative_path)
        if old not in content:
            raise ValueError(f"edit target not found in {relative_path}")
        self.write_text(relative_path, content.replace(old, new, 1))

    def glob_paths(self, pattern: str) -> list[str]:
        matches: list[str] = []
        for path in self.root.rglob("*"):
            if not path.is_file():
                continue
            relative = path.relative_to(self.root).as_posix()
            if relative in {STATE_FILE, BASELINE_FILE}:
                continue
            if fnmatch.fnmatch(relative, pattern):
                matches.append(relative)
        return sorted(matches)

    def grep(self, pattern: str) -> list[str]:
        matcher = re.compile(pattern)
        results: list[str] = []
        for relative_path in self.glob_paths("**/*"):
            for line_no, line in enumerate(self.read_text(relative_path).splitlines(), start=1):
                if matcher.search(line):
                    results.append(f"{relative_path}:{line_no}:{line}")
        return results

    def changed_files(self) -> list[str]:
        changed: list[str] = []
        for path in self.root.rglob("*"):
            if not path.is_file():
                continue
            relative = path.relative_to(self.root).as_posix()
            if relative in {STATE_FILE, BASELINE_FILE}:
                continue
            current = path.read_text(encoding="utf-8")
            baseline = self._baseline.get(relative)
            if baseline != current:
                changed.append(relative)
        return sorted(changed)

    def diff(self, paths: list[str] | None = None) -> str:
        selected = paths or self.changed_files()
        diff_chunks: list[str] = []
        for relative_path in selected:
            current = self.read_text(relative_path) if self._resolve(relative_path).exists() else ""
            baseline = self._baseline.get(relative_path, "")
            if baseline == current:
                continue
            diff_chunks.extend(
                difflib.unified_diff(
                    baseline.splitlines(),
                    current.splitlines(),
                    fromfile=f"a/{relative_path}",
                    tofile=f"b/{relative_path}",
                    lineterm="",
                )
            )
        return "\n".join(diff_chunks) or "No changes"

    def git_status_short(self) -> str:
        rows: list[str] = []
        staged = set(self._state.get("staged_paths", []))
        for relative_path in self.changed_files():
            prefix = "A" if relative_path not in self._baseline else "M"
            stage_prefix = prefix if relative_path in staged else " "
            rows.append(f"{stage_prefix}{prefix} {relative_path}")
        return "\n".join(rows) if rows else "clean"

    def increment_implement_pass(self) -> int:
        self._state["implement_pass"] = self.implement_pass + 1
        self._save_state()
        return self.implement_pass

    def record_review_reset(self) -> None:
        self._state["review_reset_count"] = self.review_reset_count + 1
        self._save_state()

    def current_review_findings(self) -> list[str]:
        findings: list[str] = []
        source = self.read_text("src/hero_cli.py")
        if "# REVIEW_TODO:" in source:
            findings.append("src/hero_cli.py still carries the reviewer TODO marker")
        if "VERBOSE_FLAG = True" not in source or "VERBOSE_FLAG_COMPLETE = True" not in source:
            findings.append("src/hero_cli.py does not finish the verbose flag implementation")
        return findings

    def simulate_bash(self, command: str) -> str:
        normalized = command.strip()
        if normalized.startswith("git switch -c "):
            branch_name = normalized.split()[-1]
            self._state["branch_name"] = branch_name
            self._save_state()
            return f"Switched to a new branch '{branch_name}'"

        if normalized.startswith("python -m compileall") or normalized.startswith("python3 -m compileall"):
            for relative_path in self.glob_paths("**/*.py"):
                compile(self.read_text(relative_path), relative_path, "exec")
            return "Listing 'src'...\nCompiling deterministic hero workspace"

        if normalized.startswith("python -m pytest") or normalized.startswith("python3 -m pytest") or normalized.startswith("pytest"):
            findings = self.current_review_findings()
            if "src/hero_cli.py still carries the reviewer TODO marker" in findings:
                findings = [item for item in findings if "TODO marker" not in item]
            if findings:
                return f"FAILED: {'; '.join(findings)}"
            return "1 passed in 0.01s"

        if normalized.startswith("git status"):
            return self.git_status_short()

        if normalized.startswith("git diff"):
            if " -- " in normalized:
                path_chunk = normalized.split(" -- ", 1)[1]
                selected = [item for item in path_chunk.split(" ") if item]
                return self.diff(selected)
            return self.diff()

        if normalized.startswith("git add"):
            self._state["staged_paths"] = self.changed_files()
            self._save_state()
            return "staged " + ", ".join(self._state["staged_paths"])

        if normalized.startswith("git commit"):
            staged = list(self._state.get("staged_paths", []))
            if not staged:
                return "Error: nothing staged to commit"
            self._state["last_commit"] = normalized
            self._save_state()
            return f"[{self.branch_name}] {normalized}"

        if normalized.startswith("git push"):
            if not self._state.get("last_commit"):
                return "Error: nothing committed to push"
            self._state["pushed"] = True
            self._save_state()
            return f"pushed {self.branch_name} to origin"

        if normalized.startswith("gh pr create"):
            self._state["pr_number"] = 1
            self._state["pr_url"] = f"https://example.test/hero/{self.branch_name}"
            self._save_state()
            return self._state["pr_url"]

        if normalized.startswith("gh pr status"):
            pr_url = self._state.get("pr_url") or "no-pr"
            return f"PR: {pr_url}"

        if normalized.startswith("gh pr checks") or normalized.startswith("gh run view") or normalized.startswith("gh run watch"):
            if not self._state.get("pushed") or not self._state.get("pr_url"):
                return "Error: PR is not ready for checks"
            self._state["ci_green"] = True
            self._save_state()
            return "All required checks passed"

        return f"Simulated bash command: {normalized}"


def make_principal(role: str, session_id: str) -> Principal:
    return Principal(
        service_id=f"{role}-service",
        role=role,
        claims={"session_id": session_id, "demo": "hero"},
    )


async def build_child_runtime(
    *,
    config: HeroConfig,
    session_id: str,
    parent_session_id: str | None,
    principal: Principal,
) -> ChildRuntimeHandles:
    client = EdictumServerClient(
        config.api_url,
        config.api_key,
        agent_id=config.child_agent_id,
        env=config.environment,
        allow_insecure=True,
    )
    audit_sink = HeroServerAuditSink(client, batch_size=1, flush_interval=0.1)
    backend = EncodedServerBackend(client)
    approval_backend = SessionAwareApprovalBackend(client, default_session_id=session_id, poll_interval=0.25)
    workflow_runtime = WorkflowRuntime(load_workflow(WORKFLOW_PATH))

    async def workflow_snapshot_provider(event: Any) -> JsonDict | None:
        event_session_id = getattr(event, "session_id", None)
        if not isinstance(event_session_id, str) or not event_session_id:
            return None
        state = await workflow_runtime.state(Session(event_session_id, backend))
        return build_workflow_snapshot(workflow_runtime.definition, state)

    audit_sink._workflow_snapshot_provider = workflow_snapshot_provider
    guard = Edictum(
        environment=config.environment,
        mode="enforce",
        tools={
            "Read": {"side_effect": "read", "idempotent": True},
            "Grep": {"side_effect": "read", "idempotent": True},
            "Glob": {"side_effect": "read", "idempotent": True},
            "Write": {"side_effect": "write", "idempotent": False},
            "Edit": {"side_effect": "write", "idempotent": False},
            "Bash": {"side_effect": "irreversible", "idempotent": False},
        },
        audit_sink=audit_sink,
        backend=backend,
        approval_backend=approval_backend,
        principal=principal,
        workflow_runtime=workflow_runtime,
    )
    adapter = LineageLangChainAdapter(guard, session_id=session_id, principal=principal)
    adapter.set_parent_session_id(parent_session_id)
    session = Session(session_id, backend)
    return ChildRuntimeHandles(
        guard=guard,
        adapter=adapter,
        backend=backend,
        client=client,
        audit_sink=audit_sink,
        workflow_runtime=workflow_runtime,
        session=session,
    )


async def close_child_runtime(handles: ChildRuntimeHandles) -> None:
    await handles.audit_sink.close()
    await handles.client.close()


async def emit_workflow_state_update(
    *,
    config: HeroConfig,
    child_session_id: str,
    parent_session_id: str | None,
    workflow: JsonDict,
    tool_args: JsonDict,
    principal: Principal | None,
) -> None:
    client = EdictumServerClient(
        config.api_url,
        config.api_key,
        agent_id=config.child_agent_id,
        env=config.environment,
        allow_insecure=True,
    )
    sink = HeroServerAuditSink(client, batch_size=1, flush_interval=0.1)
    try:
        await sink.emit(
            AuditEvent(
                action=AuditAction.WORKFLOW_STATE_UPDATED,
                run_id=child_session_id,
                call_id=str(uuid.uuid4()),
                call_index=0,
                session_id=child_session_id,
                parent_session_id=parent_session_id,
                tool_name="workflow_reset",
                tool_args=tool_args,
                side_effect="irreversible",
                environment=config.environment,
                principal=asdict(principal) if principal else None,
                mode="enforce",
                policy_version=None,
                workflow=copy.deepcopy(workflow),
            )
        )
        await sink.close()
    finally:
        await client.close()


async def apply_workflow_reset(
    *,
    config: HeroConfig,
    run_dir: Path,
    child_session_id: str,
    parent_session_id: str | None,
    target_stage: str,
    actor_principal: Principal | None,
) -> JsonDict:
    client = EdictumServerClient(
        config.api_url,
        config.api_key,
        agent_id=config.child_agent_id,
        env=config.environment,
        allow_insecure=True,
    )
    backend = EncodedServerBackend(client)
    runtime = WorkflowRuntime(load_workflow(WORKFLOW_PATH))
    try:
        session = Session(child_session_id, backend)
        workflow_events = await runtime.reset(session, target_stage)
        workflow = workflow_events[0]["workflow"] if workflow_events else build_workflow_snapshot(
            runtime.definition,
            await runtime.state(session),
        )
        await emit_workflow_state_update(
            config=config,
            child_session_id=child_session_id,
            parent_session_id=parent_session_id,
            workflow=workflow,
            tool_args={"target_stage": target_stage},
            principal=actor_principal,
        )
        workspace = HeroWorkspace.load(run_dir)
        workspace.record_review_reset()
        return workflow
    finally:
        await client.close()
