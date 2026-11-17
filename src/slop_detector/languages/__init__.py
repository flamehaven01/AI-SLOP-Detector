"""
Multi-Language Support Framework.
PythonAnalyzer is the primary implementation.
JSAnalyzer (v2.8.0) provides JS/TS support via tree-sitter AST (optional) with regex fallback.
GoAnalyzer (v1.0.0) provides Go support with regex fallback and optional tree-sitter-go.
"""

from slop_detector import language_registry as _registry

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

# Extension -> analyzer factory (calling it returns a new analyzer), derived
# from slop_detector.language_registry: Python, then every registered adapter.
# A snapshot taken at import; get_analyzer_for_file reads the registry at call
# time.
LANGUAGE_ANALYZERS = {
    ".py": PythonAnalyzer,
    **{ext: adapter.analyzer for adapter in _registry.languages() for ext in adapter.extensions},
}


def get_analyzer_for_file(file_path: str) -> LanguageAnalyzer:
    """Get appropriate analyzer for file extension"""
    import os

    _, ext = os.path.splitext(file_path)
    ext = ext.lower()

    if ext == ".py":
        return PythonAnalyzer()
    adapter = _registry.spec_for_suffix(ext)
    if adapter is None:
        raise ValueError(f"Unsupported file extension: {ext}")
    return adapter.analyzer()
