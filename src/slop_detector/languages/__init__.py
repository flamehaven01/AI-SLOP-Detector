"""
Multi-Language Support Framework
Extensible architecture for analyzing 7+ programming languages
"""

from .base import LanguageAnalyzer, AnalysisResult
from .python_analyzer import PythonAnalyzer
# from .javascript_analyzer import JavaScriptAnalyzer
# from .typescript_analyzer import TypeScriptAnalyzer
# from .java_analyzer import JavaAnalyzer
# from .go_analyzer import GoAnalyzer
# from .rust_analyzer import RustAnalyzer
# from .cpp_analyzer import CppAnalyzer
# from .csharp_analyzer import CSharpAnalyzer

__all__ = [
    'LanguageAnalyzer',
    'AnalysisResult',
    'PythonAnalyzer',
    # 'JavaScriptAnalyzer',
    # 'TypeScriptAnalyzer',
    # 'JavaAnalyzer',
    # 'GoAnalyzer',
    # 'RustAnalyzer',
    # 'CppAnalyzer',
    # 'CSharpAnalyzer',
    'get_analyzer_for_file',
]

# Language to analyzer mapping
LANGUAGE_ANALYZERS = {
    '.py': PythonAnalyzer,
    # '.js': JavaScriptAnalyzer,
    # '.jsx': JavaScriptAnalyzer,
    # '.ts': TypeScriptAnalyzer,
    # '.tsx': TypeScriptAnalyzer,
    # '.java': JavaAnalyzer,
    # '.go': GoAnalyzer,
    # '.rs': RustAnalyzer,
    # '.cpp': CppAnalyzer,
    # '.cc': CppAnalyzer,
    # '.cxx': CppAnalyzer,
    # '.hpp': CppAnalyzer,
    # '.h': CppAnalyzer,
    # '.cs': CSharpAnalyzer,
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
