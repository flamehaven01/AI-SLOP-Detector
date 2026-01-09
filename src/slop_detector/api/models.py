"""API data models"""

from typing import Optional, List, Dict, Any
from datetime import datetime
from pydantic import BaseModel, Field


class AnalysisRequest(BaseModel):
    """Request to analyze file or project"""

    file_path: Optional[str] = None
    project_path: Optional[str] = None
    save_history: bool = True
    metadata: Dict[str, Any] = Field(default_factory=dict)

    class Config:
        schema_extra = {
            "example": {
                "file_path": "/path/to/file.py",
                "save_history": True,
                "metadata": {"commit": "abc123", "branch": "main"},
            }
        }


class AnalysisResponse(BaseModel):
    """Analysis result"""

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
        """Convert core result to API response"""
        return cls(
            file_path=result.file_path,
            slop_score=result.slop_score,
            grade=result.grade,
            ldr_score=result.ldr.ldr_score,
            bcr_score=result.bcr.bcr_score,
            ddc_score=result.ddc.usage_ratio,
            patterns=[p.to_dict() for p in result.patterns],
            ml_prediction=getattr(result, "ml_score", None),
            timestamp=datetime.utcnow().isoformat(),
        )

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AnalysisResponse":
        """Create from dict"""
        return cls(**data)


class WebhookPayload(BaseModel):
    """GitHub webhook payload"""

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
    """Current project quality status"""

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
    """Quality trends over time"""

    project_path: str
    period_days: int
    data_points: List[Dict[str, Any]]
    average_score: float
    trend_direction: str
    regression_count: int

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TrendResponse":
        return cls(**data)
