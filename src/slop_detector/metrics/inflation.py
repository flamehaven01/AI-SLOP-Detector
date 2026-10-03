"""Buzzword-to-Code Ratio (BCR) calculator with context awareness."""

import ast
import io
import logging
import re
import tokenize
from pathlib import Path
from typing import Dict, List, Mapping, Optional, Sequence, Set, Tuple

from slop_detector.models import InflationResult

logger = logging.getLogger(__name__)

# Token types whose text is prose (a place a claim can be written). Python 3.12+
# splits f-strings (and 3.14 t-strings) into START/MIDDLE/END tokens.
_PROSE_TOKENS = frozenset(
    t
    for t in (
        tokenize.COMMENT,
        tokenize.STRING,
        getattr(tokenize, "FSTRING_MIDDLE", None),
        getattr(tokenize, "TSTRING_MIDDLE", None),
    )
    if t is not None
)

Spans = Dict[int, List[Tuple[int, int]]]

# Strong legal markers (matched case-insensitively, whitespace-normalized). The
# bare words "license" or "copyright" are not markers.
_LEGAL_MARKERS = tuple(
    marker.casefold()
    for marker in (
        "SPDX-License-Identifier:",
        "Copyright (c)",
        "Copyright \u00a9",
        "Licensed under the Apache License",
        "Permission is hereby granted",
        "General Public License",
        "Mozilla Public License",
        "Redistribution and use in source and binary forms",
    )
)
# License-notice wording that makes the NEXT paragraph part of the same notice
# (case-sensitive; only right after a legal paragraph).
_LEGAL_CONTINUATION = ("the License", "WARRANTY", "WARRANTIES", "applicable law", "licenses/")


def _legal_rows(tokens: List[tokenize.TokenInfo]) -> Set[int]:
    """Rows of legal paragraphs in the leading comments (claim-source boundary A2).

    Leading comments end at the first code token; a shebang or encoding cookie is
    a comment and does not end them. Paragraphs are separated by blank lines. A
    paragraph is legal when it carries a strong marker, or when it directly
    follows a legal paragraph and continues the notice.
    """
    paragraphs: List[List[tokenize.TokenInfo]] = []
    for tok in tokens:
        if tok.type == tokenize.COMMENT:
            if paragraphs and tok.start[0] == paragraphs[-1][-1].start[0] + 1:
                paragraphs[-1].append(tok)
            else:
                paragraphs.append([tok])
        elif tok.type not in (tokenize.NL, tokenize.NEWLINE, tokenize.ENCODING):
            break
    rows: Set[int] = set()
    previous_legal = False
    for paragraph in paragraphs:
        text = " ".join(" ".join(tok.string.lstrip("#") for tok in paragraph).split())
        legal = any(marker in text.casefold() for marker in _LEGAL_MARKERS) or (
            previous_legal and any(word in text for word in _LEGAL_CONTINUATION)
        )
        if legal:
            rows.update(tok.start[0] for tok in paragraph)
        previous_legal = legal
    return rows


def _prose_spans(content: str) -> Optional[Spans]:
    """Line -> column ranges covered by comments and string literals.

    A jargon word only counts as a claim inside prose; in an import path,
    attribute path, or identifier it is code. Legal paragraphs in the leading
    comments are not claims either (_legal_rows). None when the source cannot be
    tokenized, in which case every match counts (the previous behaviour).
    """
    spans: Spans = {}
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(content).readline))
    except (tokenize.TokenError, IndentationError, SyntaxError):
        return None
    lines = content.splitlines()
    legal = _legal_rows(tokens)
    for tok in tokens:
        if tok.type not in _PROSE_TOKENS:
            continue
        if tok.type == tokenize.COMMENT and tok.start[0] in legal:
            continue
        (start_row, start_col), (end_row, end_col) = tok.start, tok.end
        for row in range(start_row, end_row + 1):
            width = len(lines[row - 1]) if row - 1 < len(lines) else 0
            first = start_col if row == start_row else 0
            last = end_col if row == end_row else width
            spans.setdefault(row, []).append((first, last))
    return spans


def _in_prose(spans: Optional[Spans], row: int, start: int, end: int) -> bool:
    if spans is None:
        return True
    return any(first <= start and end <= last for first, last in spans.get(row, ()))


# Decorators that are structural evidence of caching (and justify quality jargon).
CACHE_DECORATORS = frozenset({"cache", "lru_cache"})


def _import_aliases(tree: ast.AST) -> Dict[str, str]:
    """Local name -> top-level module, for every absolute import in the file."""
    aliases: Dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                top = alias.name.split(".")[0]
                aliases[alias.asname or top] = top
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            top = node.module.split(".")[0]
            for alias in node.names:
                aliases[alias.asname or alias.name] = top
    return aliases


def cache_decorator_lines(tree: ast.AST) -> Set[int]:
    """Lines of `@cache` / `@lru_cache` decorators (bare, called, or qualified)."""
    lines: Set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            for decorator in node.decorator_list:
                target = decorator.func if isinstance(decorator, ast.Call) else decorator
                name = target.id if isinstance(target, ast.Name) else getattr(target, "attr", "")
                if name in CACHE_DECORATORS:
                    lines.add(decorator.lineno)
    return lines


def justifier_lines(tree: ast.AST, modules: Mapping[str, Sequence[str]]) -> Dict[str, Set[int]]:
    """Per category, the lines where code structurally uses a justifying library.

    A library counts where the code references a name imported from it (aliases
    included: `import torch as T` ... `T.nn`). Quality is also justified by cache
    decorators and `.vectorize`. Comments, strings, identifier names, and the
    claim word itself are never evidence.
    """
    aliases = _import_aliases(tree)
    category_of = {module: category for category, mods in modules.items() for module in mods}
    found: Dict[str, Set[int]] = {category: set() for category in modules}
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            category = category_of.get(aliases.get(node.id, ""))
            if category:
                found[category].add(node.lineno)
        elif isinstance(node, ast.Attribute) and node.attr == "vectorize" and "quality" in found:
            found["quality"].add(node.lineno)
    if "quality" in found:
        found["quality"] |= cache_decorator_lines(tree)
    return found


try:
    from radon.complexity import cc_visit

    RADON_AVAILABLE = True
except ImportError:
    RADON_AVAILABLE = False


class InflationCalculator:
    """Calculate Inflation (formerly BCR) with context-aware jargon detection."""

    JARGON = {
        # AI/ML jargon
        "ai_ml": [
            "neural",
            "deep learning",
            "transformer",
            "attention mechanism",
            "reinforcement learning",
            "policy optimization",
            "gradient descent",
            "latent space",
            "embedding",
            "semantic reasoning",
        ],
        # Architecture jargon
        "architecture": [
            "byzantine",
            "fault-tolerant",
            "fault tolerant",
            "distributed",
            "scalable",
            "enterprise-grade",
            "enterprise grade",
            "production-ready",
            "production ready",
            "mission-critical",
            "mission critical",
            "cloud-native",
            "cloud native",
            "microservices",
            "serverless",
        ],
        # Quality jargon
        "quality": [
            "robust",
            "resilient",
            "performant",
            "optimized",
            "optimization",
            "state-of-the-art",
            "cutting-edge",
            "advanced algorithm",
            "sophisticated",
            "comprehensive",
            "holistic",
        ],
        # Paper references (venue/publication names only — math terms like proof/lemma/theorem
        # are primary domain vocabulary in formal-methods and governance code, not slop signals)
        "academic": [
            "neurips",
            "iclr",
            "icml",
            "cvpr",
            "equation",
            "spotlight",
        ],
    }

    # Libraries that justify jargon where the code uses them (justifier_lines).
    # Quality is also justified by cache decorators and `.vectorize` calls.
    JUSTIFICATIONS = {
        "ai_ml": ["torch", "tensorflow", "keras", "jax", "transformers"],
        "architecture": ["multiprocessing", "concurrent", "asyncio"],
        "quality": ["numba", "cython"],
    }

    def __init__(self, config):
        """Initialize with config."""
        self.config = config
        self.use_radon = config.use_radon() and RADON_AVAILABLE

    def calculate(self, file_path: str, content: str, tree: ast.AST) -> InflationResult:
        """Calculate Inflation with context awareness (v2.8.0 TOE formula)."""
        lines = content.splitlines()
        logic_lines = sum(1 for ln in lines if ln.strip() and not ln.strip().startswith("#"))
        avg_complexity = self._calculate_avg_complexity(content, tree)
        is_config_file = self._is_config_file(file_path, tree)

        jargon_found, justified_jargon, jargon_details = self._scan_jargon(content, lines, tree)
        effective_jargon = max(0, len(jargon_found) - len(justified_jargon))
        inflation_score = self._compute_inflation_score(
            effective_jargon, logic_lines, avg_complexity, is_config_file
        )
        status = (
            "FAIL" if inflation_score > 1.0 else ("WARNING" if inflation_score > 0.5 else "PASS")
        )

        return InflationResult(
            jargon_count=len(jargon_found),
            avg_complexity=avg_complexity,
            inflation_score=inflation_score,
            status=status,
            jargon_found=jargon_found,
            jargon_details=jargon_details,
            justified_jargon=justified_jargon,
            is_config_file=is_config_file,
        )

    def _scan_jargon(self, content: str, lines: list, tree: ast.AST):
        """Scan all lines for jargon hits, returning (found, justified, details)."""
        jargon_found = []
        justified_jargon = []
        jargon_details = []
        func_scopes = self._build_function_scopes(tree, lines)
        # Tokenized at most once per file, and only once a jargon candidate is
        # found: most files have none, and tokenizing them dominated the cost.
        prose: Optional[Spans] = None
        justifiers: Dict[str, Set[int]] = {}
        tokenized = False

        for line_idx, line in enumerate(lines, 1):
            if self._is_data_literal_entry(line):
                continue
            line_lower = line.lower()
            for category, words in self.JARGON.items():
                for word in words:
                    pattern = r"\b" + re.escape(word.lower()) + r"\b"
                    for match in re.finditer(pattern, line_lower):
                        if not tokenized:
                            prose, tokenized = _prose_spans(content), True
                            justifiers = justifier_lines(tree, self.JUSTIFICATIONS)
                        if not _in_prose(prose, line_idx, match.start(), match.end()):
                            continue  # import path, attribute, or identifier: code, not a claim
                        jargon_found.append(word)
                        is_justified = self._is_jargon_justified_scoped(
                            category, line_idx, func_scopes, justifiers
                        )
                        if is_justified:
                            justified_jargon.append(word)
                        jargon_details.append(
                            {
                                "word": word,
                                "line": line_idx,
                                "category": category,
                                "justified": is_justified,
                            }
                        )
        return jargon_found, justified_jargon, jargon_details

    @staticmethod
    def _is_data_literal_entry(line: str) -> bool:
        """Return True for standalone quoted literals inside list-like vocab tables."""
        stripped = line.strip()
        return bool(re.fullmatch(r"[rubfRUBF]{0,2}([\"\']).*?\1,?", stripped))

    # Minimum denominator for jargon density: prevents single hits in tiny files
    # (e.g. a 7-line constants file) from producing disproportionately high scores.
    # Derived from the observation that files below this size produce unreliable
    # density signals — one hit in 7 lines scores the same as 2 hits in 14 lines.
    _MIN_DENSITY_LINES = 15

    def _compute_inflation_score(
        self, effective_jargon: int, logic_lines: int, avg_complexity: float, is_config_file: bool
    ) -> float:
        """Compute final inflation score using v2.8.0 density × complexity formula."""
        if is_config_file and self.config.is_config_file_exception_enabled():
            return 0.0
        if logic_lines == 0:
            # No logic lines: cap at max rather than using inf (which is invalid JSON).
            # A jargon-only file (no logic) is maximally inflated.
            return 10.0 if effective_jargon > 0 else 0.0
        effective_lines = max(logic_lines, self._MIN_DENSITY_LINES)
        jargon_density = effective_jargon / effective_lines
        # complexity_modifier >= 1.0: complex code pays premium for jargon.
        # Baseline cc=1.0 (simplest possible function); cc=3 was a free zone where
        # jargon carried no complexity penalty — corrected to cc=1 minimum.
        complexity_modifier = max(1.0, 1.0 + (avg_complexity - 1.0) / 10.0)
        return min(jargon_density * complexity_modifier * 10.0, 10.0)

    def _calculate_avg_complexity(self, content: str, tree: ast.AST) -> float:
        """Calculate average cyclomatic complexity using radon if available."""
        if self.use_radon:
            avg: float = 1.0  # safe default if radon fails
            try:
                results = cc_visit(content)
                if results:
                    avg = sum(r.complexity for r in results) / len(results)
            except Exception as exc:  # noqa: BLE001 — radon parse errors are unpredictable
                logger.debug("radon cc_visit failed, using default complexity=1.0: %s", exc)
            return avg

        # Fallback: simple AST-based complexity
        function_count = 0
        total_complexity = 0

        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                function_count += 1
                complexity = 1
                for child in ast.walk(node):
                    if isinstance(child, (ast.If, ast.For, ast.While, ast.ExceptHandler)):
                        complexity += 1
                    elif isinstance(child, ast.BoolOp):
                        complexity += len(child.values) - 1
                total_complexity += complexity

        return total_complexity / function_count if function_count > 0 else 1.0

    def _build_function_scopes(self, tree: ast.AST, lines: list) -> dict:
        """Build mapping of line_number -> (func_start, func_end) for each line.

        v2.8.0: Enables function-scoped justification check.
        Returns dict: line_idx (1-based) -> (start_line, end_line) or None.
        """
        # Collect all function ranges (include decorator lines in scope start)
        func_ranges = []
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                end = getattr(node, "end_lineno", node.lineno + 1)
                # Extend start to first decorator so @lru_cache etc. are in scope
                if node.decorator_list:
                    true_start = min(d.lineno for d in node.decorator_list)
                else:
                    true_start = node.lineno
                func_ranges.append((true_start, end))

        # Sort by start so inner functions are found after outer
        func_ranges.sort()

        # For each line, find the innermost enclosing function
        n_lines = len(lines)
        scope_map = {}
        for line_idx in range(1, n_lines + 1):
            enclosing = None
            for start, end in func_ranges:
                if start <= line_idx <= end:
                    # Prefer innermost (latest start that still contains the line)
                    if enclosing is None or start > enclosing[0]:
                        enclosing = (start, end)
            scope_map[line_idx] = enclosing
        return scope_map

    def _is_jargon_justified_scoped(
        self,
        category: str,
        line_idx: int,
        func_scopes: dict,
        justifiers: Mapping[str, Set[int]],
    ) -> bool:
        """Check if jargon is justified by structural use within its scope.

        v2.8.0: Function-scoped justification (TOE: measure at minimum relevant scope).
        - If jargon is inside a function: the library must be used in that function
        - If jargon is module-level: the library may be used anywhere in the file
        """
        lines = justifiers.get(category, set())
        scope = func_scopes.get(line_idx)
        if scope is None:
            return bool(lines)
        start, end = scope
        return any(start <= line <= end for line in lines)

    def _is_jargon_justified(self, category: str, word: str, content: str) -> bool:
        """Legacy file-scoped justification (kept for external callers)."""
        if category not in self.JUSTIFICATIONS:
            return False
        try:
            tree = ast.parse(content)
        except SyntaxError:
            return False
        return bool(justifier_lines(tree, self.JUSTIFICATIONS)[category])

    def _is_config_file(self, file_path: str, tree: ast.AST) -> bool:
        """Check if file is a configuration file."""
        # Check filename patterns
        config_patterns = self.config.get("exceptions.config_files.patterns", [])
        for pattern in config_patterns:
            if Path(file_path).match(pattern):
                # Verify no functions
                function_count = sum(
                    1
                    for node in ast.walk(tree)
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                )
                return function_count == 0

        return False
