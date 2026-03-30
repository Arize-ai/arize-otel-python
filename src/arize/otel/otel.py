import inspect
import logging
import os
import sys
import threading
from contextlib import contextmanager
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple, Type, Union
import typing
from urllib.parse import urlparse

from openinference.instrumentation import TracerProvider as _TracerProvider
from openinference.semconv.resource import ResourceAttributes as _ResourceAttributes
from opentelemetry import trace as trace_api
from opentelemetry import context as context_api
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
    OTLPSpanExporter as _GRPCSpanExporter,
)
from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
    OTLPSpanExporter as _HTTPSpanExporter,
)
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import SpanProcessor
from opentelemetry.sdk.trace.export import BatchSpanProcessor as _BatchSpanProcessor
from opentelemetry.sdk.trace.export import ConsoleSpanExporter, SpanExporter
from opentelemetry.sdk.trace.export import SimpleSpanProcessor as _SimpleSpanProcessor
from opentelemetry.sdk.trace import ReadableSpan

from .settings import (
    ENV_ARIZE_API_KEY,
    ENV_ARIZE_PROJECT_NAME,
    ENV_ARIZE_SPACE_ID,
    get_env_arize_api_key,
    get_env_arize_space_id,
    get_env_collector_endpoint,
    get_env_project_name,
)

PROJECT_NAME = _ResourceAttributes.PROJECT_NAME

logger = logging.getLogger(__name__)

# Arize routing attributes
ARIZE_SPACE_ID_ATTR = "arize.space_id"
ARIZE_PROJECT_NAME_ATTR = "arize.project.name"

# Context keys for routing
_ARIZE_SPACE_ID_CONTEXT_KEY = context_api.create_key("arize.space_id")
_ARIZE_PROJECT_NAME_CONTEXT_KEY = context_api.create_key("arize.project.name")


class Endpoint(str, Enum):
    ARIZE = "https://otlp.arize.com/v1"
    ARIZE_EUROPE = "https://otlp.eu-west-1a.arize.com/v1"


class Transport(str, Enum):
    GRPC = "grpc"
    HTTPS = "https"
    HTTP = "http"


EndpointType = Union[str, Endpoint]


@contextmanager
def set_routing_context(space_id: str, project_name: str):
    """
    Context manager to set routing context that propagates to all child spans.

    When using `register_with_routing()`, this context manager allows you to set the
    space_id and project_name at a high level (e.g., per request or per operation), and
    all spans created within this context will inherit these values unless explicitly
    overridden by span attributes.

    IMPORTANT: both space_id and project_name must be provided for routing to work; otherwise,
    the routing will not be applied.

    The context sets the following span attributes:
    - `arize.space_id`: Routes spans to the specified Arize space
    - `arize.project.name`: Sets the project name within that space

    Args:
        space_id (str, default ""): The Arize space ID to route spans to.
        project_name (str, default ""): The project name to associate with spans.

    Example:
        ```python
        from arize.otel import register_with_routing, set_routing_context

        tracer_provider = register_with_routing(api_key="your-api-key")
        tracer = tracer_provider.get_tracer(__name__)

        # Set context for a request/operation
        with set_routing_context(space_id="space-123", project_name="my-project"):
            with tracer.start_as_current_span("parent_operation"):
                # This span and all children will use space-123 and my-project
                # Attributes set: arize.space_id="space-123", arize.project.name="my-project"
                with tracer.start_as_current_span("child_operation"):
                    # Child inherits the context automatically
                    pass
        ```
    """
    ctx = context_api.get_current()

    if space_id:
        ctx = context_api.set_value(_ARIZE_SPACE_ID_CONTEXT_KEY, space_id, ctx)

    if project_name:
        ctx = context_api.set_value(_ARIZE_PROJECT_NAME_CONTEXT_KEY, project_name, ctx)

    if not space_id or not project_name:
        logger.warning(
            "Both space_id and project_name must be provided for routing to work"
        )

    token = context_api.attach(ctx)
    try:
        yield
    finally:
        context_api.detach(token)


def register(
    *,
    space_id: str = get_env_arize_space_id(),
    api_key: str = get_env_arize_api_key(),
    project_name: str = get_env_project_name(),
    endpoint: EndpointType = get_env_collector_endpoint() or Endpoint.ARIZE,
    transport: Transport = Transport.GRPC,
    batch: bool = True,
    set_global_tracer_provider: bool = True,
    headers: Optional[Dict[str, str]] = None,
    verbose: bool = True,
    log_to_console: bool = False,
) -> _TracerProvider:
    """
    Creates an OpenTelemetry TracerProvider for enabling OpenInference tracing.

    For further configuration, the `arize.otel` module provides drop-in replacements for
    OpenTelemetry TracerProvider, SimpleSpanProcessor, BatchSpanProcessor, HTTPSpanExporter, and
    GRPCSpanExporter objects with Arize-aware defaults. Documentation on how to configure tracing
    can be found at https://opentelemetry.io/docs/specs/otel/trace/sdk/.

    Args:
        space_id (str): The unique identifier for the Arize space. If not provided,
            the `ARIZE_SPACE_ID` environment variable will be used.
        api_key (str): The API key for authenticating with Arize. If not provided,
            the `ARIZE_API_KEY` environment variable will be used.
        project_name (str): The name of the project to which spans will be associated. If
            not provided, the `ARIZE_PROJECT_NAME` environment variable will be used or the
            default project_name will be "default".
        endpoint (EndpointType): The collector endpoint to which spans will be exported.
            If not provided, the `ARIZE_COLLECTOR_ENDPOINT` environment variable or the default
            `Endpoint.ARIZE` will be used.
        transport (Transport): The transport mechanism to use for exporting spans.
            Options are `Transport.GRPC`, `Transport.HTTP`, or `Transport.HTTPS`.
            Defaults to `Transport.GRPC`.
        batch (bool): If True, spans will be processed using a BatchSpanProcessor. If False, spans
            will be processed one at a time using a SimpleSpanProcessor. Defaults to False.
        set_global_tracer_provider (bool): If True, sets the TracerProvider as the global tracer
            provider. Defaults to True.
        headers (dict): Optional headers to include in requests to the collector.
            Defaults to None.
        verbose (bool): If True, prints configuration details to stdout. Defaults to True.
        log_to_console (bool): If True, spans will be logged to the console, useful for debugging.
            Defaults to False.
    """
    _validate_inputs(space_id, api_key, project_name, endpoint, transport)

    resource = Resource.create({PROJECT_NAME: project_name})
    tracer_provider = TracerProvider(
        space_id=space_id,
        api_key=api_key,
        project_name=project_name,
        endpoint=endpoint,
        transport=transport,
        resource=resource,
        # verbose=False is important so we don't print details of the default
        # processors, will be deleted below
        verbose=False,
    )
    span_processor: SpanProcessor
    if batch:
        span_processor = BatchSpanProcessor(
            space_id=space_id,
            api_key=api_key,
            endpoint=endpoint,
            transport=transport,
            headers=headers,
        )
    else:
        span_processor = SimpleSpanProcessor(
            space_id=space_id,
            api_key=api_key,
            endpoint=endpoint,
            transport=transport,
            headers=headers,
        )
    tracer_provider.add_span_processor(span_processor)
    if log_to_console:
        tracer_provider.add_span_processor(
            span_processor=_SimpleSpanProcessor(
                span_exporter=ConsoleSpanExporter(),
            )
        )
    tracer_provider._default_processor = True

    if set_global_tracer_provider:
        trace_api.set_tracer_provider(tracer_provider)
        global_provider_msg = (
            "|  \n"
            "|  `register` has set this TracerProvider as the global OpenTelemetry default.\n"
            "|  To disable this behavior, call `register` with "
            "`set_global_tracer_provider=False`.\n"
        )
    else:
        global_provider_msg = ""

    details = tracer_provider._tracing_details()
    if verbose:
        print(f"{details}{global_provider_msg}")
    return tracer_provider


class TracerProvider(_TracerProvider):
    """
    An extension of `opentelemetry.sdk.trace.TracerProvider` with Arize-aware defaults.

    Extended keyword arguments are documented in the `Args` section. For further documentation, see
    the OpenTelemetry documentation at https://opentelemetry.io/docs/specs/otel/trace/sdk/.

    Args:
        space_id (str): The unique identifier for the Arize space. If not provided,
            the `ARIZE_SPACE_ID` environment variable will be used.
        api_key (str): The API key for authenticating with Arize. If not provided,
            the `ARIZE_API_KEY` environment variable will be used.
        project_name (str): The name of the project to which spans will be associated. If
            not provided, the `ARIZE_PROJECT_NAME` environment variable will be used or the
            default project_name will be "default".
        endpoint (EndpointType): The collector endpoint to which spans will be exported.
            If not provided, the `ARIZE_COLLECTOR_ENDPOINT` environment variable or the default
            `Endpoint.ARIZE` will be used.
        transport (Transport): The transport mechanism to use for exporting spans.
            Options are `Transport.GRPC`, `Transport.HTTP`, or `Transport.HTTPS`.
            Defaults to `Transport.GRPC`.
        verbose (bool): If True, configuration details will be printed to stdout.
    """

    def __init__(
        self,
        *args: Any,
        space_id: str = get_env_arize_space_id(),
        api_key: str = get_env_arize_api_key(),
        project_name: str = get_env_project_name(),
        endpoint: EndpointType = get_env_collector_endpoint() or Endpoint.ARIZE,
        transport: Transport = Transport.GRPC,
        verbose: bool = True,
        **kwargs: Any,
    ):
        _validate_inputs(space_id, api_key, project_name, endpoint, transport)

        sig = _get_class_signature(_TracerProvider)
        bound_args = sig.bind_partial(*args, **kwargs)
        bound_args.apply_defaults()
        if bound_args.arguments.get("resource") is None:
            bound_args.arguments["resource"] = Resource.create(
                {PROJECT_NAME: project_name}
            )
        super().__init__(*bound_args.args, **bound_args.kwargs)

        self._default_processor = False
        if transport == Transport.HTTP:
            exporter: SpanExporter = HTTPSpanExporter(
                space_id=space_id,
                api_key=api_key,
                endpoint=endpoint,
            )
        elif transport == Transport.GRPC:
            exporter: SpanExporter = GRPCSpanExporter(
                space_id=space_id,
                api_key=api_key,
                endpoint=endpoint,
            )
        else:
            raise ValueError(f"Invalid transport: {transport}")
        self.add_span_processor(SimpleSpanProcessor(span_exporter=exporter))
        self._default_processor = True
        if verbose:
            print(self._tracing_details())

    def add_span_processor(self, *args: Any, **kwargs: Any) -> None:
        """
        Registers a new `SpanProcessor` for this `TracerProvider`.

        If this `TracerProvider` has a default processor, it will be removed.
        """

        if self._default_processor:
            self._active_span_processor.shutdown()
            self._active_span_processor._span_processors = (
                tuple()
            )  # remove default processors
            self._default_processor = False
        return super().add_span_processor(*args, **kwargs)

    def _tracing_details(self) -> str:
        project = self.resource.attributes.get(PROJECT_NAME)
        processor_name: Optional[str] = None
        endpoint: Optional[str] = None
        transport: Optional[str] = None
        headers: Optional[Union[Dict[str, str], str]] = None

        if self._active_span_processor:
            if processors := self._active_span_processor._span_processors:
                if len(processors) == 1:
                    span_processor = self._active_span_processor._span_processors[0]
                    # Handle both old and new attribute locations for OpenTelemetry compatibility
                    # OpenTelemetry v1.34.0+ moved exporter from span_exporter to _batch_processor._exporter
                    # https://github.com/open-telemetry/opentelemetry-python/pull/4580
                    exporter = getattr(
                        getattr(span_processor, "_batch_processor", None),
                        "_exporter",
                        None,
                    ) or getattr(span_processor, "span_exporter", None)
                    if exporter:
                        processor_name = span_processor.__class__.__name__
                        endpoint = exporter._endpoint
                        transport = _exporter_transport(exporter)
                        headers = _printable_headers(exporter._headers)
                else:
                    processor_name = "Multiple Span Processors"
                    endpoint = "Multiple Span Exporters"
                    transport = "Multiple Span Exporters"
                    headers = "Multiple Span Exporters"

        if os.name == "nt":
            details_header = "OpenTelemetry Tracing Details"
        else:
            details_header = "🔭 OpenTelemetry Tracing Details 🔭"

        configuration_msg = "|  Using a default SpanProcessor. `add_span_processor` will overwrite this default.\n"

        details_msg = (
            f"{details_header}\n"
            f"|  Arize Project: {project}\n"
            f"|  Span Processor: {processor_name}\n"
            f"|  Collector Endpoint: {endpoint}\n"
            f"|  Transport: {transport}\n"
            f"|  Transport Headers: {headers}\n"
            "|  \n"
            f"{configuration_msg if self._default_processor else ''}"
        )
        return details_msg


class SimpleSpanProcessor(_SimpleSpanProcessor):
    """
    Simple SpanProcessor implementation.

    SimpleSpanProcessor is an implementation of `SpanProcessor` that passes ended spans directly to
    the configured `SpanExporter`.

    Args:
        span_exporter (SpanExporter, optional): The `SpanExporter` to which ended spans will be
            passed.
        space_id (str, optional): Only used if span_exporter is None.
            The unique identifier for the Arize space. If not provided, the `ARIZE_SPACE_ID`
            environment variable will be used.
        api_key (str, optional): Only used if span_exporter is None.
            The API key for authenticating with Arize. If not provided, the `ARIZE_API_KEY`
            environment variable will be used.
        endpoint (EndpointType, optional): Only used if span_exporter is None.
            The collector endpoint to which spans will be exported. If not provided, the
            `ARIZE_COLLECTOR_ENDPOINT` environment variable or the default
            `Endpoint.ARIZE` will be used.
        transport (Transport, optional): Only used if span_exporter is None.
            The transport mechanism to use for exporting spans. Options are `Transport.GRPC`,
            `Transport.HTTP`, or `Transport.HTTPS`. Defaults to `Transport.GRPC`.
        headers (dict, optional): Optional headers to include in the request to the collector.
            Defaults to None.
    """

    def __init__(
        self,
        span_exporter: Optional[SpanExporter] = None,
        space_id: str = get_env_arize_space_id(),
        api_key: str = get_env_arize_api_key(),
        endpoint: EndpointType = get_env_collector_endpoint() or Endpoint.ARIZE,
        transport: Transport = Transport.GRPC,
        headers: Optional[Dict[str, str]] = None,
        **kwargs: Any,
    ):
        if span_exporter is None:
            if transport == Transport.HTTP:
                span_exporter = HTTPSpanExporter(
                    space_id=space_id,
                    api_key=api_key,
                    endpoint=endpoint,
                    headers=headers,
                )
            elif transport == Transport.GRPC:
                span_exporter = GRPCSpanExporter(
                    space_id=space_id,
                    api_key=api_key,
                    endpoint=endpoint,
                    headers=headers,
                )
            else:
                raise ValueError(f"Invalid transport: {transport}")
        super().__init__(span_exporter, **kwargs)


class BatchSpanProcessor(_BatchSpanProcessor):
    """
    Batch SpanProcessor implementation.

    `BatchSpanProcessor` is an implementation of `SpanProcessor` that batches ended spans and
    pushes them to the configured `SpanExporter`.

    `BatchSpanProcessor` is configurable with the following environment variables which correspond
    to constructor parameters:

    - :envvar:`OTEL_BSP_SCHEDULE_DELAY`
    - :envvar:`OTEL_BSP_MAX_QUEUE_SIZE`
    - :envvar:`OTEL_BSP_MAX_EXPORT_BATCH_SIZE`
    - :envvar:`OTEL_BSP_EXPORT_TIMEOUT`

    Args:
        span_exporter (SpanExporter, optional): The `SpanExporter` to which ended spans will be
            passed.
        space_id (str, optional): Only used if span_exporter is None.
            The unique identifier for the Arize space. If not provided, the `ARIZE_SPACE_ID`
            environment variable will be used.
        api_key (str, optional): Only used if span_exporter is None.
            The API key for authenticating with Arize. If not provided, the `ARIZE_API_KEY`
            environment variable will be used.
        endpoint (EndpointType, optional): Only used if span_exporter is None.
            The collector endpoint to which spans will be exported. If not provided, the
            `ARIZE_COLLECTOR_ENDPOINT` environment variable or the default
            `Endpoint.ARIZE` will be used.
        transport (Transport, optional): Only used if span_exporter is None.
            The transport mechanism to use for exporting spans. Options are `Transport.GRPC`,
            `Transport.HTTP`, or `Transport.HTTPS`. Defaults to `Transport.GRPC`.
        headers (dict, optional): Optional headers to include in the request to the collector.
            Defaults to None.
        max_queue_size (int, optional): The maximum queue size.
        schedule_delay_millis (float, optional): The delay between two consecutive exports in
            milliseconds.
        max_export_batch_size (int, optional): The maximum batch size.
        export_timeout_millis (float, optional): The batch timeout in milliseconds.
    """

    def __init__(
        self,
        span_exporter: Optional[SpanExporter] = None,
        space_id: str = get_env_arize_space_id(),
        api_key: str = get_env_arize_api_key(),
        endpoint: EndpointType = get_env_collector_endpoint() or Endpoint.ARIZE,
        transport: Transport = Transport.GRPC,
        headers: Optional[Dict[str, str]] = None,
        **kwargs: Any,
    ):
        if span_exporter is None:
            if transport == Transport.HTTP:
                span_exporter = HTTPSpanExporter(
                    space_id=space_id,
                    api_key=api_key,
                    endpoint=endpoint,
                    headers=headers,
                )
            elif transport == Transport.GRPC:
                span_exporter = GRPCSpanExporter(
                    space_id=space_id,
                    api_key=api_key,
                    endpoint=endpoint,
                    headers=headers,
                )
            else:
                raise ValueError(f"Invalid transport: {transport}")
        super().__init__(span_exporter, **kwargs)


class ArizeRoutingSpanProcessor(SpanProcessor):
    """
    Routing Processor implementation which delegates to a set of `SpanProcessor`s based on the span's attributes.

    `RoutingSpanProcessor` is an implementation of `SpanProcessor` that dynamically creates and delegates
    to `SpanProcessor`s based on the span's `arize.space_id` attribute. Project names are set via the
    span's `arize.project.name` attribute or default to "default".

    Args:
        api_key (str): The API key for authenticating with Arize.
        endpoint (EndpointType): The collector endpoint to which spans will be exported.
        transport (Transport): The transport mechanism to use for exporting spans.
        batch (bool): If True, spans will be processed using BatchSpanProcessor. If False, uses SimpleSpanProcessor.
        headers (dict, optional): Optional headers to include in the request to the collector.
    """

    def __init__(
        self,
        api_key: str,
        endpoint: EndpointType,
        transport: Transport,
        batch: bool = True,
        headers: Optional[Dict[str, str]] = None,
    ):
        self._api_key = api_key
        self._endpoint = endpoint
        self._transport = transport
        self._batch = batch
        self._headers = headers
        self._processors: Dict[str, SpanProcessor] = {}
        self._lock = threading.Lock()

    def on_start(self, span, parent_context=None):
        """
        Called when a span is started. Sets routing attributes from context if not already set.

        This allows context set by `set_routing_context()` to automatically propagate Arize
        routing attributes (space_id and project_name) to all child spans.
        """
        if ARIZE_SPACE_ID_ATTR not in span.attributes:
            ctx = (
                parent_context
                if parent_context is not None
                else context_api.get_current()
            )
            context_space_id = context_api.get_value(
                _ARIZE_SPACE_ID_CONTEXT_KEY, context=ctx
            )
            if context_space_id is not None:
                span.set_attribute(ARIZE_SPACE_ID_ATTR, context_space_id)

        if ARIZE_PROJECT_NAME_ATTR not in span.attributes:
            ctx = (
                parent_context
                if parent_context is not None
                else context_api.get_current()
            )
            context_project_name = context_api.get_value(
                _ARIZE_PROJECT_NAME_CONTEXT_KEY, context=ctx
            )
            if context_project_name is not None:
                span.set_attribute(ARIZE_PROJECT_NAME_ATTR, context_project_name)

        space_id = span.attributes.get(ARIZE_SPACE_ID_ATTR)
        if space_id is None:
            return

        processor = self._get_or_create_processor(space_id)
        processor.on_start(span)

    def on_end(self, span: ReadableSpan):
        """
        Called when a span ends. Routes the span to the appropriate processor based on space_id.
        """
        # Get space_id from span attributes (which should have been set by on_start from context)
        space_id = span.attributes.get(ARIZE_SPACE_ID_ATTR)
        if space_id is None:
            logger.warning(
                "No 'arize.space_id' attribute found in span attributes! Skipping span."
            )
            return

        # Project name should be set as a span attribute, via the on_start method from context
        # If not set, do not continue since we cannot send spans to Arizewithout a project name
        if ARIZE_PROJECT_NAME_ATTR not in span.attributes:
            logger.warning(
                f"No project name attribute (arize.project.name) found for span '{span.name}'. Project name is required for Arize span routing. Skipping span."
            )
            return

        processor = self._get_or_create_processor(space_id)
        processor.on_end(span)

    def shutdown(self):
        with self._lock:
            return all(
                processor.shutdown()
                for processor in self._processors.values()
                if processor
            )

    def force_flush(self, timeout_millis: typing.Optional[int] = None) -> bool:
        with self._lock:
            return all(
                processor.force_flush(timeout_millis)
                for processor in self._processors.values()
                if processor
            )

    def _get_or_create_processor(self, space_id: str) -> SpanProcessor:
        """Get existing processor for space_id or create a new one."""
        # First check to see if we have already created a span processor for this space_id
        # If we have, return the existing processor
        if space_id in self._processors:
            return self._processors[space_id]

        # If we haven't, acquire lock to create new span processor for the newly seen space_id
        with self._lock:
            # Double-check in case another thread created it
            if space_id in self._processors:
                return self._processors[space_id]

            # Create new processor for the  space_id which we haven't seen before
            if self._batch:
                processor = BatchSpanProcessor(
                    space_id=space_id,
                    api_key=self._api_key,
                    endpoint=self._endpoint,
                    transport=self._transport,
                    headers=self._headers,
                )
            else:
                processor = SimpleSpanProcessor(
                    space_id=space_id,
                    api_key=self._api_key,
                    endpoint=self._endpoint,
                    transport=self._transport,
                    headers=self._headers,
                )

            self._processors[space_id] = processor

            logger.info(f"Created new span processor for Arize space_id: {space_id}")
            return processor


def register_with_routing(
    *,
    api_key: str = get_env_arize_api_key(),
    endpoint: EndpointType = get_env_collector_endpoint() or Endpoint.ARIZE,
    transport: Transport = Transport.GRPC,
    batch: bool = True,
    set_global_tracer_provider: bool = True,
    headers: Optional[Dict[str, str]] = None,
    verbose: bool = True,
    log_to_console: bool = False,
) -> _TracerProvider:
    """
    Creates an OpenTelemetry TracerProvider for enabling OpenInference tracing with dynamic routing support.

    This function creates a TracerProvider that dynamically routes spans to different Arize spaces based
    on the `arize.space_id` span attribute. Span processors are created on-demand for each space_id
    encountered. Project names are set via the `arize.project.name` span attribute.

    Important: Use `set_routing_context()` to set context that propagates the required routing attributes to all child spans.

    Performance Note: A dedicated span processor is created for each unique space_id and cached in memory
    for the lifetime of the application. If routing to many different spaces (hundreds or thousands),
    memory usage will grow accordingly.

    Args:
        api_key (str): The API key for authenticating with Arize. This single API key will be used
            for all spaces. If not provided, the `ARIZE_API_KEY` environment variable will be used.
        endpoint (EndpointType): The collector endpoint to which spans will be exported.
            If not provided, the `ARIZE_COLLECTOR_ENDPOINT` environment variable or the default
            `Endpoint.ARIZE` will be used.
        transport (Transport): The transport mechanism to use for exporting spans.
            Options are `Transport.GRPC`, `Transport.HTTP`, or `Transport.HTTPS`.
            Defaults to `Transport.GRPC`.
        batch (bool): If True, spans will be processed using a BatchSpanProcessor. If False, spans
            will be processed one at a time using a SimpleSpanProcessor. Defaults to True.
        set_global_tracer_provider (bool): If True, sets the TracerProvider as the global tracer
            provider. Defaults to True.
        headers (dict): Optional headers to include in requests to the collector.
            Defaults to None.
        verbose (bool): If True, prints configuration details to stdout. Defaults to True.
        log_to_console (bool): If True, spans will be logged to the console, useful for debugging.
            Defaults to False.
    """
    _validate_routing_inputs(
        api_key=api_key,
        endpoint=endpoint,
        transport=transport,
    )

    resource = Resource.create()
    tracer_provider = _TracerProvider(resource=resource)

    routing_span_processor = ArizeRoutingSpanProcessor(
        api_key=api_key,
        endpoint=endpoint,
        transport=transport,
        batch=batch,
        headers=headers,
    )
    tracer_provider.add_span_processor(routing_span_processor)

    if log_to_console:
        tracer_provider.add_span_processor(
            span_processor=_SimpleSpanProcessor(
                span_exporter=ConsoleSpanExporter(),
            )
        )

    if set_global_tracer_provider:
        trace_api.set_tracer_provider(tracer_provider)
        global_provider_msg = (
            "|  \n"
            "|  `register_with_routing` has set this TracerProvider as the global OpenTelemetry default.\n"
            "|  To disable this behavior, call `register_with_routing` with "
            "`set_global_tracer_provider=False`.\n"
        )
    else:
        global_provider_msg = ""

    if verbose:
        if os.name == "nt":
            details_header = "OpenTelemetry Tracing Details (Dynamic Routing)"
        else:
            details_header = "🔭 OpenTelemetry Tracing Details (Dynamic Routing) 🔭"

        details_msg = (
            f"{details_header}\n"
            f"|  API Key: ****\n"
            f"|  Collector Endpoint: {endpoint}\n"
            f"|  Transport: {transport.value}\n"
            f"|  Batch Processing: {batch}\n"
            f"|  Routing: Dynamic (processors created on-demand per space_id)\n"
            "|  \n"
            "|  Span attributes used for routing:\n"
            "|    - arize.space_id: Routes to different Arize spaces\n"
            "|    - arize.project.name: Sets the project name within each space\n"
            "|  \n"
            "|  Two ways to set routing attributes:\n"
            "|    1. Set span attributes: span.set_attribute('arize.space_id', 'space-123')\n"
            "|    2. Use context: with set_routing_context(space_id='space-123', project_name='my-project')\n"
            "|  \n"
            "|  Context propagates to all child spans automatically!\n"
        )
        print(f"{details_msg}{global_provider_msg}")

    return tracer_provider


class HTTPSpanExporter(_HTTPSpanExporter):
    """
    OTLP span exporter using HTTP.

    For more information, see:
    - `opentelemetry.exporter.otlp.proto.http.trace_exporter.OTLPSpanExporter`

    Args:
        space_id (str, optional): Only used if span_exporter is None.
            The unique identifier for the Arize space. If not provided, the `ARIZE_SPACE_ID`
            environment variable will be used.
        api_key (str, optional): Only used if span_exporter is None.
            The API key for authenticating with Arize. If not provided, the `ARIZE_API_KEY`
            environment variable will be used.
        endpoint (EndpointType, optional): Only used if span_exporter is None.
            The collector endpoint to which spans will be exported. If not provided, the
            `ARIZE_COLLECTOR_ENDPOINT` environment variable or the default
            `Endpoint.ARIZE` will be used.
        headers: Headers to send when exporting. If not provided, the `ARIZE_CLIENT_HEADERS`
            or `OTEL_EXPORTER_OTLP_HEADERS` environment variables will be used.
    """

    def __init__(
        self,
        *args: Any,
        space_id: str = get_env_arize_space_id(),
        api_key: str = get_env_arize_api_key(),
        endpoint: EndpointType = get_env_collector_endpoint() or Endpoint.ARIZE,
        **kwargs: Any,
    ):
        _validate_inputs(
            space_id, api_key, "", endpoint, Transport.HTTP, skip=["project_name"]
        )
        sig = _get_class_signature(_HTTPSpanExporter)
        bound_args = sig.bind_partial(*args, **kwargs)
        bound_args.apply_defaults()

        auth_header = _get_arize_auth_headers(space_id, api_key)
        if not bound_args.arguments.get("headers"):
            headers = {
                **(auth_header or dict()),
            }
            bound_args.arguments["headers"] = headers if headers else None
        else:
            headers = dict()
            for header_field, value in bound_args.arguments["headers"].items():
                headers[header_field.lower()] = value

            # If the auth header is not in the headers, add it
            miss_authorization = (
                "authorization" not in headers and "api_key" not in headers
            )
            miss_space_id = (
                "space_id" not in headers and "arize-space-id" not in headers
            )
            if miss_authorization or miss_space_id:
                bound_args.arguments["headers"] = {
                    **headers,
                    **(auth_header or dict()),
                }
            else:
                bound_args.arguments["headers"] = headers

        if bound_args.arguments.get("endpoint") is None:
            bound_args.arguments["endpoint"] = endpoint
        super().__init__(*bound_args.args, **bound_args.kwargs)


class GRPCSpanExporter(_GRPCSpanExporter):
    """
    OTLP span exporter using gRPC.

    For more information, see:
    - `opentelemetry.exporter.otlp.proto.grpc.trace_exporter.OTLPSpanExporter`

    Args:
        space_id (str, optional): Only used if span_exporter is None.
            The unique identifier for the Arize space. If not provided, the `ARIZE_SPACE_ID`
            environment variable will be used.
        api_key (str, optional): Only used if span_exporter is None.
            The API key for authenticating with Arize. If not provided, the `ARIZE_API_KEY`
            environment variable will be used.
        endpoint (EndpointType, optional): Only used if span_exporter is None.
            The collector endpoint to which spans will be exported. If not provided, the
            `ARIZE_COLLECTOR_ENDPOINT` environment variable or the default
            `Endpoint.ARIZE` will be used.
        insecure: Connection type
        credentials: Credentials object for server authentication
        headers: Headers to send when exporting. If not provided, the `ARIZE_CLIENT_HEADERS`
            or `OTEL_EXPORTER_OTLP_HEADERS` environment variables will be used.
        timeout: Backend request timeout in seconds
        compression: gRPC compression method to use
    """

    def __init__(
        self,
        space_id: str = get_env_arize_space_id(),
        api_key: str = get_env_arize_api_key(),
        endpoint: EndpointType = get_env_collector_endpoint() or Endpoint.ARIZE,
        *args: Any,
        **kwargs: Any,
    ):
        _validate_inputs(
            space_id, api_key, "", endpoint, Transport.GRPC, skip=["project_name"]
        )
        sig = _get_class_signature(_GRPCSpanExporter)
        bound_args = sig.bind_partial(*args, **kwargs)
        bound_args.apply_defaults()

        auth_header = _get_arize_auth_headers(space_id, api_key)
        if not bound_args.arguments.get("headers"):
            headers = {
                **(auth_header or dict()),
            }
            bound_args.arguments["headers"] = headers if headers else None
        else:
            headers = dict()
            for header_field, value in bound_args.arguments["headers"].items():
                headers[header_field.lower()] = value

            # If the auth header is not in the headers, add it
            if "authorization" not in headers:
                bound_args.arguments["headers"] = {
                    **headers,
                    **(auth_header or dict()),
                }
            else:
                bound_args.arguments["headers"] = headers

        if bound_args.arguments.get("endpoint") is None:
            bound_args.arguments["endpoint"] = endpoint
        super().__init__(*bound_args.args, **bound_args.kwargs)


def _exporter_transport(exporter: SpanExporter) -> str:
    if isinstance(exporter, _HTTPSpanExporter):
        return "HTTP"
    if isinstance(exporter, _GRPCSpanExporter):
        return "gRPC"
    else:
        return exporter.__class__.__name__


def _printable_headers(
    headers: Union[List[Tuple[str, str]], Dict[str, str]],
) -> Dict[str, str]:
    if isinstance(headers, dict):
        return {key: "****" for key, _ in headers.items()}
    return {key: "****" for key, _ in headers}


def _get_arize_auth_headers(space_id: str, api_key: str) -> Dict[str, str]:
    return {
        "authorization": api_key,
        "api_key": api_key,  # deprecated, will be removed in future versions
        "arize-space-id": space_id,
        "space_id": space_id,  # deprecated, will be removed in future versions
        "arize-interface": "otel",
    }


def _validate_routing_inputs(
    api_key: str,
    endpoint: EndpointType,
    transport: Transport,
) -> None:
    """Validate inputs for routing configuration."""
    if not api_key:
        raise ValueError(
            "api_key is required. Please pass it as argument or "
            f"set the {ENV_ARIZE_API_KEY} environment variable."
        )
    if not isinstance(api_key, str):
        raise ValueError("api_key must be a string")

    _validate_endpoint(endpoint)
    _validate_transport(transport)


def _validate_inputs(
    space_id: str,
    api_key: str,
    project_name: str,
    endpoint: EndpointType,
    transport: Transport,
    skip: List[str] = list(),
) -> None:
    if not space_id and "space_id" not in skip:
        raise ValueError(
            "space_id is required. Please pass it as argument or "
            f"set the {ENV_ARIZE_SPACE_ID} environment variable."
        )
    if not api_key and "api_key" not in skip:
        raise ValueError(
            "api_key is required. Please pass it as argument or "
            f"set the {ENV_ARIZE_API_KEY} environment variable."
        )
    if not project_name and "project_name" not in skip:
        raise ValueError(
            "project_name is required. Please pass it as argument or "
            f"set the {ENV_ARIZE_PROJECT_NAME} environment variable."
        )
    if "endpoint" not in skip:
        _validate_endpoint(endpoint)
    if "transport" not in skip:
        _validate_transport(transport)


def _validate_endpoint(endpoint: Any) -> None:
    parsed = ""
    if isinstance(endpoint, Endpoint):
        parsed = urlparse(endpoint.value)
    elif isinstance(endpoint, str):
        parsed = urlparse(endpoint)
    else:
        raise TypeError(
            f"Invalid endpoint type: {type(endpoint).__name__}. "
            "Expected type 'Endpoint' or 'str'. Please provide a valid endpoint "
            "as a string (e.g., 'https://example.com') or an Endpoint instance, "
            "imported `from arize.otel import Endpoint`."
        )
    if not all([parsed.scheme, parsed.netloc]):
        raise ValueError(f"Invalid endpoint: {endpoint}. Please provide a valid URL.")


def _validate_transport(transport: Any) -> None:
    if not isinstance(transport, Transport):
        raise TypeError(
            f"Invalid transport type: {type(transport).__name__}. "
            "Expected type 'Transport'. Please provide a valid Transport instance, "
            "imported `from arize.otel import Transport`."
        )


def _get_class_signature(fn: Type[Any]) -> inspect.Signature:
    if sys.version_info >= (3, 9):
        return inspect.signature(fn)
    elif sys.version_info >= (3, 8):
        init_signature = inspect.signature(fn.__init__)
        new_params = list(init_signature.parameters.values())[1:]  # Skip 'self'
        new_sig = init_signature.replace(parameters=new_params)
        return new_sig
    else:
        raise RuntimeError("Unsupported Python version")
