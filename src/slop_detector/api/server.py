"""FastAPI REST API server for AI SLOP Detector"""

from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from ..core import SlopDetector
from ..history import HistoryTracker
from .models import (
    AnalysisRequest,
    AnalysisResponse,
    ProjectStatus,
    TrendResponse,
    WebhookPayload,
)


def create_app(config_path: Optional[Path] = None) -> FastAPI:
    """Create FastAPI application"""

    app = FastAPI(
        title="AI SLOP Detector API",
        description="REST API for detecting AI-generated code quality issues",
        version="2.4.0",
        docs_url="/docs",
        redoc_url="/redoc",
    )

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # Configure in production
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Dependency injection
    def get_detector() -> SlopDetector:
        return SlopDetector(config_path=config_path)

    def get_history() -> HistoryTracker:
        return HistoryTracker()

    # Routes
    @app.get("/")
    async def root():
        return {
            "service": "AI SLOP Detector API",
            "version": "2.4.0",
            "docs": "/docs",
            "health": "/health",
        }

    @app.get("/health")
    async def health():
        return {"status": "healthy", "timestamp": datetime.utcnow().isoformat()}

    @app.post("/analyze/file", response_model=AnalysisResponse)
    async def analyze_file(
        request: AnalysisRequest,
        detector: SlopDetector = Depends(get_detector),
        history: HistoryTracker = Depends(get_history),
    ):
        """Analyze a single file"""
        try:
            file_path = Path(request.file_path)
            if not file_path.exists():
                raise HTTPException(status_code=404, detail="File not found")

            result = detector.analyze_file(str(file_path))

            # Save to history if enabled
            if request.save_history:
                history.record_analysis(
                    file_path=str(file_path),
                    result=result,
                    metadata=request.metadata,
                )

            return AnalysisResponse.from_result(result)

        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    @app.post("/analyze/project", response_model=List[AnalysisResponse])
    async def analyze_project(
        request: AnalysisRequest,
        background_tasks: BackgroundTasks,
        detector: SlopDetector = Depends(get_detector),
    ):
        """Analyze entire project (async)"""
        try:
            project_path = Path(request.project_path)
            if not project_path.exists():
                raise HTTPException(status_code=404, detail="Project not found")

            results = detector.analyze_project(str(project_path))

            # Background task: save to history
            if request.save_history:
                background_tasks.add_task(
                    _save_project_history,
                    results,
                    request.metadata,
                )

            return [AnalysisResponse.from_result(r) for r in results]

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
        trends = history.get_trends(project_path, days=days)
        return TrendResponse.from_dict(trends)

    @app.post("/webhook/github")
    async def github_webhook(
        payload: WebhookPayload,
        background_tasks: BackgroundTasks,
    ):
        """Handle GitHub push webhook"""
        # Validate signature in production
        background_tasks.add_task(_analyze_github_push, payload)
        return {"status": "accepted", "job_id": payload.after[:8]}

    @app.get("/status/project/{project_id}")
    async def get_project_status(project_id: str) -> ProjectStatus:
        """Get current project quality status"""
        # Implementation depends on dashboard backend
        pass

    return app


async def _save_project_history(results: List[Any], metadata: Dict[str, Any]):
    """Background task to save project analysis"""
    history = HistoryTracker()
    for result in results:
        history.record_analysis(
            file_path=result.file_path,
            result=result,
            metadata=metadata,
        )


async def _analyze_github_push(payload: WebhookPayload):
    """Analyze files from GitHub push event"""
    # Clone repo, analyze changed files, post status
    pass


def run_server(
    host: str = "0.0.0.0",
    port: int = 8000,
    config_path: Optional[Path] = None,
):
    """Run API server"""
    import uvicorn

    app = create_app(config_path)
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    run_server()
