import os
from enum import Enum
from typing import List, Optional, Union

from openinference.semconv.resource import ResourceAttributes
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
    OTLPSpanExporter as GrpcSpanExporter,
)
from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
    OTLPSpanExporter as HttpSpanExporter,
)
from opentelemetry.sdk.trace import Resource, TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    ConsoleSpanExporter,
    SimpleSpanProcessor,
)


class Endpoints(str, Enum):
    ARIZE = "https://otlp.arize.com/v1"
    PHOENIX_LOCAL = "http://localhost:4317/v1/traces"
    HOSTED_PHOENIX = "https://app.phoenix.arize.com/v1/traces"


EndpointsType = Union[str, List[str], Endpoints, List[Endpoints]]


def register_otel(
    endpoints: EndpointsType,
    # authentication for arize and hosted phoenix
    api_key: Optional[str] = None,
    # arize specific
    space_key: Optional[str] = None,
    model_id: Optional[str] = None,
    model_version: Optional[str] = None,
    # phoenix specific
    project_name: Optional[str] = None,
    # debugging
    log_to_console: bool = False,
    # config
    use_batch_processor: bool = True,
) -> None:
    """
    Sets up a `TracerProvider` with the corresponding `Resource` and with
    multiple, if appropriate, `SimpleSpanProcessor`s.
    Each `SimpleSpanProcessor` (one per endpoint) is provided with an `OTLPSpanExporter`
    pointing to the corresponding endpoint.

    Parameters:
    -----------
        endpoints(str, List[str], Endpoints, List[Endpoints]): set of endpoints to set up.
            It can be one or many endpoints. If you'd like to send traces to Arize and/or Phoenix,
            we recommend the use of Endpoints.ARIZE and Endpoints.PHOENIX_LOCAL, respecitvely.
        space_key(str, optional): This is Arize specific. The space key is necessary for
            authentication when sending traces to Arize and you can find it in the
            Space Settings page in the Arize platform. Defaults to None.
        api_key(str, optional): This is Arize specific. The api key is necessary for
            authentication when sending traces to Arize and you can find it in the
            Space Settings page in the Arize platform. Defaults to None.
        model_id(str, optional): This is Arize specific. The model ID is a unique name
            to identify your model in the Arize platform. Defaults to None.
        model_version(str, optional): This is Arize specific. The model version is
            used to group a subset of data, given the same model ID,
            to compare and track changes. Defaults to None.
        project_name(str, optional): This is Phoenix specific. A project is a collection of
            traces that are related to a single application or service. You can have
            multiple projects, each with multiple traces. Defaults to None.
        log_to_console(bool, optional): Enable this option while developing so the
            spans are printed in the console. Defaults to False.
        use_batch_processor(bool, optional): Enable this option to use
            `BatchSpanProcessor` instead of the default `SimpleSpanProcessor`.
            Defaults to False.

    Returns:
    --------
        None
    """
    if not isinstance(use_batch_processor, bool):
        raise TypeError("use_batch_processor must be of type bool")

    if not isinstance(endpoints, list):
        endpoints = [endpoints]

    if Endpoints.ARIZE in endpoints:
        validate_for_arize(space_key, api_key, model_id)

    if Endpoints.HOSTED_PHOENIX in endpoints:
        validate_for_hosted_phoenix(api_key)

    set_auth_keys(space_key, api_key)

    provider = TracerProvider(
        resource=create_resource(
            model_id,
            model_version,
            project_name,
        )
    )

    processor = BatchSpanProcessor if use_batch_processor else SimpleSpanProcessor

    for endpoint in endpoints:
        # Extract string value from Endpoints Enum, or use the string value passed by the user
        exporter = HttpSpanExporter if should_use_http(endpoint) else GrpcSpanExporter
        ep = endpoint.value if isinstance(endpoint, Endpoints) else endpoint
        provider.add_span_processor(
            span_processor=processor(
                span_exporter=exporter(endpoint=ep),
            )
        )

    if log_to_console:
        provider.add_span_processor(
            span_processor=processor(
                span_exporter=ConsoleSpanExporter(),
            )
        )

    trace.set_tracer_provider(tracer_provider=provider)


def should_use_http(
    endpoint: Endpoints,
) -> bool:
    return endpoint == Endpoints.HOSTED_PHOENIX


def validate_for_arize(
    space_key: str,
    api_key: str,
    model_id: str,
) -> None:
    if not space_key:
        raise ValueError("Missing 'space_key' to log traces into Arize")
    if not api_key:
        raise ValueError("Missing 'api_key' to log traces into Arize")
    if not model_id:
        raise ValueError("Missing 'model_id' to log traces into Arize")


def validate_for_hosted_phoenix(api_key: str) -> None:
    if not api_key:
        raise ValueError("Missing 'api_key' to log traces into Hosted Phoenix")


def create_resource(
    model_id: str,
    model_version: str,
    project_name: str,
) -> Resource:
    attributes = {}
    if model_id:
        attributes["model_id"] = model_id
    if model_version:
        attributes["model_version"] = model_version
    if project_name:
        attributes[ResourceAttributes.PROJECT_NAME] = project_name
    return Resource(attributes=attributes)


def set_auth_keys(
    space_key: str,
    api_key: str,
) -> None:
    # Set the Space and API keys as headers
    os.environ["OTEL_EXPORTER_OTLP_TRACES_HEADERS"] = f"space_key={space_key},api_key={api_key}"
