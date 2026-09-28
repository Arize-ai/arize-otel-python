import logging
import os
import subprocess
import sys
from typing import Any, Dict, List, Optional
from unittest.mock import Mock, patch

import pytest
from opentelemetry.context import Context
from opentelemetry.sdk.trace import ReadableSpan, SpanProcessor
from opentelemetry.sdk.trace.export import SpanExporter
from opentelemetry.trace import Span

from arize.otel.otel import (
    ARIZE_PROJECT_TYPE_ATTR,
    PYTHON_VERSION,
    SDK_LANGUAGE,
    SDK_PACKAGE_NAME,
    GRPCSpanExporter,
    HTTPSpanExporter,
    SimpleSpanProcessor,
    Transport,
    _auto_instrument_installed_openinference_libraries,
    register,
)
from arize.otel.version import __version__


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


def _register_test_tracer_provider(**kwargs: Any) -> Any:
    defaults = {
        "space_id": "test-space",
        "api_key": "test-api-key",
        "project_name": "test-project",
        "verbose": False,
        "set_global_tracer_provider": False,
    }
    defaults.update(kwargs)
    return register(**defaults)


def test_register_sets_explicit_project_type_on_resource() -> None:
    tracer_provider = _register_test_tracer_provider(project_type="harness")

    assert (
        tracer_provider.resource.attributes[ARIZE_PROJECT_TYPE_ATTR] == "harness"
    )


def test_register_reads_project_type_from_env() -> None:
    env = os.environ.copy()
    env["ARIZE_PROJECT_TYPE"] = "experiment"
    script = """
from arize.otel.otel import ARIZE_PROJECT_TYPE_ATTR, register

tracer_provider = register(
    space_id="test-space",
    api_key="test-api-key",
    project_name="test-project",
    verbose=False,
    set_global_tracer_provider=False,
)
print(tracer_provider.resource.attributes[ARIZE_PROJECT_TYPE_ATTR])
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        check=True,
        env=env,
    )

    assert result.stdout.strip() == "experiment"


def test_register_explicit_project_type_overrides_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ARIZE_PROJECT_TYPE", "experiment")

    tracer_provider = _register_test_tracer_provider(project_type="harness")

    assert (
        tracer_provider.resource.attributes[ARIZE_PROJECT_TYPE_ATTR] == "harness"
    )


def test_register_defaults_project_type_to_application(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ARIZE_PROJECT_TYPE", raising=False)

    tracer_provider = _register_test_tracer_provider()

    assert (
        tracer_provider.resource.attributes[ARIZE_PROJECT_TYPE_ATTR]
        == "application"
    )


def test_register_rejects_invalid_project_type(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ARIZE_PROJECT_TYPE", raising=False)

    with pytest.raises(ValueError, match="application, experiment, harness"):
        _register_test_tracer_provider(project_type="not-a-type")


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


def test_register_then_add_span_processor_keeps_arize_exporter() -> None:
    tracer_provider = register(
        space_id="test-space",
        api_key="test-api-key",
        project_name="test-project",
        batch=False,
        verbose=False,
        set_global_tracer_provider=False,
    )

    assert tracer_provider._default_processor is False

    custom_processor = NoopSpanProcessor()
    tracer_provider.add_span_processor(custom_processor)

    processors = _get_processors(tracer_provider)
    assert len(processors) == 2
    assert isinstance(_get_exporter_from_processor(processors[0]), GRPCSpanExporter)
    assert processors[1] is custom_processor


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


def _assert_sdk_metadata_headers(headers: Dict[str, str]) -> None:
    assert headers["sdk-language"] == SDK_LANGUAGE
    assert headers["sdk-package-name"] == SDK_PACKAGE_NAME
    assert headers["sdk-version"] == __version__
    assert headers["language-version"] == PYTHON_VERSION


def test_grpc_exporter_includes_sdk_metadata_headers() -> None:
    exporter = GRPCSpanExporter(space_id="test-space", api_key="test-api-key")
    headers = _headers_as_dict(exporter._headers)
    _assert_sdk_metadata_headers(headers)
    # SDK metadata is emitted with package identity for the exporter itself.
    assert headers["sdk-package-name"] == "arize-otel"


def test_http_exporter_includes_sdk_metadata_headers() -> None:
    exporter = HTTPSpanExporter(
        space_id="test-space",
        api_key="test-api-key",
        endpoint="https://otlp.arize.com/v1",
    )
    headers = _headers_as_dict(exporter._headers)
    _assert_sdk_metadata_headers(headers)
    assert headers["sdk-package-name"] == "arize-otel"


def test_sdk_metadata_headers_coexist_with_custom_and_auth_headers() -> None:
    tracer_provider = register(
        space_id="test-space",
        api_key="test-api-key",
        project_name="test-project",
        transport=Transport.GRPC,
        batch=False,
        headers={"X-Custom": "custom-value"},
        verbose=False,
        set_global_tracer_provider=False,
    )

    processors = _get_processors(tracer_provider)
    exporter = _get_exporter_from_processor(processors[-1])
    assert exporter is not None

    headers = _headers_as_dict(exporter._headers)
    # Auth, custom, and SDK metadata headers all survive the merge.
    assert headers["authorization"] == "test-api-key"
    assert headers["arize-space-id"] == "test-space"
    assert headers["x-custom"] == "custom-value"
    _assert_sdk_metadata_headers(headers)


def test_user_supplied_sdk_metadata_header_overrides_default() -> None:
    # A caller who explicitly sets an SDK metadata key must win over the
    # built-in default — the merge is additive, never clobbering.
    exporter = GRPCSpanExporter(
        space_id="test-space",
        api_key="test-api-key",
        headers={"sdk-package-name": "custom-sdk"},
    )
    headers = _headers_as_dict(exporter._headers)
    assert headers["sdk-package-name"] == "custom-sdk"
    # Non-overridden metadata keys still fall back to the built-in defaults.
    assert headers["sdk-language"] == SDK_LANGUAGE


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
