"""Tests for the question generator."""

import pytest
from unittest.mock import MagicMock
from slop_detector.question_generator import QuestionGenerator, Question
from slop_detector.models import FileAnalysis, DDCResult, InflationResult, LDRResult
from slop_detector.metrics.docstring_inflation import DocstringInflationResult
from slop_detector.metrics.hallucination_deps import HallucinationDepsResult
from slop_detector.metrics.context_jargon import ContextJargonResult

@pytest.fixture
def generator():
    return QuestionGenerator()

@pytest.fixture
def mock_analysis():
    analysis = MagicMock(spec=FileAnalysis)
    
    # Mock DDC
    analysis.ddc = MagicMock(spec=DDCResult)
    analysis.ddc.unused = []
    analysis.ddc.usage_ratio = 1.0
    analysis.ddc.imported = []
    
    # Mock Inflation
    analysis.inflation = MagicMock(spec=InflationResult)
    analysis.inflation.jargon_details = []
    analysis.inflation.inflation_score = 0.0
    
    # Mock LDR
    analysis.ldr = MagicMock(spec=LDRResult)
    analysis.ldr.ldr_score = 1.0
    analysis.ldr.empty_lines = 0
    analysis.ldr.total_lines = 10
    analysis.ldr.logic_lines = 10
    
    # Mock Docstring Inflation
    analysis.docstring_inflation = MagicMock(spec=DocstringInflationResult)
    analysis.docstring_inflation.details = []
    analysis.docstring_inflation.status = "PASS"
    analysis.docstring_inflation.inflated_count = 0
    
    # Mock Hallucination Deps
    analysis.hallucination_deps = MagicMock(spec=HallucinationDepsResult)
    analysis.hallucination_deps.total_hallucinated = 0
    analysis.hallucination_deps.category_usage = []
    analysis.hallucination_deps.hallucinated_deps = []
    
    # Mock Context Jargon
    analysis.context_jargon = MagicMock(spec=ContextJargonResult)
    analysis.context_jargon.justification_ratio = 1.0
    analysis.context_jargon.worst_offenders = []
    analysis.context_jargon.evidence_details = []
    
    # Mock Pattern Issues
    analysis.pattern_issues = []
    
    return analysis

def test_ddc_questions(generator, mock_analysis):
    """Test DDC question generation."""
    # 1. Single unused import
    mock_analysis.ddc.unused = ["numpy"]
    qs = generator._generate_ddc_questions(mock_analysis)
    assert len(qs) == 1
    assert "Why is 'numpy' imported" in qs[0].question
    
    # 2. Multiple unused imports
    mock_analysis.ddc.unused = ["numpy", "pandas", "torch"]
    qs = generator._generate_ddc_questions(mock_analysis)
    assert len(qs) == 1
    assert "Why are 'numpy', 'pandas', 'torch' imported" in qs[0].question
    
    # 3. Many unused imports
    mock_analysis.ddc.unused = ["a", "b", "c", "d"]
    qs = generator._generate_ddc_questions(mock_analysis)
    assert len(qs) == 1
    assert "Why are 4 imports" in qs[0].question
    
    # 4. Critical usage ratio
    mock_analysis.ddc.usage_ratio = 0.1
    mock_analysis.ddc.imported = ["a", "b", "c", "d", "e", "f"]
    qs = generator._generate_ddc_questions(mock_analysis)
    # Should have the "many unused" warning + "critical ratio" question
    assert len(qs) == 2
    assert any(q.severity == "critical" for q in qs)

def test_inflation_questions(generator, mock_analysis):
    """Test inflation/jargon questions."""
    # 1. Single jargon on line
    mock_analysis.inflation.jargon_details = [
        {"word": "scalable", "category": "scale", "line": 10}
    ]
    qs = generator._generate_inflation_questions(mock_analysis)
    assert len(qs) == 1
    assert "What evidence supports the claim 'scalable'" in qs[0].question
    
    # 2. Multiple jargon on same line
    mock_analysis.inflation.jargon_details = [
        {"word": "scalable", "category": "scale", "line": 10},
        {"word": "robust", "category": "quality", "line": 10}
    ]
    qs = generator._generate_inflation_questions(mock_analysis)
    assert len(qs) == 1
    assert "Multiple buzzwords" in qs[0].question
    
    # 3. High overall inflation
    mock_analysis.inflation.inflation_score = 2.0
    qs = generator._generate_inflation_questions(mock_analysis)
    assert any(q.severity == "critical" for q in qs)

def test_ldr_questions(generator, mock_analysis):
    """Test LDR (Logic Density) questions."""
    mock_analysis.ldr.ldr_score = 0.1
    mock_analysis.ldr.empty_lines = 60
    mock_analysis.ldr.total_lines = 100
    mock_analysis.ldr.logic_lines = 10
    
    qs = generator._generate_ldr_questions(mock_analysis)
    assert len(qs) >= 1
    assert any("empty lines" in q.question for q in qs)
    assert any("actual logic" in q.question for q in qs)

def test_docstring_inflation_questions(generator, mock_analysis):
    """Test docstring inflation questions."""
    # Mock details with attributes
    detail_crit = MagicMock()
    detail_crit.severity = "critical"
    detail_crit.name = "bad_func"
    detail_crit.docstring_lines = 20
    detail_crit.implementation_lines = 1
    detail_crit.line = 5
    
    detail_warn = MagicMock()
    detail_warn.severity = "warning"
    detail_warn.name = "warn_func"
    detail_warn.docstring_lines = 5
    detail_warn.implementation_lines = 2
    detail_warn.line = 10
    
    mock_analysis.docstring_inflation.details = [detail_crit, detail_warn]
    mock_analysis.docstring_inflation.status = "FAIL"
    mock_analysis.docstring_inflation.total_docstring_lines = 100
    mock_analysis.docstring_inflation.total_implementation_lines = 10
    mock_analysis.docstring_inflation.overall_ratio = 10.0
    
    qs = generator._generate_docstring_inflation_questions(mock_analysis)
    
    assert len(qs) >= 3  # crit detail, warn detail, file fail
    assert any("bad_func" in q.question for q in qs)
    assert any("warn_func" in q.question for q in qs)
    assert any("This file has 100 lines of docstrings" in q.question for q in qs)

def test_hallucination_deps_questions(generator, mock_analysis):
    """Test hallucinated dependencies questions."""
    # Critical threshold
    mock_analysis.hallucination_deps.total_hallucinated = 6
    
    # Category usage mock
    cat_usage = MagicMock()
    cat_usage.unused = ["torch"]
    cat_usage.usage_ratio = 0.0
    cat_usage.category = "ml"
    mock_analysis.hallucination_deps.category_usage = [cat_usage]
    
    # Individual dep mock
    hal_dep = MagicMock()
    hal_dep.library = "torch"
    hal_dep.likely_intent = "ML"
    hal_dep.line = 1
    hal_dep.category = "ml"
    mock_analysis.hallucination_deps.hallucinated_deps = [hal_dep]
    
    qs = generator._generate_hallucination_deps_questions(mock_analysis)
    
    assert any(q.severity == "critical" for q in qs)
    assert any("Imported 'torch' but never used" in q.question for q in qs)

def test_context_jargon_questions(generator, mock_analysis):
    """Test context jargon questions."""
    mock_analysis.context_jargon.justification_ratio = 0.1
    mock_analysis.context_jargon.worst_offenders = ["scalable", "robust"]
    
    evidence = MagicMock()
    evidence.is_justified = False
    evidence.evidence_ratio = 0.0
    evidence.jargon = "scalable"
    evidence.line = 5
    evidence.missing_evidence = ["tests", "metrics"]
    mock_analysis.context_jargon.evidence_details = [evidence]
    
    qs = generator._generate_context_jargon_questions(mock_analysis)
    
    assert any(q.severity == "critical" for q in qs)
    assert any("ZERO supporting evidence" in q.question for q in qs)
    assert any("lacks: tests, metrics" in q.question for q in qs)

def test_pattern_questions(generator, mock_analysis):
    """Test pattern issue questions."""
    issue = MagicMock()
    issue.pattern_id = "empty_except"
    issue.severity = "critical" # string or enum
    issue.line = 10
    
    mock_analysis.pattern_issues = [issue]
    
    qs = generator._generate_pattern_questions(mock_analysis)
    assert len(qs) == 1
    assert "Why is this exception handler empty" in qs[0].question

def test_format_questions_text(generator):
    """Test text formatting."""
    qs = [
        Question("CritQ", "critical", 1),
        Question("WarnQ", "warning", 2),
        Question("InfoQ", "info", 3)
    ]
    
    text = generator.format_questions_text(qs)
    assert "CRITICAL QUESTIONS" in text
    assert "WARNING QUESTIONS" in text
    assert "INFO QUESTIONS" in text
    assert "CritQ" in text
    assert "WarnQ" in text
    assert "InfoQ" in text
