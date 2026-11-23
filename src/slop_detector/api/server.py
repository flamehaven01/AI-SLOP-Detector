"""FastAPI REST API server for AI SLOP Detector.

Requires the [api] extras: pip install ai-slop-detector[api]
"""

import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

try:
    from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.middleware.trustedhost import TrustedHostMiddleware
except ImportError:
    raise ImportError(
        "FastAPI is required for the API server. " "Install with: pip install ai-slop-detector[api]"
    )

from .. import __version__
from ..history import (
    HISTORY_NOT_RECORDED,
    HistoryBackupError,
    HistoryTracker,
    history_project_root,
    measurement_provenance,
)
from ..language_registry import all_file_results
from ..service.scan import ScanFailedError, ScanRequest, ScanService, WritePolicy
from .models import (
    AgentFileResponse,
    AgentProjectResponse,
    AgentSurfaceManifest,
    AnalysisRequest,
    AnalysisResponse,
    TrendResponse,
    WebhookPayload,
)

logger = logging.getLogger(__name__)


def _project_id_for_path(path: Path) -> str:
    import hashlib

    return hashlib.sha256(str(path.resolve()).encode("utf-8")).hexdigest()[:12]


# Host names the API answers by default. A page the user visits can reach 127.0.0.1 from the
# browser; under its own host name (DNS rebinding) it gets 400 instead of a scan.
LOOPBACK_HOSTS = ("127.0.0.1", "localhost", "[::1]")


def create_app(
    config_path: Optional[Path] = None,
    allowed_origins: Sequence[str] = (),
    allowed_hosts: Sequence[str] = (),
) -> FastAPI:
    """Create the FastAPI application.

    The API has no authentication and scans any path it is sent, so by default it answers
    only local clients: no cross-origin access (a web page of another origin cannot read a
    scan) and only loopback host names. `allowed_origins` lists origins that may call it
    (without credentials); `allowed_hosts` adds host names, e.g. the address it is bound to.
    """

    app = FastAPI(
        title="AI SLOP Detector API",
        description="REST API for detecting AI-generated code quality issues",
        version=__version__,
        docs_url="/docs",
        redoc_url="/redoc",
    )

    app.add_middleware(
        TrustedHostMiddleware, allowed_hosts=list(LOOPBACK_HOSTS) + list(allowed_hosts)
    )
    if allowed_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(allowed_origins),
            allow_credentials=False,
            allow_methods=["GET", "POST"],
            allow_headers=["content-type"],
        )

    def scan(target: Path, mode: str):
        """Read-only scan with the app's config only: no analysis cache, no history.
        The /analyze/* routes record history themselves when a request asks."""
        request = ScanRequest(
            target=target,
            mode=mode,
            config_path=Path(config_path) if config_path else None,
            discover_config=False,
            writes=WritePolicy.READ_ONLY,
        )
        try:
            return ScanService().run(request)
        except ScanFailedError as exc:
            status = 400 if exc.kind == "unsupported_language" else 500
            raise HTTPException(status_code=status, detail=exc.detail) from None

    # Dependency injection
    def get_history() -> HistoryTracker:
        return HistoryTracker()

    # Routes
    @app.get("/")
    async def root():
        return {
            "service": "AI SLOP Detector API",
            "version": __version__,
            "docs": "/docs",
            "health": "/health",
        }

    @app.get("/health")
    async def health():
        return {"status": "healthy", "timestamp": datetime.utcnow().isoformat()}

    @app.get("/agent/schema", response_model=AgentSurfaceManifest)
    async def agent_schema():
        """Describe the agent-native surface and available endpoints."""
        return AgentSurfaceManifest(
            capabilities=[
                "structured project snapshots",
                "structured file snapshots",
                "priority hotspots",
                "suppression ledger",
                "structural coherence mode",
            ],
            endpoints=[
                {
                    "path": "/agent/file",
                    "method": "POST",
                    "description": "Structured snapshot for a single file analysis",
                },
                {
                    "path": "/agent/project",
                    "method": "POST",
                    "description": "Structured snapshot for a full project analysis",
                },
                {
                    "path": "/agent/schema",
                    "method": "GET",
                    "description": "Describe the agent-native response contract",
                },
            ],
            notes=[
                "Existing /analyze/* routes remain available for backward compatibility.",
                "Agent responses include hotspot, suppression, and coherence metadata.",
            ],
        )

    @app.post("/analyze/file", response_model=AnalysisResponse)
    async def analyze_file(request: AnalysisRequest):
        """Analyze a single file"""
        try:
            file_path = Path(request.file_path)
            if not file_path.exists():
                raise HTTPException(status_code=404, detail="File not found")

            outcome = scan(file_path, "python_file")
            result = outcome.result

            # Save to history if asked; opening the tracker creates its database.
            if request.save_history:
                try:
                    tracker = get_history()
                except HistoryBackupError as exc:
                    _history_not_recorded(exc)
                else:
                    tracker.record(
                        result,
                        git_commit=request.metadata.get("commit"),
                        git_branch=request.metadata.get("branch"),
                        project_id=_project_id_for_path(file_path.parent),
                        provenance=measurement_provenance(
                            outcome.config, history_project_root(str(file_path), False)
                        ),
                    )

            return AnalysisResponse.from_result(result)

        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    @app.post("/agent/file", response_model=AgentFileResponse)
    async def analyze_file_agent(request: AnalysisRequest):
        """Analyze a single file and return an agent-friendly snapshot."""
        try:
            file_path = Path(request.file_path)
            if not file_path.exists():
                raise HTTPException(status_code=404, detail="File not found")
            return AgentFileResponse.from_result(scan(file_path, "python_file").result)
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    @app.post("/analyze/project", response_model=List[AnalysisResponse])
    async def analyze_project(
        request: AnalysisRequest,
        background_tasks: BackgroundTasks,
    ):
        """Analyze entire project (async)"""
        try:
            project_path = Path(request.project_path)
            if not project_path.exists():
                raise HTTPException(status_code=404, detail="Project not found")

            outcome = scan(project_path, "project")
            results = outcome.result

            # Background task: save to history
            if request.save_history:
                background_tasks.add_task(
                    _save_project_history,
                    all_file_results(results),
                    project_path,
                    request.metadata,
                    measurement_provenance(outcome.config, project_path),
                )

            return [AnalysisResponse.from_result(r) for r in results.file_results]

        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    @app.post("/agent/project", response_model=AgentProjectResponse)
    async def analyze_project_agent(request: AnalysisRequest):
        """Analyze a project and return the agent-native structured snapshot."""
        try:
            project_path = Path(request.project_path)
            if not project_path.exists():
                raise HTTPException(status_code=404, detail="Project not found")
            return AgentProjectResponse.from_result(scan(project_path, "project").result)
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    @app.get("/history/file/{file_path:path}", response_model=List[AnalysisResponse])
    async def get_file_history(
        file_path: str,
        limit: int = 10,
        history: HistoryTracker = Depends(get_history),
    ):
        """Get analysis history for a file"""
        records = history.get_file_history(file_path, limit=limit)
        return [AnalysisResponse.from_dict(r) for r in records]

    @app.get("/trends/project", response_model=TrendResponse)
    async def get_project_trends(
        project_path: str,
        days: int = 30,
        history: HistoryTracker = Depends(get_history),
    ):
        """Get quality trends for project"""
        trends = history.get_project_trends(days=days)
        return TrendResponse.from_history(project_path, trends)

    # Routes kept so clients get an explicit answer; no work is done or queued.
    @app.post("/webhook/github", status_code=501)
    async def github_webhook(payload: WebhookPayload):
        """GitHub push analysis is not implemented: answers 501 and schedules nothing."""
        raise HTTPException(status_code=501, detail="GitHub push analysis is not implemented.")

    @app.get("/status/project/{project_id}", status_code=501)
    async def get_project_status(project_id: str):
        """Project status is not implemented: answers 501."""
        raise HTTPException(status_code=501, detail="Project status backend is not implemented.")

    return app


def _history_not_recorded(exc: Exception) -> None:
    """The analysis is answered; history is not recorded (the pre-upgrade copy failed)."""
    logger.warning(HISTORY_NOT_RECORDED)
    logger.debug("history not recorded: %s", exc)


async def _save_project_history(
    results: List[Any], project_path: Path, metadata: Dict[str, Any], provenance=None
):
    """Background task to save project analysis"""
    try:
        history = HistoryTracker()
    except HistoryBackupError as exc:
        _history_not_recorded(exc)
        return
    project_id = _project_id_for_path(project_path)
    for result in results:
        history.record(
            result,
            git_commit=metadata.get("commit"),
            git_branch=metadata.get("branch"),
            project_id=project_id,
            provenance=provenance,
        )


def run_server(
    host: str = "127.0.0.1",
    port: int = 8000,
    config_path: Optional[Path] = None,
):
    """Run the API server on this machine only, unless a host is given.

    The API has no authentication and reads any path it is sent, so binding a
    network interface (host="0.0.0.0") exposes that to the network. The bound host
    is answered as a host name besides the loopback names; other names get 400.
    """
    import uvicorn

    extra = () if host in LOOPBACK_HOSTS or host in ("0.0.0.0", "::") else (host,)
    app = create_app(config_path, allowed_hosts=extra)
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    run_server()
