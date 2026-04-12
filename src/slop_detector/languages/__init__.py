"""
Multi-Language Support Framework.
PythonAnalyzer is the primary implementation.
JSAnalyzer (v2.8.0) provides JS/TS support via tree-sitter AST (optional) with regex fallback.
GoAnalyzer (v1.0.0) provides Go support with regex fallback and optional tree-sitter-go.
"""

from .base import AnalysisResult, LanguageAnalyzer
from .go_analyzer import GoAnalyzer
from .js_analyzer import JSAnalyzer
from .python_analyzer import PythonAnalyzer

__all__ = [
    "LanguageAnalyzer",
    "AnalysisResult",
    "PythonAnalyzer",
    "JSAnalyzer",
    "GoAnalyzer",
    "get_analyzer_for_file",
    "LANGUAGE_ANALYZERS",
]

# Language to analyzer mapping
LANGUAGE_ANALYZERS = {
    ".py": PythonAnalyzer,
    ".js": JSAnalyzer,
    ".jsx": JSAnalyzer,
    ".ts": JSAnalyzer,
    ".tsx": JSAnalyzer,
    ".go": GoAnalyzer,
}


def get_analyzer_for_file(file_path: str) -> LanguageAnalyzer:
    """Get appropriate analyzer for file extension"""
    import os

    _, ext = os.path.splitext(file_path)
    ext = ext.lower()

    analyzer_class = LANGUAGE_ANALYZERS.get(ext)

    if analyzer_class is None:
        raise ValueError(f"Unsupported file extension: {ext}")

    return analyzer_class()
