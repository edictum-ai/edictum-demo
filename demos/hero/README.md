# Workflow Gates Hero Demo

This is the primary deterministic demo path for `edictum-demo`.

It shows the agency-control story end to end: an unbounded parent starts a bounded child, and the child must finish a coding task inside a declared Workflow Gates profile.

## Demo narrative

Without Edictum, the agent can jump ahead. With Edictum, the same agent must operate inside its declared profile.

The run demonstrates:

- read-before-write
- verification-before-push
- approval-before-critical-transition
- blocked action
- recorded evidence
- final behavioral conformance audit trail

The parent and child are deterministic so the demo proves runtime boundaries without depending on live LLM behavior.

Measurement boundary: this demo shows behavioral conformance to the declared workflow profile. It does not evaluate output quality such as accuracy, relevance, coherence, or answer quality.

## What Happens

The child must:

1. Read the workspace brief before editing.
2. Create a branch before implementation.
3. Run baseline verification before code changes.
4. Attempt an early push during implementation and get blocked.
5. Run local verification before review and push.
6. Pass through external review before the critical transition into delivery.
7. Record evidence for each transition.
8. Finish at `done` with workflow state, lineage, approvals, events, and final audit data captured by the API.

## What To Run

The hero demo assumes the sibling repos are checked out next to this one:

- `../edictum`
- `../edictum-api`

### 1. Start Postgres

```bash
cd ../edictum-api
docker-compose up -d
```

### 2. Start the API

```bash
cd ../edictum-api
export DATABASE_URL="postgresql://edictum:edictum@localhost:5432/edictum"
export API_KEY_SALT="test-salt-for-dev"
go run ./cmd/server/main.go serve
```

### 3. Bootstrap a demo workspace and API key

```bash
cd ../edictum-api
go run ./cmd/server/main.go bootstrap \
  --workspace-id ws-hero \
  --workspace-name "Hero Demo" \
  --api-key-name hero-key
```

Save the `api_key` from the JSON output.

### 4. Create the demo virtualenv

```bash
cd ../edictum-demo
uv venv .venv --clear
uv pip install -e "../edictum[otel,langchain]" \
  "langchain>=0.3.0" \
  "langchain-openai>=0.3.0" \
  "python-dotenv>=1.0.0" \
  pytest \
  pytest-asyncio
```

`pytest` and `pytest-asyncio` are included here on purpose.

### 5. Run the unit slice

```bash
.venv/bin/python -m pytest demos/hero/test_workflow_progression.py -v
```

Expected: `5 passed`

### 6. Run the actual demo

```bash
.venv/bin/python -m demos.hero.run \
  --api-url http://127.0.0.1:8080 \
  --api-key edk_YOUR_KEY \
  --runs 1 \
  --summary
```

Typical output shape:

```text
Hero demo PASS (1/1 runs succeeded)
run 1: ok session=hero-child-... stage=done events=77 approvals=2 blocked=yes resets=1
  stages: read-analyze -> create-branch -> baseline-verify -> implement -> local-verify -> external-review -> docs-update -> push-pr -> ci-green -> done
  last evidence: Bash: gh pr checks --watch
  behavioral conformance: read-before-write=yes verification-before-push=yes approval-before-critical-transition=yes blocked-action=yes evidence=recorded audit-trail=complete
  review: requested-reset, approved-external-review
```

Use `--json` for machine-readable output. Use `--pretty-json` for the full payload in an indented form.

### 7. Repeatability check

```bash
.venv/bin/python -m demos.hero.run \
  --api-url http://127.0.0.1:8080 \
  --api-key edk_YOUR_KEY \
  --runs 5 \
  --summary
```

Expected: all 5 runs succeed with the same shape.

## API Checks

Workflow state:

```bash
curl -H "Authorization: Bearer edk_YOUR_KEY" \
  "http://127.0.0.1:8080/v1/agents/hero-child/workflow-state?session_id=SESSION_ID"
```

Events:

```bash
curl -H "Authorization: Bearer edk_YOUR_KEY" \
  "http://127.0.0.1:8080/v1/events?agent_id=hero-child&limit=100" | jq '.total'
```

## One Important Detail

The workflow has 10 total stages if you count terminal `done`.

The API reports that as:

- `completed_stages`: the first 9 named stages
- `active_stage: "done"` once the run is finished

That is the correct behavior for the current workflow model.
