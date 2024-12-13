from opentelemetry.sdk.resources import Resource

from .otel import (
    PROJECT_NAME,
    BatchSpanProcessor,
    Endpoint,
    GRPCSpanExporter,
    HTTPSpanExporter,
    SimpleSpanProcessor,
    TracerProvider,
    Transport,
    register,
)

__all__ = [
    "PROJECT_NAME",
    "BatchSpanProcessor",
    "Endpoint",
    "GRPCSpanExporter",
    "HTTPSpanExporter",
    "Resource",
    "SimpleSpanProcessor",
    "TracerProvider",
    "Transport",
    "register",
]
