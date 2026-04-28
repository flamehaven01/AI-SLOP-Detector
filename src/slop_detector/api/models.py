"""API data models."""

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class AnalysisRequest(BaseModel):
    """Request to analyze file or project."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "file_path": "/path/to/file.py",
                "save_history": True,
                "metadata": {"commit": "abc123", "branch": "main"},
            }
        }
    )

    file_path: Optional[str] = None
    project_path: Optional[str] = None
    save_history: bool = True
    metadata: Dict[str, Any] = Field(default_factory=dict)


class AnalysisResponse(BaseModel):
    """Normalized API result for a single analyzed file."""

    file_path: str
    slop_score: float
    grade: str
    ldr_score: float
    bcr_score: float
    ddc_score: float
    patterns: List[Dict[str, Any]]
    ml_prediction: Optional[float] = None
    timestamp: str

    @classmethod
    def from_result(cls, result: Any) -> "AnalysisResponse":
        """Convert a current FileAnalysis object to the public API shape."""
        return cls(
            file_path=result.file_path,
            slop_score=result.deficit_score,
            grade=result.status.value,
            ldr_score=result.ldr.ldr_score,
            bcr_score=result.inflation.inflation_score,
            ddc_score=result.ddc.usage_ratio,
            patterns=[
                p.to_dict() if hasattr(p, "to_dict") else {"message": str(p)}
                for p in getattr(result, "pattern_issues", [])
            ],
            ml_prediction=getattr(result, "ml_score", None),
            timestamp=datetime.now().isoformat(),
        )

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AnalysisResponse":
        """Create from dict"""
        return cls(**data)


class WebhookPayload(BaseModel):
    """GitHub webhook payload."""

    ref: str
    before: str
    after: str
    repository: Dict[str, Any]
    commits: List[Dict[str, Any]]

    @property
    def branch(self) -> str:
        return self.ref.split("/")[-1]

    @property
    def changed_files(self) -> List[str]:
        """Extract all changed Python files"""
        files = set()
        for commit in self.commits:
            files.update(commit.get("added", []))
            files.update(commit.get("modified", []))
        return [f for f in files if f.endswith(".py")]


class ProjectStatus(BaseModel):
    """Current project quality status."""

    project_id: str
    project_name: str
    overall_score: float
    grade: str
    total_files: int
    files_analyzed: int
    last_analysis: str
    trend: str  # "improving" | "stable" | "degrading"
    alerts: List[str]


class TrendResponse(BaseModel):
    """Quality trends over time."""

    project_path: str
    period_days: int
    data_points: List[Dict[str, Any]]
    average_score: float
    trend_direction: str
    regression_count: int

    @classmethod
    def from_history(cls, project_path: str, data: Dict[str, Any]) -> "TrendResponse":
        daily = data.get("daily_trends", [])
        average = 0.0
        if daily:
            average = sum(item.get("avg_deficit", 0.0) for item in daily) / len(daily)

        trend_direction = "stable"
        if len(daily) >= 2:
            newest = daily[0].get("avg_deficit", 0.0)
            oldest = daily[-1].get("avg_deficit", 0.0)
            if newest < oldest:
                trend_direction = "improving"
            elif newest > oldest:
                trend_direction = "degrading"

        regression_count = sum(
            1
            for idx in range(len(daily) - 1)
            if daily[idx].get("avg_deficit", 0.0) > daily[idx + 1].get("avg_deficit", 0.0)
        )
        return cls(
            project_path=project_path,
            period_days=data.get("period_days", 0),
            data_points=daily,
            average_score=round(average, 2),
            trend_direction=trend_direction,
            regression_count=regression_count,
        )
