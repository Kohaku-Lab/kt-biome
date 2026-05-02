"""OpenTelemetry Metrics Plugin — emit quantifiable agent metrics via OTLP.

Observes LLM calls, tool executions, sub-agent runs, compaction, and session
lifecycle via pre/post hooks.  Emits counters and histograms to an OTLP endpoint.

Requires: opentelemetry-api, opentelemetry-sdk, opentelemetry-exporter-otlp-proto-http
Install: pip install kt-biome[otel]

Usage:
    plugins:
      - name: otel_metrics
        module: kt_biome.plugins.otel_metrics
        class: OTelMetricsPlugin
        options:
          service_name: "kohaku-terrarium"
          endpoint: "http://localhost:4318/v1/metrics"
          export_interval: 30
"""

import os
import time
import uuid
from typing import Any

from kohakuterrarium.modules.plugin.base import BasePlugin, PluginContext
from kohakuterrarium.utils.logging import get_logger

logger = get_logger(__name__)

try:
    from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
    from opentelemetry.sdk.metrics import Counter, Histogram, MeterProvider
    from opentelemetry.sdk.metrics.export import AggregationTemporality, PeriodicExportingMetricReader
    from opentelemetry.sdk.resources import Resource
    _otel_available: bool = True
    _DELTA_TEMPORALITY = {Counter: AggregationTemporality.DELTA, Histogram: AggregationTemporality.DELTA}
except ImportError:
    _otel_available: bool = False
    _DELTA_TEMPORALITY = {}

try:
    from opentelemetry import trace as trace_api
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor
    from opentelemetry.trace.status import StatusCode
    _trace_available: bool = True
except ImportError:
    _trace_available: bool = False

# ── Instrument definitions (module-level constants) ─────────────────

_COUNTER_DEFS: list[tuple[str, str]] = [
    ("kt.llm.calls", "LLM call count"),
    ("kt.llm.tokens.prompt", "Prompt tokens"),
    ("kt.llm.tokens.completion", "Completion tokens"),
    ("kt.llm.tokens.cache_read", "Cache-read tokens"),
    ("kt.llm.tokens.cache_creation", "Cache-write tokens"),
    ("kt.llm.active_time", "Accumulated LLM wall-clock time in seconds"),
    ("kt.tool.calls", "Tool call count"),
    ("kt.tool.dispatches", "Tool dispatch count"),
    ("kt.tool.errors", "Failed tool calls"),
    ("kt.subagent.runs", "Sub-agent run count"),
    ("kt.subagent.errors", "Failed sub-agent runs"),
    ("kt.compact.count", "Compaction count"),
    ("kt.agent.starts", "Agent session starts"),
    ("kt.agent.stops", "Agent session stops"),
    ("kt.events", "Event count"),
    ("kt.interrupts", "Interrupt count"),
]

_HISTOGRAM_DEFS: list[tuple[str, str, str]] = [
    ("kt.llm.duration", "LLM call latency", "ms"),
    ("kt.tool.duration", "Tool execution latency", "ms"),
    ("kt.subagent.duration", "Sub-agent run latency", "ms"),
    ("kt.subagent.turns", "Sub-agent turns", "1"),
    ("kt.compact.context_length", "Context length before compact", "1"),
    ("kt.compact.messages_removed", "Messages removed during compact", "1"),
    ("kt.agent.session.duration", "Agent session duration", "s"),
]


class OTelMetricsPlugin(BasePlugin):
    name = "otel_metrics"
    priority = 1  # First to observe

    def __init__(self, options: dict[str, Any] | None = None, **kwargs: Any):
        super().__init__()
        # Loader calls cls(**options), fallback calls cls(options={...})
        opts = {**(options or {}), **kwargs}
        self._service_name: str = opts.get("service_name", "kohaku-terrarium")
        endpoint = opts.get("endpoint")
        if not endpoint:
            endpoint = os.environ.get("OTEL_EXPORTER_OTLP_METRICS_ENDPOINT")
        if not endpoint:
            base = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")
            endpoint = (
                f"{base.rstrip('/')}/v1/metrics" if base
                else "http://localhost:4318/v1/metrics"
            )
        self._endpoint: str = endpoint
        self._trace_endpoint: str | None = opts.get("trace_endpoint")
        self._export_interval: int = int(opts.get("export_interval", 30))
        self._resource_attrs: dict[str, str] = opts.get("resource_attributes", {})
        self._agent_name: str = ""
        self._session_start: float = 0.0
        self._start_times: dict[int | str, float] = {}
        self._ctx: PluginContext | None = None
        self._provider: Any | None = None
        self._meter: Any | None = None
        self._tracer_provider: Any | None = None
        self._tracer: Any | None = None
        self._counters: dict[str, Any] = {}
        self._histograms: dict[str, Any] = {}
        self._active_spans: dict[int | str, Any] = {}
        self._fallback_session_id: str = ""

    @property
    def _session_id(self) -> str:
        sid = getattr(self._ctx, "session_id", "") if self._ctx else ""
        if sid:
            return sid
        if not self._fallback_session_id:
            self._fallback_session_id = uuid.uuid4().hex
        return self._fallback_session_id

    # ── Centralised helpers ─────────────────────────────────────────

    def _resolve_model(self, kwargs: dict[str, Any]) -> str:
        model = kwargs.get("model", "")
        if not model and self._ctx is not None:
            ctrl = self._ctx.controller
            if ctrl is not None:
                model = getattr(getattr(ctrl.llm, "config", None), "model", "") or ""
        return model or "unknown"

    def _inc(self, name: str, value: int | float, attrs: dict[str, str] | None = None) -> None:
        try:
            c = self._counters.get(name)
            if c is not None:
                c.add(value, attrs or {})
        except Exception:
            logger.warning("metric add failed", metric=name)

    def _observe(self, name: str, value: int | float, attrs: dict[str, str] | None = None) -> None:
        try:
            h = self._histograms.get(name)
            if h is not None:
                h.record(value, attrs or {})
        except Exception:
            logger.warning("metric record failed", metric=name)

    # ── Lifecycle ───────────────────────────────────────────────────

    async def on_load(self, context: PluginContext) -> None:
        self._agent_name = context.agent_name
        self._ctx = context
        self._start_times = {}
        self._session_start = time.monotonic()
        if not _otel_available:
            logger.warning("opentelemetry packages not installed; plugin is no-op")
            return

        resource = Resource.create({"service.name": self._service_name, **self._resource_attrs})
        exporter = OTLPMetricExporter(endpoint=self._endpoint, preferred_temporality=_DELTA_TEMPORALITY)
        reader = PeriodicExportingMetricReader(exporter, export_interval_millis=self._export_interval * 1000)
        self._provider = MeterProvider(resource=resource, metric_readers=[reader])
        self._meter = self._provider.get_meter("kohaku-terrarium")

        for name, desc in _COUNTER_DEFS:
            self._counters[name] = self._meter.create_counter(name, description=desc)
        for name, desc, unit in _HISTOGRAM_DEFS:
            self._histograms[name] = self._meter.create_histogram(name, description=desc, unit=unit)

        if _trace_available:
            if self._trace_endpoint:
                trace_endpoint = self._trace_endpoint
            else:
                trace_base = self._endpoint.replace("/v1/metrics", "").rstrip("/")
                trace_endpoint = f"{trace_base}/v1/traces"
            span_exporter = OTLPSpanExporter(endpoint=trace_endpoint)
            self._tracer_provider = TracerProvider(resource=resource)
            self._tracer_provider.add_span_processor(BatchSpanProcessor(span_exporter))
            self._tracer = self._tracer_provider.get_tracer("kohaku-terrarium")

        logger.info("OTel metrics initialised", endpoint=self._endpoint, service=self._service_name)

    async def on_unload(self) -> None:
        if self._tracer_provider is not None:
            try:
                self._tracer_provider.force_flush()
            except Exception:
                pass
            try:
                self._tracer_provider.shutdown()
            except Exception:
                pass
            self._tracer_provider = None
            self._tracer = None
        if self._provider is not None:
            try:
                self._provider.force_flush()
            except Exception:
                pass
            try:
                self._provider.shutdown()
            except Exception:
                pass
            self._provider = None
            self._meter = None

    async def on_agent_start(self) -> None:
        self._inc("kt.agent.starts", 1, {"agent": self._agent_name})

    async def on_agent_stop(self) -> None:
        self._inc("kt.agent.stops", 1, {"agent": self._agent_name})
        if self._session_start:
            elapsed = time.monotonic() - self._session_start
            self._observe("kt.agent.session.duration", elapsed, {"agent": self._agent_name})

    # ── LLM hooks ───────────────────────────────────────────────────

    async def pre_llm_call(self, messages, **kwargs):
        key = id(messages)
        self._start_times[key] = time.monotonic()
        if self._tracer is not None:
            span = self._tracer.start_span("kt.llm.call", attributes={"request_source": "main"})
            self._active_spans[key] = span
        return None

    async def post_llm_call(self, messages, response, usage, **kwargs):
        model = self._resolve_model(kwargs)
        session_id = self._session_id
        key = id(messages)
        start = self._start_times.pop(key, None)
        timed = start is not None
        elapsed_s = time.monotonic() - start if timed else 0
        duration_ms = elapsed_s * 1000
        u = usage or {}
        attrs = {"model": model, "request_source": "main", "session_id": session_id}
        self._inc("kt.llm.calls", 1, attrs)
        self._inc("kt.llm.tokens.prompt", u.get("prompt_tokens", 0), attrs)
        self._inc("kt.llm.tokens.completion", u.get("completion_tokens", 0), attrs)
        self._inc("kt.llm.tokens.cache_read", u.get("cached_tokens", 0), attrs)
        self._inc("kt.llm.tokens.cache_creation", u.get("cache_write_tokens", 0), attrs)
        if timed:
            self._inc("kt.llm.active_time", elapsed_s, attrs)
            self._observe("kt.llm.duration", duration_ms, attrs)

        span = self._active_spans.pop(key, None)
        if span is not None:
            span.set_attribute("model", model)
            span.set_attribute("session_id", session_id)
            span.set_attribute("request_source", "main")
            span.set_attribute("llm.prompt_tokens", u.get("prompt_tokens", 0))
            span.set_attribute("llm.completion_tokens", u.get("completion_tokens", 0))
            span.set_attribute("llm.cache_read_tokens", u.get("cached_tokens", 0))
            span.set_attribute("llm.cache_creation_tokens", u.get("cache_write_tokens", 0))
            span.set_status(StatusCode.OK)
            span.end()

        return None

    # ── Tool hooks ──────────────────────────────────────────────────

    async def pre_tool_dispatch(self, call, context, **kwargs):
        self._inc("kt.tool.dispatches", 1, {"tool_name": getattr(call, "name", ""), "session_id": self._session_id})
        return None

    async def pre_tool_execute(self, args, **kwargs):
        job_id = kwargs.get("job_id", "")
        self._start_times[job_id] = time.monotonic()
        if self._tracer is not None:
            span = self._tracer.start_span("kt.tool.execute", attributes={"tool_name": kwargs.get("tool_name", "")})
            self._active_spans[job_id] = span
        return None

    async def post_tool_execute(self, result, **kwargs):
        tool_name = kwargs.get("tool_name", "")
        job_id = kwargs.get("job_id", "")
        start = self._start_times.pop(job_id, None)
        duration = (time.monotonic() - start) * 1000 if start is not None else 0
        attrs = {"tool_name": tool_name, "session_id": self._session_id}
        success = getattr(result, "success", True) if result else True
        self._inc("kt.tool.calls", 1, attrs)
        self._observe("kt.tool.duration", duration, attrs)
        if not success:
            self._inc("kt.tool.errors", 1, attrs)

        span = self._active_spans.pop(job_id, None)
        if span is not None:
            span.set_attribute("success", success)
            if not success:
                span.set_status(StatusCode.ERROR)
            else:
                span.set_status(StatusCode.OK)
            span.end()

        return None

    # ── Sub-agent hooks ─────────────────────────────────────────────

    async def pre_subagent_run(self, task, **kwargs):
        job_id = kwargs.get("job_id", "")
        self._start_times[job_id] = time.monotonic()
        if self._tracer is not None:
            span = self._tracer.start_span("kt.subagent.run", attributes={
                "subagent_name": kwargs.get("name", ""),
                "request_source": "subagent",
            })
            self._active_spans[job_id] = span
        return None

    async def post_subagent_run(self, result, **kwargs):
        name = kwargs.get("name", "")
        session_id = self._session_id
        job_id = kwargs.get("job_id", "")
        start = self._start_times.pop(job_id, None)
        duration = (time.monotonic() - start) * 1000 if start is not None else 0
        success = getattr(result, "success", True)
        turns = getattr(result, "turns", 0)
        attrs = {"subagent_name": name, "request_source": "subagent", "session_id": session_id}
        self._inc("kt.subagent.runs", 1, attrs)
        self._observe("kt.subagent.duration", duration, attrs)
        self._observe("kt.subagent.turns", turns, attrs)
        if not success:
            self._inc("kt.subagent.errors", 1, attrs)

        span = self._active_spans.pop(job_id, None)
        if span is not None:
            span.set_attribute("session_id", session_id)
            span.set_attribute("success", success)
            span.set_attribute("turns", turns)
            span.set_status(StatusCode.OK if success else StatusCode.ERROR)
            span.end()

        return None

    # ── Compact hooks ───────────────────────────────────────────────

    async def on_compact_start(self, context_length: int) -> None:
        attrs = {"session_id": self._session_id}
        self._inc("kt.compact.count", 1, attrs)
        self._observe("kt.compact.context_length", context_length, attrs)

    async def on_compact_end(self, summary: str, messages_removed: int) -> None:
        self._observe("kt.compact.messages_removed", messages_removed or 0, {"session_id": self._session_id})

    # ── Event / interrupt callbacks ─────────────────────────────────

    async def on_event(self, event=None) -> None:
        event_type = getattr(event, "type", "unknown") if event else "unknown"
        self._inc("kt.events", 1, {"event_type": event_type, "session_id": self._session_id})

    async def on_interrupt(self) -> None:
        self._inc("kt.interrupts", 1, {"session_id": self._session_id})
