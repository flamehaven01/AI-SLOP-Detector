"""Question generation for reviewer UX."""

from __future__ import annotations

from typing import List

from slop_detector.models import FileAnalysis


class Question:
    """A review question about code quality."""

    def __init__(self, question: str, severity: str, line: int | None = None, context: str | None = None):
        self.question = question
        self.severity = severity  # "critical", "warning", "info"
        self.line = line
        self.context = context

    def __repr__(self):
        loc = f" (Line {self.line})" if self.line else ""
        return f"[{self.severity.upper()}]{loc} {self.question}"


class QuestionGenerator:
    """Generates contextual questions for code review."""

    def generate_questions(self, result: FileAnalysis) -> List[Question]:
        """Generate review questions based on analysis result."""
        questions = []

        # DDC questions (unused imports)
        questions.extend(self._generate_ddc_questions(result))

        # Inflation questions (jargon)
        questions.extend(self._generate_inflation_questions(result))

        # LDR questions (low logic density)
        questions.extend(self._generate_ldr_questions(result))

        # Docstring inflation questions (v2.2)
        questions.extend(self._generate_docstring_inflation_questions(result))

        # Hallucination dependencies questions (v2.2)
        questions.extend(self._generate_hallucination_deps_questions(result))

        # Context-based jargon questions (v2.2)
        questions.extend(self._generate_context_jargon_questions(result))

        # Pattern questions
        questions.extend(self._generate_pattern_questions(result))

        return questions

    def _generate_ddc_questions(self, result: FileAnalysis) -> List[Question]:
        """Generate questions about dependencies."""
        questions = []

        if not result.ddc.unused:
            return questions

        unused = result.ddc.unused
        if len(unused) == 1:
            questions.append(
                Question(
                    question=f"Why is '{unused[0]}' imported if it's never used?",
                    severity="warning",
                    context="unused_import"
                )
            )
        elif len(unused) <= 3:
            imports_str = "', '".join(unused)
            questions.append(
                Question(
                    question=f"Why are '{imports_str}' imported if they're never used?",
                    severity="warning",
                    context="unused_imports"
                )
            )
        else:
            questions.append(
                Question(
                    question=f"Why are {len(unused)} imports ({', '.join(unused[:3])}, ...) never used? "
                             f"Were they left over from AI code generation?",
                    severity="warning",
                    context="many_unused_imports"
                )
            )

        # If usage ratio is very low, ask about "hallucination dependencies"
        if result.ddc.usage_ratio < 0.3 and len(result.ddc.imported) > 5:
            questions.append(
                Question(
                    question=f"Only {result.ddc.usage_ratio:.0%} of imports are actually used. "
                             f"Did an AI generate these imports without understanding the code?",
                    severity="critical",
                    context="hallucination_dependencies"
                )
            )

        return questions

    def _generate_inflation_questions(self, result: FileAnalysis) -> List[Question]:
        """Generate questions about jargon/buzzwords."""
        questions = []

        if not result.inflation.jargon_details:
            return questions

        # Group jargon by line
        jargon_by_line = {}
        for jargon in result.inflation.jargon_details:
            line = jargon.get("line", 0)
            if line not in jargon_by_line:
                jargon_by_line[line] = []
            jargon_by_line[line].append(jargon)

        # Generate questions for each line with jargon
        for line, jargons in sorted(jargon_by_line.items())[:5]:  # Limit to 5 lines
            if len(jargons) == 1:
                jargon = jargons[0]
                word = jargon["word"]
                category = jargon["category"]

                questions.append(
                    Question(
                        question=f"What evidence supports the claim '{word}'? "
                                 f"Where are the {self._get_evidence_type(category)}?",
                        severity="warning",
                        line=line,
                        context=f"jargon_{category}"
                    )
                )
            else:
                words = "', '".join([j["word"] for j in jargons[:3]])
                questions.append(
                    Question(
                        question=f"Multiple buzzwords ('{words}') on this line. "
                                 f"What concrete evidence supports these claims?",
                        severity="warning",
                        line=line,
                        context="multiple_jargon"
                    )
                )

        # Overall inflation question
        if result.inflation.inflation_score > 1.5:
            questions.append(
                Question(
                    question=f"Jargon density is {result.inflation.inflation_score:.1f}x normal. "
                             f"Is this documentation or sales copy? Where's the actual code?",
                    severity="critical",
                    context="high_inflation"
                )
            )

        return questions

    def _generate_ldr_questions(self, result: FileAnalysis) -> List[Question]:
        """Generate questions about logic density."""
        questions = []

        if result.ldr.ldr_score < 0.3:
            empty_ratio = result.ldr.empty_lines / result.ldr.total_lines if result.ldr.total_lines > 0 else 0
            logic_ratio = result.ldr.logic_lines / result.ldr.total_lines if result.ldr.total_lines > 0 else 0

            if empty_ratio > 0.5:
                questions.append(
                    Question(
                        question=f"{empty_ratio:.0%} of this file is empty lines. "
                                 f"Is this intentional spacing or AI-generated fluff?",
                        severity="info",
                        context="excessive_empty_lines"
                    )
                )

            if logic_ratio < 0.3:
                questions.append(
                    Question(
                        question=f"Only {logic_ratio:.0%} of lines contain actual logic. "
                                 f"What's the purpose of the rest?",
                        severity="warning",
                        context="low_logic_density"
                    )
                )

        return questions

    def _generate_docstring_inflation_questions(self, result: FileAnalysis) -> List[Question]:
        """Generate questions about docstring inflation (v2.2)."""
        questions = []

        if not result.docstring_inflation:
            return questions

        doc_inflation = result.docstring_inflation

        # Check for individual inflated docstrings
        for detail in doc_inflation.details[:5]:  # Limit to top 5
            if detail.severity == "critical":
                questions.append(
                    Question(
                        question=f"Function '{detail.name}' has {detail.docstring_lines} lines of docstring "
                        f"but only {detail.implementation_lines} lines of implementation. "
                        f"Is this AI-generated documentation without substance?",
                        severity="critical",
                        line=detail.line,
                        context="docstring_inflation_critical",
                    )
                )
            elif detail.severity == "warning":
                questions.append(
                    Question(
                        question=f"'{detail.name}' has more documentation ({detail.docstring_lines} lines) "
                        f"than implementation ({detail.implementation_lines} lines). "
                        f"Does the code actually do what the docstring claims?",
                        severity="warning",
                        line=detail.line,
                        context="docstring_inflation_warning",
                    )
                )

        # Overall file inflation
        if doc_inflation.status == "FAIL":
            questions.append(
                Question(
                    question=f"This file has {doc_inflation.total_docstring_lines} lines of docstrings "
                    f"but only {doc_inflation.total_implementation_lines} lines of implementation "
                    f"(ratio: {doc_inflation.overall_ratio:.1f}). "
                    f"Is this AI-generated boilerplate with minimal actual logic?",
                    severity="critical",
                    context="file_docstring_inflation",
                )
            )
        elif doc_inflation.status == "WARNING" and doc_inflation.inflated_count > 0:
            questions.append(
                Question(
                    question=f"{doc_inflation.inflated_count} functions/classes have inflated docstrings. "
                    f"Were these docstrings auto-generated without verifying they match the implementation?",
                    severity="warning",
                    context="multiple_docstring_inflation",
                )
            )

        return questions

    def _generate_hallucination_deps_questions(self, result: FileAnalysis) -> List[Question]:
        """Generate questions about hallucinated dependencies (v2.2)."""
        questions = []

        if not result.hallucination_deps:
            return questions

        hal_deps = result.hallucination_deps

        # Critical: Multiple hallucinated deps in same category
        if hal_deps.total_hallucinated >= 5:
            questions.append(
                Question(
                    question=f"{hal_deps.total_hallucinated} unused purpose-specific imports detected. "
                    f"Did an AI generate these imports without implementing the actual functionality?",
                    severity="critical",
                    context="massive_hallucination",
                )
            )

        # Category-specific questions
        for category_usage in hal_deps.category_usage:
            if category_usage.unused and category_usage.usage_ratio < 0.5:
                unused_str = "', '".join(category_usage.unused[:3])
                questions.append(
                    Question(
                        question=f"Category '{category_usage.category}': Imported '{unused_str}' "
                        f"but never used. Was {category_usage.unused[0]} intended for "
                        f"{hal_deps.hallucinated_deps[0].likely_intent if hal_deps.hallucinated_deps else 'specific functionality'}?",
                        severity="warning",
                        context=f"category_{category_usage.category}",
                    )
                )

        # Individual hallucinated deps
        for hal_dep in hal_deps.hallucinated_deps[:5]:  # Top 5
            questions.append(
                Question(
                    question=f"Why import '{hal_dep.library}' for {hal_dep.likely_intent} "
                    f"but never use it? Was this AI-generated boilerplate?",
                    severity="warning",
                    line=hal_dep.line,
                    context=f"hallucinated_{hal_dep.category}",
                )
            )

        return questions

    def _generate_context_jargon_questions(self, result: FileAnalysis) -> List[Question]:
        """Generate questions about context-based jargon validation (v2.2)."""
        questions = []

        if not result.context_jargon:
            return questions

        ctx_jargon = result.context_jargon

        # Critical: Low justification ratio
        if ctx_jargon.justification_ratio < 0.3:
            questions.append(
                Question(
                    question=f"Only {ctx_jargon.justification_ratio:.0%} of quality claims are backed by evidence. "
                    f"Are these marketing buzzwords without substance?",
                    severity="critical",
                    context="low_justification_ratio",
                )
            )

        # Worst offenders (0 evidence)
        if ctx_jargon.worst_offenders:
            offenders_str = "', '".join(ctx_jargon.worst_offenders[:3])
            questions.append(
                Question(
                    question=f"Claims like '{offenders_str}' have ZERO supporting evidence. "
                    f"Where are the tests, error handling, and other indicators?",
                    severity="critical",
                    context="zero_evidence",
                )
            )

        # Individual unjustified jargon
        for evidence in ctx_jargon.evidence_details[:5]:  # Top 5
            if not evidence.is_justified and evidence.evidence_ratio < 0.3:
                missing_str = ", ".join(evidence.missing_evidence[:3])
                questions.append(
                    Question(
                        question=f"'{evidence.jargon}' claim at line {evidence.line} lacks: {missing_str}. "
                        f"Only {evidence.evidence_ratio:.0%} of required evidence present.",
                        severity="warning",
                        line=evidence.line,
                        context=f"unjustified_{evidence.jargon}",
                    )
                )

        return questions

    def _generate_pattern_questions(self, result: FileAnalysis) -> List[Question]:
        """Generate questions about detected patterns."""
        questions = []

        for issue in result.pattern_issues[:10]:  # Limit to 10 patterns
            severity_map = {
                "critical": "critical",
                "high": "warning",
                "medium": "info",
                "low": "info"
            }

            # Convert pattern to question
            question_text = self._pattern_to_question(issue)
            if question_text:
                # Issue is a dataclass, access attributes directly
                severity_val = issue.severity.value if hasattr(issue.severity, 'value') else str(issue.severity)
                questions.append(
                    Question(
                        question=question_text,
                        severity=severity_map.get(severity_val, "info"),
                        line=issue.line,
                        context=f"pattern_{issue.pattern_id}"
                    )
                )

        return questions

    def _pattern_to_question(self, issue) -> str | None:
        """Convert a pattern issue to a review question."""
        # Issue is a dataclass with attributes, not a dict
        pattern_id = issue.pattern_id

        # Map patterns to questions
        question_map = {
            "empty_except": "Why is this exception handler empty? What errors are being silently ignored?",
            "not_implemented": "Is this intentionally unimplemented, or was it forgotten?",
            "pass_placeholder": "Is this placeholder function still needed, or should it be removed?",
            "ellipsis_placeholder": "What should this function actually do?",
            "return_none_placeholder": "Should this function return something meaningful instead of None?",
            "todo_comment": "When will this TODO be addressed? Is there a ticket for it?",
            "fixme_comment": "What needs to be fixed here? Is there a ticket tracking this?",
            "hack_comment": "What's the proper solution to replace this hack?",
            "interface_only_class": "Should this be an Abstract Base Class (ABC) instead?",
            "bare_except": "What specific exceptions should be caught here?",
            "mutable_default_arg": "Is this mutable default argument intentional? It can cause bugs.",
            "star_import": "Which specific imports are actually needed from this module?",
        }

        return question_map.get(pattern_id)

    def _get_evidence_type(self, category: str) -> str:
        """Get the type of evidence needed for a jargon category."""
        evidence_map = {
            "quality": "tests, benchmarks, or quality metrics",
            "architecture": "architecture diagrams, design docs, or code structure",
            "performance": "benchmarks, profiling results, or performance tests",
            "security": "security audits, penetration tests, or compliance certs",
            "scale": "load tests, capacity planning, or production metrics"
        }
        return evidence_map.get(category, "supporting evidence")

    def format_questions_text(self, questions: List[Question]) -> str:
        """Format questions as text output."""
        if not questions:
            return ""

        lines = ["", "=" * 80, "REVIEW QUESTIONS", "=" * 80, ""]

        critical = [q for q in questions if q.severity == "critical"]
        warnings = [q for q in questions if q.severity == "warning"]
        info = [q for q in questions if q.severity == "info"]

        if critical:
            lines.append("CRITICAL QUESTIONS:")
            lines.append("-" * 80)
            for i, q in enumerate(critical, 1):
                loc = f" (Line {q.line})" if q.line else ""
                lines.append(f"{i}.{loc} {q.question}")
            lines.append("")

        if warnings:
            lines.append("WARNING QUESTIONS:")
            lines.append("-" * 80)
            for i, q in enumerate(warnings, 1):
                loc = f" (Line {q.line})" if q.line else ""
                lines.append(f"{i}.{loc} {q.question}")
            lines.append("")

        if info:
            lines.append("INFO QUESTIONS:")
            lines.append("-" * 80)
            for i, q in enumerate(info, 1):
                loc = f" (Line {q.line})" if q.line else ""
                lines.append(f"{i}.{loc} {q.question}")
            lines.append("")

        lines.append("=" * 80)
        return "\n".join(lines)
