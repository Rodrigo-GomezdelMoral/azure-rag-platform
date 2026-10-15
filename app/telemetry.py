from uuid import uuid4

from agent_framework.observability import create_resource, enable_instrumentation, get_meter, get_tracer
from azure.identity import DefaultAzureCredential
from azure.monitor.opentelemetry import configure_azure_monitor
from opentelemetry import trace

from app.config import Settings

SERVICE = "azure-rag-platform"
tracer = get_tracer(SERVICE)
unverified_claims = get_meter(SERVICE).create_counter("app.unverified_claims", "1", "claims dropped by verification")


def configure(settings: Settings) -> None:
    if settings.applicationinsights_connection_string:
        resource = create_resource(service_name=SERVICE)
        connection = settings.applicationinsights_connection_string
        configure_azure_monitor(connection_string=connection, credential=DefaultAzureCredential(), resource=resource)
    enable_instrumentation(enable_sensitive_data=False)


def current_trace_id() -> str:
    trace_id = trace.get_current_span().get_span_context().trace_id
    return trace.format_trace_id(trace_id) if trace_id else uuid4().hex
