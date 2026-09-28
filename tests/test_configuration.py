import inspect
import os
import subprocess
import sys

import pytest
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace.export import ConsoleSpanExporter
from test_otel import _get_exporter_from_processor, _get_processors, _headers_as_dict

from arize.otel import otel
from arize.otel.blob import ArizeBlobUploader

ENTRY_POINTS = [
    otel.register,
    otel.TracerProvider,
    otel.SimpleSpanProcessor,
    otel.BatchSpanProcessor,
    otel.register_with_routing,
    otel.HTTPSpanExporter,
    otel.GRPCSpanExporter,
]


@pytest.fixture
def configured_env(monkeypatch):
    values = {
        "ARIZE_API_KEY": "synthetic-config-key",
        "ARIZE_SPACE_ID": "config-space",
        "ARIZE_PROJECT_NAME": "config-project",
        "ARIZE_PROJECT_TYPE": "harness",
        "ARIZE_COLLECTOR_ENDPOINT": "https://collector.example/v1",
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    return values


def _construct(entry_point, **kwargs):
    if entry_point in (otel.register, otel.register_with_routing):
        kwargs.update(set_global_tracer_provider=False, verbose=False, batch=False)
    elif entry_point is otel.TracerProvider:
        kwargs["verbose"] = False
    return entry_point(**kwargs)


def _exporter(instance):
    if isinstance(instance, (otel.HTTPSpanExporter, otel.GRPCSpanExporter)):
        return instance
    if hasattr(instance, "resource"):
        processor = _get_processors(instance)[0]
        if isinstance(processor, otel.ArizeRoutingSpanProcessor):
            processor = processor._get_or_create_processor("config-space")
    else:
        processor = instance
    return _get_exporter_from_processor(processor)


@pytest.mark.parametrize("name", [entry.__name__ for entry in ENTRY_POINTS])
def test_signatures_and_help_do_not_capture_environment_secrets(name):
    env = os.environ.copy()
    env["ARIZE_API_KEY"] = "synthetic-preimport-secret-87334"
    script = """
import inspect
import pydoc
import sys
from arize.otel import otel
entry = getattr(otel, sys.argv[1])
secret = 'synthetic-preimport-secret-87334'
assert secret not in str(inspect.signature(entry)), 'secret leaked in signature'
assert secret not in pydoc.render_doc(entry), 'secret leaked in help'
if inspect.isclass(entry):
    assert secret not in str(inspect.signature(entry.__init__))
assert inspect.signature(entry).parameters['api_key'].default is None
"""
    result = subprocess.run(
        [sys.executable, "-c", script, name],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("entry_point", ENTRY_POINTS)
@pytest.mark.parametrize("pass_none", [False, True])
def test_configuration_rotates_after_import(
    entry_point, pass_none, configured_env, monkeypatch
):
    kwargs = {}
    if pass_none:
        kwargs = {
            name: None
            for name in (
                "api_key",
                "space_id",
                "project_name",
                "project_type",
                "endpoint",
            )
            if name in inspect.signature(entry_point).parameters
        }
    for suffix, project_type in (("first", "harness"), ("second", "experiment")):
        monkeypatch.setenv("ARIZE_API_KEY", "synthetic-" + suffix)
        monkeypatch.setenv("ARIZE_SPACE_ID", "space-" + suffix)
        monkeypatch.setenv("ARIZE_PROJECT_NAME", "project-" + suffix)
        monkeypatch.setenv("ARIZE_PROJECT_TYPE", project_type)
        monkeypatch.setenv(
            "ARIZE_COLLECTOR_ENDPOINT", "https://" + suffix + ".example/v1"
        )
        instance = _construct(entry_point, **kwargs)
        try:
            exporter = _exporter(instance)
            headers = _headers_as_dict(exporter._headers)
            assert headers["authorization"] == "synthetic-" + suffix
            expected_space = (
                "config-space"
                if entry_point is otel.register_with_routing
                else "space-" + suffix
            )
            assert headers["arize-space-id"] == expected_space
            assert suffix + ".example" in exporter._endpoint
            if entry_point is otel.register:
                assert (
                    instance.resource.attributes[otel.PROJECT_NAME]
                    == "project-" + suffix
                )
                assert (
                    instance.resource.attributes[otel.ARIZE_PROJECT_TYPE_ATTR]
                    == project_type
                )
        finally:
            instance.shutdown()


@pytest.mark.parametrize("entry_point", ENTRY_POINTS)
def test_explicit_configuration_overrides_environment(entry_point, configured_env):
    values = {
        "api_key": "synthetic-explicit-key",
        "space_id": "explicit-space",
        "project_name": "explicit-project",
        "project_type": "experiment",
        "endpoint": "https://explicit.example/v1",
    }
    kwargs = {
        name: value
        for name, value in values.items()
        if name in inspect.signature(entry_point).parameters
    }
    instance = _construct(entry_point, **kwargs)
    try:
        exporter = _exporter(instance)
        assert (
            _headers_as_dict(exporter._headers)["authorization"]
            == "synthetic-explicit-key"
        )
        assert "explicit.example" in exporter._endpoint
        if entry_point is otel.register:
            assert instance.resource.attributes[otel.PROJECT_NAME] == "explicit-project"
            assert (
                instance.resource.attributes[otel.ARIZE_PROJECT_TYPE_ATTR]
                == "experiment"
            )
    finally:
        instance.shutdown()


@pytest.mark.parametrize(
    "entry_point,field",
    [
        (entry, field)
        for entry in ENTRY_POINTS
        for field in ("api_key", "space_id", "project_name", "project_type", "endpoint")
        if field in inspect.signature(entry).parameters
    ],
)
def test_explicit_empty_values_are_not_replaced(entry_point, field, configured_env):
    with pytest.raises(ValueError):
        _construct(entry_point, **{field: ""})


@pytest.mark.parametrize("endpoint", [None, ""])
def test_empty_environment_endpoint_uses_default(endpoint, configured_env, monkeypatch):
    if endpoint is None:
        monkeypatch.delenv("ARIZE_COLLECTOR_ENDPOINT")
    else:
        monkeypatch.setenv("ARIZE_COLLECTOR_ENDPOINT", endpoint)
    exporter = otel.HTTPSpanExporter()
    try:
        assert exporter._endpoint == otel.Endpoint.ARIZE.value
    finally:
        exporter.shutdown()


@pytest.mark.parametrize(
    "processor_class", [otel.SimpleSpanProcessor, otel.BatchSpanProcessor]
)
def test_custom_exporter_bypasses_arize_configuration(processor_class, monkeypatch):
    for name in ("ARIZE_API_KEY", "ARIZE_SPACE_ID", "ARIZE_COLLECTOR_ENDPOINT"):
        monkeypatch.delenv(name, raising=False)
    exporter = ConsoleSpanExporter()
    processor = processor_class(
        span_exporter=exporter,
        api_key="",
        space_id="",
        endpoint="",
        transport="invalid",
    )
    try:
        assert _get_exporter_from_processor(processor) is exporter
    finally:
        processor.shutdown()


def test_routing_keeps_configuration_when_processor_creation_is_delayed(
    configured_env, monkeypatch
):
    provider = _construct(otel.register_with_routing)
    try:
        monkeypatch.setenv("ARIZE_API_KEY", "synthetic-rotated-key")
        monkeypatch.setenv("ARIZE_COLLECTOR_ENDPOINT", "https://rotated.example/v1")
        exporter = _exporter(provider)
        assert (
            _headers_as_dict(exporter._headers)["authorization"]
            == "synthetic-config-key"
        )
        assert "collector.example" in exporter._endpoint
    finally:
        provider.shutdown()


def test_positional_exporter_endpoint_takes_precedence(configured_env):
    http = otel.HTTPSpanExporter("https://positional.example/v1")
    grpc = otel.GRPCSpanExporter(None, None, None, "https://positional.example/v1")
    try:
        assert http._endpoint == "https://positional.example/v1"
        assert grpc._endpoint == "positional.example"
    finally:
        http.shutdown()
        grpc.shutdown()


def test_explicit_resource_takes_precedence(configured_env):
    resource = Resource.create({otel.PROJECT_NAME: "resource-project"})
    provider = otel.TracerProvider(resource=resource, verbose=False)
    try:
        assert provider.resource.attributes[otel.PROJECT_NAME] == "resource-project"
    finally:
        provider.shutdown()


def test_blob_configuration_rotates_after_import(configured_env, monkeypatch):
    for suffix in ("first", "second"):
        monkeypatch.setenv("ARIZE_API_KEY", "synthetic-" + suffix)
        monkeypatch.setenv("ARIZE_SPACE_ID", "space-" + suffix)
        monkeypatch.setenv("ARIZE_PROJECT_NAME", "project-" + suffix)
        monkeypatch.setenv("ARIZE_BLOB_ENDPOINT", "https://blob-" + suffix + ".example")
        uploader = ArizeBlobUploader()
        try:
            assert uploader._client._api_key == "synthetic-" + suffix
            assert uploader._destination.space_id == "space-" + suffix
            assert uploader._destination.project_name == "project-" + suffix
            assert "blob-" + suffix + ".example" in uploader._client._base_endpoint
        finally:
            uploader.shutdown()
