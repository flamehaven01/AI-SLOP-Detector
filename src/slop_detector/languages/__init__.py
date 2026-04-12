"""
Multi-Language Support Framework.
PythonAnalyzer is the primary implementation.
JSAnalyzer (v2.8.0) provides JS/TS support via tree-sitter AST (optional) with regex fallback.
"""

from .base import AnalysisResult, LanguageAnalyzer
from .js_analyzer import JSAnalyzer
from .python_analyzer import PythonAnalyzer

__all__ = [
    "LanguageAnalyzer",
    "AnalysisResult",
    "PythonAnalyzer",
    "JSAnalyzer",
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
