import os
from enum import Enum
from typing import List, Optional, Union
from warnings import warn

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
    LOCAL_PHOENIX_HTTP = "http://localhost:6006/v1/traces"
    LOCAL_PHOENIX_GRPC = "http://localhost:4317"
    HOSTED_PHOENIX = "https://app.phoenix.arize.com/v1/traces"


EndpointsType = Union[str, List[str], Endpoints, List[Endpoints]]


def register_otel(
    endpoints: EndpointsType,
    # authentication for arize and hosted phoenix
    api_key: Optional[str] = None,
    # arize specific
    space_id: Optional[str] = None,
    space_key: Optional[str] = None,
    model_id: Optional[str] = None,
    model_version: Optional[str] = None,
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
            we recommend the use of Endpoints.ARIZE and Endpoints.HOSTED_PHOENIX, respectively.
        space_id(str, optional): This is Arize specific. The space ID is necessary for
            authentication when sending traces to Arize and you can find it in the
            Space Settings page in the Arize platform. Defaults to None.
        space_key(str, optional): Deprecated - Use space_id instead.
        api_key(str, optional): This is Arize specific. The api key is necessary for
            authentication when sending traces to Arize and you can find it in the
            Space Settings page in the Arize platform. Defaults to None.
        model_id(str, optional): (Deprecated) This is Arize specific. The model ID is a unique name
            to identify your model in the Arize platform. Defaults to None.
        model_version(str, optional): This is Arize specific. The model version is
            used to group a subset of data, given the same model ID,
            to compare and track changes. Defaults to None.
        project_name(str, optional): A project is a collection of
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
    if space_key:
        warn(
            message="The space_key parameter is deprecated and will be removed in a future release. "
            + "Please use the space_id parameter instead.",
            category=DeprecationWarning,
            stacklevel=2,
        )

    if not isinstance(use_batch_processor, bool):
        raise TypeError("use_batch_processor must be of type bool")

    if not isinstance(endpoints, list):
        endpoints = [endpoints]

    if Endpoints.ARIZE in endpoints:
        validate_for_arize(space_id, space_key, api_key, model_id, project_name)

    if Endpoints.HOSTED_PHOENIX in endpoints:
        validate_for_hosted_phoenix(api_key)

    set_auth_keys(space_id, space_key, api_key)

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
    endpoint: Union[str, Endpoints],
) -> bool:
    if isinstance(endpoint, str) and endpoint.startswith("http"):
        return True
    return endpoint in (
        Endpoints.LOCAL_PHOENIX_HTTP,
        Endpoints.HOSTED_PHOENIX,
    )


def validate_for_arize(
    space_id: str, space_key: str, api_key: str, model_id: str, project_name: str
) -> None:
    if not (space_key or space_id):
        raise ValueError("Missing 'space_id' to log traces into Arize")
    if not api_key:
        raise ValueError("Missing 'api_key' to log traces into Arize")
    if not project_name and not model_id:
        raise ValueError(
            "Missing 'project_name' or 'model_id' to log traces into Arize"
        )


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
        attributes["model_id"] = project_name
        attributes[ResourceAttributes.PROJECT_NAME] = project_name
    return Resource(attributes=attributes)


def set_auth_keys(space_id: str, space_key: str, api_key: str) -> None:
    if space_id:
        auth_key_str = f"space_id={space_id},api_key={api_key}"
    else:
        auth_key_str = f"space_key={space_key},api_key={api_key}"
    os.environ["OTEL_EXPORTER_OTLP_TRACES_HEADERS"] = auth_key_str
