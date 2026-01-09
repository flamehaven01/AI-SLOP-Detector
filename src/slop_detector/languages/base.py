"""
Base Language Analyzer Interface
All language-specific analyzers must implement this interface
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Dict, Set, Optional
from enum import Enum


class SeverityLevel(str, Enum):
    """Issue severity levels"""

    BLOCKER = "blocker"
    CRITICAL = "critical"
    MAJOR = "major"
    MINOR = "minor"
    INFO = "info"


@dataclass
class CodeIssue:
    """Represents a code quality issue"""

    line_number: int
    severity: SeverityLevel
    category: str
    message: str
    suggestion: Optional[str] = None
    code_snippet: Optional[str] = None


@dataclass
class FunctionMetrics:
    """Metrics for a single function"""

    name: str
    start_line: int
    end_line: int
    lines_of_code: int
    cyclomatic_complexity: int
    cognitive_complexity: int
    parameters_count: int
    is_empty: bool
    has_docstring: bool


@dataclass
class AnalysisResult:
    """Complete analysis result for a file"""

    file_path: str
    language: str
    total_lines: int
    code_lines: int
    comment_lines: int
    blank_lines: int

    functions: List[FunctionMetrics]
    classes_count: int
    imports_count: int
    unused_imports: Set[str]

    avg_complexity: float
    max_complexity: int

    logic_density: float
    inflation_ratio: float
    dependency_score: float

    deficit_score: float
    grade: str

    issues: List[CodeIssue]

    def to_dict(self) -> Dict:
        """Serialize to dictionary"""
        return {
            "file_path": self.file_path,
            "language": self.language,
            "metrics": {
                "total_lines": self.total_lines,
                "code_lines": self.code_lines,
                "comment_lines": self.comment_lines,
                "blank_lines": self.blank_lines,
                "functions_count": len(self.functions),
                "classes_count": self.classes_count,
                "imports_count": self.imports_count,
                "unused_imports_count": len(self.unused_imports),
            },
            "complexity": {
                "average": self.avg_complexity,
                "maximum": self.max_complexity,
            },
            "quality_scores": {
                "logic_density": self.logic_density,
                "inflation_ratio": self.inflation_ratio,
                "dependency_score": self.dependency_score,
                "deficit_score": self.deficit_score,
                "grade": self.grade,
            },
            "functions": [
                {
                    "name": f.name,
                    "lines": f"{f.start_line}-{f.end_line}",
                    "loc": f.lines_of_code,
                    "complexity": f.cyclomatic_complexity,
                    "is_empty": f.is_empty,
                }
                for f in self.functions
            ],
            "issues": [
                {
                    "line": issue.line_number,
                    "severity": issue.severity.value,
                    "category": issue.category,
                    "message": issue.message,
                }
                for issue in self.issues
            ],
        }


class LanguageAnalyzer(ABC):
    """Abstract base class for language-specific analyzers"""

    def __init__(self):
        self.jargon = self._get_jargon()
        self.empty_patterns = self._get_empty_patterns()

    @abstractmethod
    def analyze(self, file_path: str) -> AnalysisResult:
        """Analyze a source file and return results"""
        pass

    @abstractmethod
    def _count_lines(self, file_path: str) -> Dict[str, int]:
        """Count different types of lines (code, comment, blank)"""
        pass

    @abstractmethod
    def _extract_functions(self, file_path: str) -> List[FunctionMetrics]:
        """Extract function metrics"""
        pass

    @abstractmethod
    def _calculate_complexity(self, file_path: str) -> Dict[str, float]:
        """Calculate cyclomatic and cognitive complexity"""
        pass

    @abstractmethod
    def _detect_unused_imports(self, file_path: str) -> Set[str]:
        """Detect unused imports/dependencies"""
        pass

    @abstractmethod
    def _get_jargon(self) -> Set[str]:
        """Get language-specific jargon terms"""
        pass

    @abstractmethod
    def _get_empty_patterns(self) -> List[str]:
        """Get language-specific empty code patterns"""
        pass

    def _calculate_logic_density(
        self, code_lines: int, empty_functions: int, total_functions: int
    ) -> float:
        """Calculate logic density ratio (LDR)"""
        if total_functions == 0:
            return 1.0

        empty_ratio = empty_functions / total_functions
        return max(0.0, 1.0 - empty_ratio)

    def _calculate_inflation_ratio(self, file_path: str, avg_complexity: float) -> float:
        """Calculate inflation-to-complexity ratio (ICR)"""
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read().lower()

        jargon_count = sum(1 for word in self.jargon if word in content)

        if avg_complexity == 0:
            return 0.0

        return jargon_count / avg_complexity

    def _calculate_dependency_score(self, total_imports: int, unused_imports: int) -> float:
        """Calculate dependency cleanliness score (DDC)"""
        if total_imports == 0:
            return 1.0

        used_imports = total_imports - unused_imports
        return used_imports / total_imports

    def _calculate_deficit_score(self, ldr: float, inflation: float, ddc: float) -> float:
        """Calculate overall Deficit score"""
        # Quality factor (0-1, higher is better)
        quality = (
            ldr * 0.4  # 40% weight on logic density
            + (1.0 - min(inflation / 2.0, 1.0)) * 0.3  # 30% weight on inflation ratio
            + ddc * 0.3  # 30% weight on dependency score
        )

        # Deficit score (0-100, lower is better)
        return round(100 * (1.0 - quality), 2)

    def _assign_grade(self, deficit_score: float) -> str:
        """Assign letter grade based on deficit score"""
        if deficit_score < 10:
            return "S++"
        elif deficit_score < 20:
            return "S+"
        elif deficit_score < 30:
            return "S"
        elif deficit_score < 40:
            return "A"
        elif deficit_score < 50:
            return "B"
        elif deficit_score < 60:
            return "C"
        elif deficit_score < 70:
            return "D"
        else:
            return "F"

    def _detect_issues(
        self, functions: List[FunctionMetrics], unused_imports: Set[str]
    ) -> List[CodeIssue]:
        """Detect code quality issues"""
        issues = []

        # Empty functions
        for func in functions:
            if func.is_empty:
                issues.append(
                    CodeIssue(
                        line_number=func.start_line,
                        severity=SeverityLevel.MAJOR,
                        category="empty_function",
                        message=f"Function '{func.name}' has no meaningful implementation",
                        suggestion="Add implementation or remove the function",
                    )
                )

        # High complexity
        for func in functions:
            if func.cyclomatic_complexity > 15:
                issues.append(
                    CodeIssue(
                        line_number=func.start_line,
                        severity=SeverityLevel.CRITICAL,
                        category="high_complexity",
                        message=f"Function '{func.name}' has high complexity ({func.cyclomatic_complexity})",
                        suggestion="Refactor into smaller functions",
                    )
                )
            elif func.cyclomatic_complexity > 10:
                issues.append(
                    CodeIssue(
                        line_number=func.start_line,
                        severity=SeverityLevel.MAJOR,
                        category="moderate_complexity",
                        message=f"Function '{func.name}' has moderate complexity ({func.cyclomatic_complexity})",
                        suggestion="Consider simplifying logic",
                    )
                )

        # Long functions
        for func in functions:
            if func.lines_of_code > 100:
                issues.append(
                    CodeIssue(
                        line_number=func.start_line,
                        severity=SeverityLevel.MAJOR,
                        category="long_function",
                        message=f"Function '{func.name}' is too long ({func.lines_of_code} LOC)",
                        suggestion="Break down into smaller functions",
                    )
                )

        # Missing docstrings
        for func in functions:
            if not func.has_docstring and func.lines_of_code > 5:
                issues.append(
                    CodeIssue(
                        line_number=func.start_line,
                        severity=SeverityLevel.MINOR,
                        category="missing_docstring",
                        message=f"Function '{func.name}' lacks documentation",
                        suggestion="Add docstring explaining purpose and parameters",
                    )
                )

        # Unused imports
        for imp in unused_imports:
            issues.append(
                CodeIssue(
                    line_number=1,  # Import location varies by language
                    severity=SeverityLevel.MINOR,
                    category="unused_import",
                    message=f"Unused import: '{imp}'",
                    suggestion="Remove unused import",
                )
            )

        return issues
