"""Test pattern detection."""

import ast
from pathlib import Path

import pytest

from slop_detector.patterns.structural import (
    BareExceptPattern,
    MutableDefaultArgPattern,
    StarImportPattern,
)
from slop_detector.patterns.placeholder import PassPlaceholderPattern, TodoCommentPattern
from slop_detector.patterns.cross_language import (
    JavaScriptPushPattern,
    JavaEqualsPattern,
)


def test_bare_except_detection():
    """Test bare except pattern detection."""
    code = """
try:
    risky_operation()
except:  # Should trigger
    pass
"""
    tree = ast.parse(code)
    pattern = BareExceptPattern()
    issues = pattern.check(tree, Path("test.py"), code)
    
    assert len(issues) == 1
    assert issues[0].pattern_id == "bare_except"
    assert issues[0].severity.value == "critical"


def test_mutable_default_arg():
    """Test mutable default argument detection."""
    code = """
def bad_function(items=[]):  # Should trigger
    items.append(1)
    return items
"""
    tree = ast.parse(code)
    pattern = MutableDefaultArgPattern()
    issues = pattern.check(tree, Path("test.py"), code)
    
    assert len(issues) == 1
    assert issues[0].pattern_id == "mutable_default_arg"
    assert issues[0].severity.value == "critical"


def test_star_import():
    """Test star import detection."""
    code = "from os import *"
    tree = ast.parse(code)
    pattern = StarImportPattern()
    issues = pattern.check(tree, Path("test.py"), code)
    
    assert len(issues) == 1
    assert issues[0].pattern_id == "star_import"


def test_pass_placeholder():
    """Test pass placeholder detection."""
    code = """
def not_implemented():
    pass  # Should trigger
"""
    tree = ast.parse(code)
    pattern = PassPlaceholderPattern()
    issues = pattern.check(tree, Path("test.py"), code)
    
    assert len(issues) == 1
    assert issues[0].pattern_id == "pass_placeholder"


def test_todo_comment():
    """Test TODO comment detection."""
    code = """
def needs_work():
    # TODO: implement this
    return None
"""
    tree = ast.parse(code)
    pattern = TodoCommentPattern()
    issues = pattern.check(tree, Path("test.py"), code)
    
    assert len(issues) == 1
    assert issues[0].pattern_id == "todo_comment"


def test_javascript_push():
    """Test JavaScript push pattern detection."""
    code = """
items = []
items.push(1)  # Should trigger
"""
    tree = ast.parse(code)
    pattern = JavaScriptPushPattern()
    issues = pattern.check(tree, Path("test.py"), code)
    
    assert len(issues) == 1
    assert issues[0].pattern_id == "js_push"
    assert "append" in issues[0].suggestion.lower()


def test_java_equals():
    """Test Java equals pattern detection."""
    code = """
if text1.equals(text2):  # Should trigger
    pass
"""
    tree = ast.parse(code)
    pattern = JavaEqualsPattern()
    issues = pattern.check(tree, Path("test.py"), code)
    
    assert len(issues) == 1
    assert issues[0].pattern_id == "java_equals"


def test_no_false_positives():
    """Test that good code doesn't trigger patterns."""
    good_code = """
def good_function(items=None):
    if items is None:
        items = []
    
    try:
        result = process(items)
    except ValueError as e:
        logger.error(f"Error: {e}")
        return None
    
    items.append(result)
    return items
"""
    tree = ast.parse(good_code)
    
    patterns = [
        BareExceptPattern(),
        MutableDefaultArgPattern(),
        PassPlaceholderPattern(),
    ]
    
    for pattern in patterns:
        issues = pattern.check(tree, Path("test.py"), good_code)
        assert len(issues) == 0, f"False positive from {pattern.id}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
