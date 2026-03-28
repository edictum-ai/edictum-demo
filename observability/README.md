# Observability

OpenTelemetry integration for Edictum-governed AI agents. Traces every governance
decision, metrics for allowed/denied counts, and a Grafana dashboard to visualize it all.

## Architecture

```
Agent (any framework)
  |
  v
Edictum guard.run()
  |
  +-- GovernanceTelemetry (tracer: "edictum")
  |     span: tool.execute {tool_name}
  |     counters: edictum.calls.allowed, edictum.calls.denied
  |
  +-- Engine governance tracer (tracer: "edictum.governance")
  |     span: edictum.evaluate  (one per audit event)
  |
  v
OTel SDK  -->  OTLP Collector  -->  Tempo (traces)
                                -->  Prometheus (metrics)
                                         |
                                         v
                                      Grafana dashboard
```

## Telemetry Schema

Edictum emits two types of spans from two independent tracers, plus two metric counters.

### Span: `tool.execute {tool_name}`

Emitted by `GovernanceTelemetry` (tracer name: `edictum`). One span per `guard.run()` call,
covering the full lifecycle from pre-execution through post-execution.

| Attribute | Type | Description |
|-----------|------|-------------|
| `tool.name` | string | Tool name |
| `tool.side_effect` | string | `pure`, `read`, `write`, or `irreversible` |
| `tool.call_index` | int | Sequential call index within the session |
| `governance.environment` | string | Execution environment |
| `governance.run_id` | string | Session/run ID |
| `governance.action` | string | `allowed`, `denied`, `would_deny`, `approved` |
| `governance.reason` | string | Denial reason (if denied) |
| `governance.would_deny_reason` | string | Reason (if observe mode) |
| `governance.tool_success` | bool | Whether the tool executed successfully |
| `governance.postconditions_passed` | bool | Whether postconditions passed (false = PII redacted) |
| `edictum.policy_version` | string | Contract bundle version (if set) |

### Span: `edictum.evaluate`

Emitted by the engine's governance tracer (tracer name: `edictum.governance`). One span per
audit event — typically 1-2 per tool call (pre-decision + post-execution).

| Attribute | Type | Description |
|-----------|------|-------------|
| `edictum.tool.name` | string | Tool name |
| `edictum.decision` | string | `call_denied`, `call_allowed`, `call_executed`, `call_would_deny`, `call_approval_requested`, etc. |
| `edictum.decision.reason` | string | Human-readable reason |
| `edictum.decision.source` | string | `precondition`, `sandbox`, `postcondition`, `session`, `hook` |
| `edictum.decision.name` | string | Name of the deciding contract/hook |
| `edictum.side_effect` | string | Tool classification |
| `edictum.environment` | string | Execution environment |
| `edictum.mode` | string | `enforce` or `observe` |
| `edictum.session.attempt_count` | int | Total attempts in this session |
| `edictum.session.execution_count` | int | Successful executions in this session |
| `edictum.tool.args` | string | JSON-serialized tool arguments |
| `edictum.principal.role` | string | Principal's RBAC role |
| `edictum.principal.user_id` | string | Principal's user ID |
| `edictum.principal.team` | string | Principal's team (if set) |
| `edictum.principal.ticket_ref` | string | Ticket reference (if set) |
| `edictum.principal.org_id` | string | Organization ID (if set) |
| `edictum.policy_version` | string | Contract bundle version |
| `edictum.policy_error` | bool | True if a policy evaluation error occurred |

Span status: `ERROR` for `call_denied`, `OK` for everything else.

### Metrics

| OTel Name | Prometheus Name | Type | Labels | Description |
|-----------|----------------|------|--------|-------------|
| `edictum.calls.allowed` | `edictum_calls_allowed_total` | Counter | `tool_name` | Allowed tool calls |
| `edictum.calls.denied` | `edictum_calls_denied_total` | Counter | `tool_name` | Denied tool calls |

Resource attribute `service.name` becomes Prometheus label `service_name`.

## Quick Start — Console Exporter

See spans and metrics printed to stdout. No infrastructure needed.

```bash
cd /path/to/edictum-demo
python observability/demo_otel.py
```

This runs 6 governance scenarios (allow, deny, redact, observe, RBAC, rate limit) and
prints every span and metric to the terminal.

## Local Grafana Stack

Full observability stack with Grafana, Tempo, Prometheus, and the OTel Collector.

### 1. Start the stack

```bash
cd observability
docker compose up -d
```

Services:
- **Grafana**: http://localhost:3000 (no login required)
- **Prometheus**: http://localhost:9090
- **Tempo**: http://localhost:3200
- **OTel Collector**: localhost:4317 (gRPC), localhost:4318 (HTTP)

### 2. Run the demo

```bash
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318 python observability/demo_otel.py
```

### 3. Open the dashboard

Go to http://localhost:3000 and find the **Edictum Governance** dashboard
(auto-provisioned on startup).

### 4. Tear down

```bash
cd observability
docker compose down -v
```

## Grafana Cloud / Remote OTLP

Set these environment variables to send telemetry to any OTLP-compatible backend:

```bash
export OTEL_EXPORTER_OTLP_ENDPOINT=https://otlp-gateway-<region>.grafana.net/otlp
export OTEL_EXPORTER_OTLP_HEADERS="Authorization=Basic%20<base64-token>"
```

The base64 token is `echo -n "<instanceID>:<API-token>" | base64`. Header values
must be URL-encoded per the OTel spec (`%20` for spaces).

Temporality defaults to CUMULATIVE (Grafana Cloud / Prometheus compatible).
Override with `EDICTUM_OTEL_TEMPORALITY=delta` for backends that require it.

### Grafana Cloud gotchas

- **Metric temporality**: Grafana Cloud (Mimir) requires **CUMULATIVE** for all instrument
  types. The SDK defaults `ObservableCounter` to DELTA which Mimir silently rejects.
  The `otel_config.py` forces CUMULATIVE for all types by default.
- **TraceQL in dashboards**: Grafana Cloud Tempo's trace search index has aggressive
  retention limits. Trace *list* panels don't work reliably in dashboards. Use TraceQL
  *metrics* (`| rate()`, `| quantile_over_time()`) for dashboard panels, and Explore
  (queryless mode) for individual trace inspection.
- **Service name filter**: Use `rootServiceName` in TraceQL (not `resource.service.name`)
  for Grafana Cloud Tempo.
- **Datasource UIDs**: Instance-specific (`grafanacloud-<stackname>-prom`). Run the
  rename script to match your instance before importing:
  ```bash
  ./observability/grafana/rename-datasources.sh grafanacloud-myorg-prom grafanacloud-myorg-traces
  ```

## Dashboard Panels

The Edictum Governance dashboard (`grafana/edictum-dashboard.json`) has 12 panels
across 4 rows:

| # | Panel | Source | What it shows |
|---|-------|--------|---------------|
| 1 | Governance Decisions | Prometheus | Allowed vs denied rate over time |
| 2 | Denial Rate | Prometheus | Percentage of calls denied (gauge) |
| 3 | Total Calls | Prometheus | Total governance-evaluated calls (stat) |
| 4 | Denials by Tool | Prometheus | Which tools get denied most |
| 5 | Allowed by Tool | Prometheus | Which tools are used most (allowed) |
| 6 | Denied vs Allowed per Tool | Prometheus | Stacked horizontal comparison |
| 7 | Denial Rate per Tool | Prometheus | Per-tool denial percentage |
| 8 | Span Rate (from Traces) | Tempo | Agent activity over time (TraceQL metrics) |
| 9 | Span Rate by Tool | Tempo | Trace rate grouped by span name |
| 10 | Error Rate (Denied Spans) | Tempo | Rate of ERROR-status spans |
| 11 | Span Duration (p50/p95/p99) | Tempo | Latency percentiles from traces |
| 12 | Explore Traces | — | Deep links to Explore for trace drill-down |

## Adapter Demo Integration

All v2 adapter demos support `--otel` to enable telemetry:

```bash
# Console output
python adapters/demo_langchain.py --otel console

# Send to local stack
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318 python adapters/demo_langchain.py --otel otlp

# Disabled (default)
python adapters/demo_langchain.py
```

## Files

| File | Description |
|------|-------------|
| `demo_otel.py` | Standalone OTel demo — 6 scenarios with console/OTLP export |
| `otel_config.py` | OTel setup — auto-detects OTLP, console, or disabled mode |
| `docker-compose.yml` | Local observability stack (4 services) |
| `otel-collector-config.yaml` | Collector pipeline: OTLP in, Tempo + Prometheus out |
| `tempo-config.yaml` | Tempo trace storage config |
| `prometheus.yml` | Prometheus scrape config |
| `grafana/edictum-dashboard.json` | 14-panel Grafana dashboard |
| `grafana/rename-datasources.sh` | Replace datasource UIDs for Grafana Cloud import |
| `grafana/provisioning/` | Auto-provisioning for datasources and dashboards |

## Graceful Degradation

If `opentelemetry-sdk` is not installed, all telemetry becomes a no-op:
- `GovernanceTelemetry` returns `_NoOpSpan` instances
- Engine skips `_emit_otel_governance_span()` entirely
- Zero runtime overhead — governance still works, just without telemetry

Install OTel support: `pip install edictum[otel]`
