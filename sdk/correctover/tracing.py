# Copyright 2024-2025 Correctover Team
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.

"""OpenTelemetry tracing integration for Correctover SDK.

Each MAPE-K phase = one span, each full call = one trace.
Auto-configured via environment variables:
  OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317
  OTEL_SERVICE_NAME=correctover-sdk
"""

import os
from typing import Optional

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.resources import Resource


# Span name templates
SPAN_CALL = "correctover.call"
SPAN_MONITOR = "correctover.monitor"
SPAN_ANALYZE = "correctover.analyze"
SPAN_PLAN = "correctover.plan"
SPAN_EXECUTE = "correctover.execute"
SPAN_KNOWLEDGE = "correctover.knowledge"


def setup_tracing(
    service_name: str = "correctover-sdk",
    endpoint: Optional[str] = None,
    enabled: bool = True,
) -> trace.Tracer:
    """Configure OpenTelemetry tracing for Correctover.

    Args:
        service_name: Service name shown in Jaeger/Zipkin.
        endpoint: OTLP endpoint (default: from OTEL_EXPORTER_OTLP_ENDPOINT env).
        enabled: Set False to disable tracing entirely.

    Returns:
        Configured Tracer instance.
    """
    if not enabled:
        # No-op tracer
        provider = TracerProvider()
        trace.set_tracer_provider(provider)
        return trace.get_tracer("correctover", "0.0.0")

    resource = Resource.create({
        "service.name": service_name,
        "service.version": os.environ.get("CORRECTOVER_VERSION", "4.4.2"),
    })

    provider = TracerProvider(resource=resource)

    # Only set up exporter if endpoint is configured
    otlp_endpoint = endpoint or os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "")
    if otlp_endpoint:
        try:
            from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
                OTLPSpanExporter,
            )
            exporter = OTLPSpanExporter(endpoint=otlp_endpoint, insecure=False)
            provider.add_span_processor(BatchSpanProcessor(exporter))
        except Exception:
            # If OTLP exporter fails, fall back to console
            from opentelemetry.sdk.trace.export import ConsoleSpanExporter
            provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))
    else:
        # No endpoint configured — use console exporter for development
        from opentelemetry.sdk.trace.export import ConsoleSpanExporter
        provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))

    trace.set_tracer_provider(provider)
    return trace.get_tracer("correctover", "4.4.2")


def get_tracer() -> trace.Tracer:
    """Get the Correctover tracer (lazy init)."""
    return trace.get_tracer("correctover", "4.4.2")


# Auto-setup on import if OTEL_ENABLED=1
if os.environ.get("CORRECTOVER_TRACING", "0") == "1":
    setup_tracing()
