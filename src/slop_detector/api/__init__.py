"""REST API surface with lazy server imports for optional FastAPI support."""

from .models import (
    AgentFileResponse,
    AgentProjectResponse,
    AgentSurfaceManifest,
    AnalysisRequest,
    AnalysisResponse,
    WebhookPayload,
)


def create_app(*args, **kwargs):
    """Lazily import the FastAPI server factory."""
    from .server import create_app as _create_app

    return _create_app(*args, **kwargs)


def run_server(*args, **kwargs):
    """Lazily import the FastAPI runner."""
    from .server import run_server as _run_server

    return _run_server(*args, **kwargs)


__all__ = [
    "create_app",
    "run_server",
    "AnalysisRequest",
    "AnalysisResponse",
    "WebhookPayload",
    "AgentSurfaceManifest",
    "AgentFileResponse",
    "AgentProjectResponse",
]
