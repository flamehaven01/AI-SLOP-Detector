"""REST API for AI SLOP Detector v2.4.0"""

from .models import AnalysisRequest, AnalysisResponse, WebhookPayload
from .server import create_app, run_server

__all__ = ["create_app", "run_server", "AnalysisRequest", "AnalysisResponse", "WebhookPayload"]
