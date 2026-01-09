"""Cross-language pattern detectors - AI leaks patterns from other languages."""

import ast
from typing import Optional

from slop_detector.patterns.base import ASTPattern, Issue, Severity, Axis


class JavaScriptPushPattern(ASTPattern):
    """Detect .push() instead of .append() (JavaScript pattern)."""
    
    id = "js_push"
    severity = Severity.HIGH
    axis = Axis.QUALITY
    message = "JavaScript pattern: use .append() instead of .push()"
    
    def check_node(self, node: ast.AST, file, content) -> Optional[Issue]:
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Attribute):
                if node.func.attr == "push":
                    return self.create_issue_from_node(
                        node,
                        file,
                        suggestion="Use Python's .append() method"
                    )
        return None


class JavaScriptLengthPattern(ASTPattern):
    """Detect .length instead of len() (JavaScript pattern)."""
    
    id = "js_length"
    severity = Severity.HIGH
    axis = Axis.QUALITY
    message = "JavaScript pattern: use len() instead of .length"
    
    def check_node(self, node: ast.AST, file, content) -> Optional[Issue]:
        if isinstance(node, ast.Attribute):
            if node.attr == "length":
                return self.create_issue_from_node(
                    node,
                    file,
                    suggestion="Use Python's len(object) function"
                )
        return None


class JavaEqualsPattern(ASTPattern):
    """Detect .equals() instead of == (Java pattern)."""
    
    id = "java_equals"
    severity = Severity.HIGH
    axis = Axis.QUALITY
    message = "Java pattern: use == instead of .equals()"
    
    def check_node(self, node: ast.AST, file, content) -> Optional[Issue]:
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Attribute):
                if node.func.attr == "equals":
                    return self.create_issue_from_node(
                        node,
                        file,
                        suggestion="Use == for comparison in Python"
                    )
        return None


class JavaToStringPattern(ASTPattern):
    """Detect .toString() instead of str() (Java pattern)."""
    
    id = "java_tostring"
    severity = Severity.HIGH
    axis = Axis.QUALITY
    message = "Java pattern: use str() instead of .toString()"
    
    def check_node(self, node: ast.AST, file, content) -> Optional[Issue]:
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Attribute):
                if node.func.attr == "toString":
                    return self.create_issue_from_node(
                        node,
                        file,
                        suggestion="Use Python's str(object) function"
                    )
        return None


class RubyEachPattern(ASTPattern):
    """Detect .each instead of for loop (Ruby pattern)."""
    
    id = "ruby_each"
    severity = Severity.HIGH
    axis = Axis.QUALITY
    message = "Ruby pattern: use for loop instead of .each"
    
    def check_node(self, node: ast.AST, file, content) -> Optional[Issue]:
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Attribute):
                if node.func.attr == "each":
                    return self.create_issue_from_node(
                        node,
                        file,
                        suggestion="Use 'for item in collection:' in Python"
                    )
        return None


class RubyNilPattern(ASTPattern):
    """Detect .nil? instead of is None (Ruby pattern)."""
    
    id = "ruby_nil"
    severity = Severity.HIGH
    axis = Axis.QUALITY
    message = "Ruby pattern: use 'is None' instead of .nil?"
    
    def check_node(self, node: ast.AST, file, content) -> Optional[Issue]:
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Attribute):
                if node.func.attr == "nil?":
                    return self.create_issue_from_node(
                        node,
                        file,
                        suggestion="Use 'if value is None:' in Python"
                    )
        return None


class GoPrintPattern(ASTPattern):
    """Detect fmt.Println() instead of print() (Go pattern)."""
    
    id = "go_println"
    severity = Severity.MEDIUM
    axis = Axis.QUALITY
    message = "Go pattern: use print() instead of fmt.Println()"
    
    def check_node(self, node: ast.AST, file, content) -> Optional[Issue]:
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Attribute):
                if node.func.attr == "Println":
                    if isinstance(node.func.value, ast.Name):
                        if node.func.value.id == "fmt":
                            return self.create_issue_from_node(
                                node,
                                file,
                                suggestion="Use Python's print() function"
                            )
        return None


class CSharpLengthPattern(ASTPattern):
    """Detect .Length (capitalized) instead of len() (C# pattern)."""
    
    id = "csharp_length"
    severity = Severity.HIGH
    axis = Axis.QUALITY
    message = "C# pattern: use len() instead of .Length"
    
    def check_node(self, node: ast.AST, file, content) -> Optional[Issue]:
        if isinstance(node, ast.Attribute):
            if node.attr == "Length":  # Capitalized
                return self.create_issue_from_node(
                    node,
                    file,
                    suggestion="Use Python's len(object) function"
                )
        return None


class CSharpToLowerPattern(ASTPattern):
    """Detect .ToLower() instead of .lower() (C# pattern)."""
    
    id = "csharp_tolower"
    severity = Severity.MEDIUM
    axis = Axis.QUALITY
    message = "C# pattern: use .lower() instead of .ToLower()"
    
    def check_node(self, node: ast.AST, file, content) -> Optional[Issue]:
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Attribute):
                if node.func.attr == "ToLower":  # Capitalized
                    return self.create_issue_from_node(
                        node,
                        file,
                        suggestion="Use Python's .lower() method"
                    )
        return None


class PHPStrlenPattern(ASTPattern):
    """Detect strlen() instead of len() (PHP pattern)."""
    
    id = "php_strlen"
    severity = Severity.HIGH
    axis = Axis.QUALITY
    message = "PHP pattern: use len() instead of strlen()"
    
    def check_node(self, node: ast.AST, file, content) -> Optional[Issue]:
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                if node.func.id == "strlen":
                    return self.create_issue_from_node(
                        node,
                        file,
                        suggestion="Use Python's len() function"
                    )
        return None


class PHPArrayPushPattern(ASTPattern):
    """Detect array_push() instead of .append() (PHP pattern)."""
    
    id = "php_array_push"
    severity = Severity.HIGH
    axis = Axis.QUALITY
    message = "PHP pattern: use .append() instead of array_push()"
    
    def check_node(self, node: ast.AST, file, content) -> Optional[Issue]:
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                if node.func.id == "array_push":
                    return self.create_issue_from_node(
                        node,
                        file,
                        suggestion="Use Python's list.append() method"
                    )
        return None
