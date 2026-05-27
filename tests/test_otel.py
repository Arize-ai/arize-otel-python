import logging
from typing import Any, Dict, List, Optional
from unittest.mock import Mock, patch

from opentelemetry.context import Context
from opentelemetry.sdk.trace import ReadableSpan, SpanProcessor
from opentelemetry.sdk.trace.export import SpanExporter
from opentelemetry.trace import Span

from arize.otel.otel import (
    GRPCSpanExporter,
    SimpleSpanProcessor,
    Transport,
    _auto_instrument_installed_openinference_libraries,
    register,
)


class NoopSpanProcessor(SpanProcessor):
    def on_start(self, span: Span, parent_context: Optional[Context] = None) -> None:
        pass

    def on_end(self, span: ReadableSpan) -> None:
        pass

    def shutdown(self) -> None:
        pass

    def force_flush(self, timeout_millis: Optional[int] = None) -> bool:
        return True


class FakeEntryPoint:
    def __init__(self, instrumentor_class: Any) -> None:
        self._instrumentor_class = instrumentor_class

    def load(self) -> Any:
        return self._instrumentor_class


class SelectableEntryPoints:
    def __init__(self, entry_points: List[FakeEntryPoint]) -> None:
        self.selected_groups: List[str] = []
        self._entry_points = entry_points

    def select(self, *, group: str) -> List[FakeEntryPoint]:
        self.selected_groups.append(group)
        if group == "openinference_instrumentor":
            return self._entry_points
        return []


class RecordingInstrumentor:
    instances: List["RecordingInstrumentor"] = []

    def __init__(self) -> None:
        self.instrument = Mock()
        self.__class__.instances.append(self)


def _get_processors(tracer_provider: Any) -> Any:
    return tracer_provider._active_span_processor._span_processors


def _get_exporter_from_processor(span_processor: Any) -> Optional[SpanExporter]:
    return (
        getattr(
            getattr(span_processor, "_batch_processor", None),
            "_exporter",
            None,
        )
        or getattr(span_processor, "span_exporter", None)
        or getattr(span_processor, "_span_exporter", None)
    )


def _headers_as_dict(headers: Any) -> Dict[str, str]:
    if isinstance(headers, dict):
        return {key.lower(): value for key, value in headers.items()}
    return {key.lower(): value for key, value in headers}


def test_register_with_auto_instrument_calls_discovery_helper() -> None:
    with patch(
        "arize.otel.otel._auto_instrument_installed_openinference_libraries"
    ) as mock_auto_instrument:
        tracer_provider = register(
            space_id="test-space",
            api_key="test-api-key",
            project_name="test-project",
            auto_instrument=True,
            verbose=False,
            set_global_tracer_provider=False,
        )

    mock_auto_instrument.assert_called_once_with(tracer_provider)
    assert tracer_provider._default_processor is False


def test_register_adds_custom_span_processors_before_arize_exporter() -> None:
    custom_processor = NoopSpanProcessor()

    tracer_provider = register(
        space_id="test-space",
        api_key="test-api-key",
        project_name="test-project",
        batch=False,
        span_processors=[custom_processor],
        verbose=False,
        set_global_tracer_provider=False,
    )

    processors = _get_processors(tracer_provider)
    assert processors[0] is custom_processor
    assert isinstance(processors[1], SimpleSpanProcessor)
    assert isinstance(_get_exporter_from_processor(processors[1]), GRPCSpanExporter)
    assert tracer_provider._default_processor is False


def test_register_preserves_arize_headers_with_custom_span_processors() -> None:
    custom_processor = NoopSpanProcessor()

    tracer_provider = register(
        space_id="test-space",
        api_key="test-api-key",
        project_name="test-project",
        transport=Transport.GRPC,
        batch=False,
        headers={"X-Custom": "custom-value"},
        span_processors=[custom_processor],
        verbose=False,
        set_global_tracer_provider=False,
    )

    processors = _get_processors(tracer_provider)
    exporter = _get_exporter_from_processor(processors[-1])
    assert exporter is not None

    headers = _headers_as_dict(exporter._headers)
    assert headers["x-custom"] == "custom-value"
    assert headers["authorization"] == "test-api-key"
    assert headers["arize-space-id"] == "test-space"


def test_auto_instrument_loads_openinference_entry_points() -> None:
    RecordingInstrumentor.instances = []
    tracer_provider = Mock()
    entry_points = SelectableEntryPoints([FakeEntryPoint(RecordingInstrumentor)])

    with patch("arize.otel.otel.entry_points", return_value=entry_points):
        _auto_instrument_installed_openinference_libraries(tracer_provider)

    assert entry_points.selected_groups == ["openinference_instrumentor"]
    assert len(RecordingInstrumentor.instances) == 1
    RecordingInstrumentor.instances[0].instrument.assert_called_once_with(
        tracer_provider=tracer_provider
    )


def test_auto_instrument_logs_when_no_openinference_entry_points(
    caplog: Any,
) -> None:
    tracer_provider = Mock()

    with patch(
        "arize.otel.otel.entry_points",
        return_value={"openinference_instrumentor": []},
    ):
        with caplog.at_level(logging.WARNING, logger="arize.otel.otel"):
            _auto_instrument_installed_openinference_libraries(tracer_provider)

    assert "No OpenInference instrumentors found" in caplog.text
