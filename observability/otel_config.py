"""OpenTelemetry configuration for Edictum demos.

Three modes (auto-detected from environment):

1. GRAFANA CLOUD (or any OTLP backend)
     OTEL_EXPORTER_OTLP_ENDPOINT  — e.g. https://otlp-gateway-<region>.grafana.net/otlp
     OTEL_EXPORTER_OTLP_HEADERS   — URL-encoded, e.g. Authorization=Basic%20<base64>

   Header values MUST be URL-encoded per the OTel spec (%20 for spaces).
   The base64 token: echo -n "<instanceID>:<API token>" | base64

   Temporality defaults to CUMULATIVE (Grafana Cloud / Prometheus).
   Override: EDICTUM_OTEL_TEMPORALITY=delta

2. LOCAL OTLP — set OTEL_EXPORTER_OTLP_ENDPOINT to your collector
     (e.g. http://localhost:4318). No auth headers needed.

3. CONSOLE — set EDICTUM_OTEL_CONSOLE=1 (prints spans/metrics to terminal)

If none are set, OTel is silently disabled — demo still works.
"""

import logging
import os


def configure_otel() -> str:
    """Configure OTel exporters. Returns mode: 'otlp' | 'console' | 'disabled'."""
    endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")
    console = os.environ.get("EDICTUM_OTEL_CONSOLE", "").strip()

    if endpoint:
        return _configure_otlp(endpoint)
    elif console == "1":
        return _configure_console()
    else:
        return "disabled"


def _configure_otlp(endpoint: str) -> str:
    """OTLP/HTTP exporter → Grafana Cloud or local collector."""
    try:
        from opentelemetry import metrics, trace
        from opentelemetry.exporter.otlp.proto.http.metric_exporter import (
            OTLPMetricExporter,
        )
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
            OTLPSpanExporter,
        )
        from opentelemetry.sdk.metrics import MeterProvider
        from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
    except ImportError:
        print("⚠ OTel packages not installed. Run: pip install -r requirements.txt")
        return "disabled"

    # Parse headers from env — values are URL-encoded per the OTel spec
    # (e.g. "Authorization=Basic%20abc123") and may contain '=' in base64
    from urllib.parse import unquote

    headers_raw = os.environ.get("OTEL_EXPORTER_OTLP_HEADERS", "")
    headers = {}
    if headers_raw:
        for part in headers_raw.split(","):
            k, _, v = part.partition("=")
            if k and v:
                headers[k.strip()] = unquote(v.strip())

    resource = Resource.create(
        {
            "service.name": "edictum-demo",
            "service.version": "0.1.0",
            "deployment.environment": "demo",
        }
    )

    # Traces
    trace_exporter = OTLPSpanExporter(
        endpoint=f"{endpoint}/v1/traces",
        headers=headers,
    )
    tracer_provider = TracerProvider(resource=resource)
    tracer_provider.add_span_processor(BatchSpanProcessor(trace_exporter))
    trace.set_tracer_provider(tracer_provider)

    temporality = os.environ.get("EDICTUM_OTEL_TEMPORALITY", "cumulative").strip().lower()
    if temporality not in {"delta", "cumulative"}:
        temporality = "cumulative"

    # Metrics
    from opentelemetry.sdk.metrics import (
        Counter as SdkCounter,
        Histogram as SdkHistogram,
        ObservableCounter as SdkObservableCounter,
        ObservableGauge as SdkObservableGauge,
        ObservableUpDownCounter as SdkObservableUpDownCounter,
        UpDownCounter as SdkUpDownCounter,
    )
    from opentelemetry.sdk.metrics.export import AggregationTemporality

    t = AggregationTemporality.DELTA if temporality == "delta" else AggregationTemporality.CUMULATIVE
    preferred_temporality = {
        SdkCounter: t,
        SdkUpDownCounter: t,
        SdkHistogram: t,
        SdkObservableCounter: t,
        SdkObservableUpDownCounter: t,
        SdkObservableGauge: t,
    }
    metric_exporter = OTLPMetricExporter(
        endpoint=f"{endpoint}/v1/metrics",
        headers=headers,
        preferred_temporality=preferred_temporality,
    )
    # Note: PeriodicExportingMetricReader auto-inherits temporality from the
    # exporter via super().__init__(preferred_temporality=exporter._preferred_temporality)
    metric_reader = PeriodicExportingMetricReader(
        metric_exporter,
        export_interval_millis=5000,
    )
    meter_provider = MeterProvider(resource=resource, metric_readers=[metric_reader])
    metrics.set_meter_provider(meter_provider)

    # Suppress noisy export errors (e.g. 429 rate-limit from Grafana Cloud)
    # so they don't pollute demo output
    for logger_name in (
        "opentelemetry.exporter.otlp.proto.http.metric_exporter",
        "opentelemetry.exporter.otlp.proto.http._log_exporter",
        "opentelemetry.sdk.metrics._internal.export",
    ):
        logging.getLogger(logger_name).setLevel(logging.WARNING)

    return "otlp"


def _configure_console() -> str:
    """Console exporter — prints spans and metrics to terminal."""
    try:
        from opentelemetry import metrics, trace
        from opentelemetry.sdk.metrics import MeterProvider
        from opentelemetry.sdk.metrics.export import (
            ConsoleMetricExporter,
            PeriodicExportingMetricReader,
        )
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import (
            ConsoleSpanExporter,
            SimpleSpanProcessor,
        )
    except ImportError:
        print("⚠ OTel packages not installed. Run: pip install -r requirements.txt")
        return "disabled"

    resource = Resource.create(
        {
            "service.name": "edictum-demo",
            "service.version": "0.1.0",
        }
    )

    # Traces → stdout
    tracer_provider = TracerProvider(resource=resource)
    tracer_provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))
    trace.set_tracer_provider(tracer_provider)

    # Metrics → stdout every 10s
    metric_reader = PeriodicExportingMetricReader(
        ConsoleMetricExporter(), export_interval_millis=10000
    )
    meter_provider = MeterProvider(resource=resource, metric_readers=[metric_reader])
    metrics.set_meter_provider(meter_provider)

    return "console"


def shutdown_otel():
    """Flush and shut down OTel providers. Safe to call even if disabled."""
    try:
        from opentelemetry import metrics, trace

        tracer_provider = trace.get_tracer_provider()
        if hasattr(tracer_provider, "force_flush"):
            tracer_provider.force_flush()
        if hasattr(tracer_provider, "shutdown"):
            tracer_provider.shutdown()

        meter_provider = metrics.get_meter_provider()
        if hasattr(meter_provider, "force_flush"):
            meter_provider.force_flush()
        if hasattr(meter_provider, "shutdown"):
            meter_provider.shutdown()
    except Exception:
        pass
