"""Hallucination Dependencies Detector - Detects unused purpose-specific imports."""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from typing import Any, Dict, List, Set


@dataclass
class CategoryUsage:
    """Track usage of a specific import category."""

    category: str
    imported: List[str]
    used: List[str]
    unused: List[str]
    usage_ratio: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "category": self.category,
            "imported": self.imported,
            "used": self.used,
            "unused": self.unused,
            "usage_ratio": self.usage_ratio,
        }


@dataclass
class HallucinatedDependency:
    """A dependency that was imported but never used."""

    library: str
    category: str
    line: int
    likely_intent: str  # What the AI probably intended to do

    def to_dict(self) -> Dict[str, Any]:
        return {
            "library": self.library,
            "category": self.category,
            "line": self.line,
            "likely_intent": self.likely_intent,
        }


@dataclass
class HallucinationDepsResult:
    """Result of hallucination dependency analysis."""

    total_hallucinated: int
    category_usage: List[CategoryUsage]
    hallucinated_deps: List[HallucinatedDependency]
    worst_category: str  # Category with most unused imports
    status: str  # "PASS", "WARNING", "CRITICAL"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_hallucinated": self.total_hallucinated,
            "category_usage": [c.to_dict() for c in self.category_usage],
            "hallucinated_deps": [h.to_dict() for h in self.hallucinated_deps],
            "worst_category": self.worst_category,
            "status": self.status,
        }


class HallucinationDepsDetector:
    """Detect when AI hallucinates dependencies for specific purposes without using them."""

    def __init__(self, config):
        """Initialize detector."""
        self.config = config
        self._load_known_deps()

        # Build reverse map: library -> categories
        self.lib_to_categories: Dict[str, Set[str]] = {}
        for category, libs in self.CATEGORY_MAP.items():
            for lib in libs:
                if lib not in self.lib_to_categories:
                    self.lib_to_categories[lib] = set()
                self.lib_to_categories[lib].add(category)

    def _load_known_deps(self):
        """Load known dependencies from yaml config."""
        import yaml
        from pathlib import Path

        # Default fallback (if yaml load fails)
        self.CATEGORY_MAP = {}
        self.INTENT_PATTERNS = {}

        try:
            # Try to load from config dir relative to this file
            current_dir = Path(__file__).parent.parent
            config_path = current_dir / "config" / "known_deps.yaml"
            
            if config_path.exists():
                with open(config_path, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f)
                    self.CATEGORY_MAP = {k: set(v) for k, v in data.get("categories", {}).items()}
                    self.INTENT_PATTERNS = data.get("intent_patterns", {})
            else:
                # If file not found, we could warn, but for now we'll just use empty or raise
                # In a real app we might want hardcoded fallbacks here just in case
                pass
        except Exception:
            # Fallback or empty if error
            pass

    def analyze(
        self, file_path: str, content: str, tree: ast.AST, ddc_result: Any
    ) -> HallucinationDepsResult:
        """Analyze for hallucinated dependencies."""
        # Get unused imports from DDC
        unused_imports = set(ddc_result.unused)

        # Categorize unused imports
        category_stats: Dict[str, Dict[str, Set[str]]] = {}
        hallucinated_deps: List[HallucinatedDependency] = []

        # Initialize category stats
        for category in self.CATEGORY_MAP.keys():
            category_stats[category] = {"imported": set(), "used": set(), "unused": set()}

        # Categorize all imports
        import_lines = self._collect_import_lines(tree)

        for lib in ddc_result.imported:
            categories = self.lib_to_categories.get(lib, set())
            for category in categories:
                category_stats[category]["imported"].add(lib)

                if lib in unused_imports:
                    category_stats[category]["unused"].add(lib)

                    # Create hallucinated dependency entry
                    line = import_lines.get(lib, 0)
                    hallucinated_deps.append(
                        HallucinatedDependency(
                            library=lib,
                            category=category,
                            line=line,
                            likely_intent=self.INTENT_PATTERNS.get(
                                category, "specific functionality"
                            ),
                        )
                    )
                else:
                    category_stats[category]["used"].add(lib)

        # Build category usage results
        category_usage = []
        max_unused = 0
        worst_category = "none"

        for category, stats in category_stats.items():
            if not stats["imported"]:
                continue  # Skip empty categories

            imported_list = sorted(list(stats["imported"]))
            used_list = sorted(list(stats["used"]))
            unused_list = sorted(list(stats["unused"]))
            usage_ratio = len(used_list) / len(imported_list) if imported_list else 1.0

            category_usage.append(
                CategoryUsage(
                    category=category,
                    imported=imported_list,
                    used=used_list,
                    unused=unused_list,
                    usage_ratio=usage_ratio,
                )
            )

            # Track worst category
            if len(unused_list) > max_unused:
                max_unused = len(unused_list)
                worst_category = category

        # Determine status
        total_hallucinated = len(hallucinated_deps)
        if total_hallucinated >= 5:
            status = "CRITICAL"
        elif total_hallucinated >= 3:
            status = "WARNING"
        else:
            status = "PASS"

        return HallucinationDepsResult(
            total_hallucinated=total_hallucinated,
            category_usage=sorted(category_usage, key=lambda c: c.usage_ratio),
            hallucinated_deps=hallucinated_deps[:10],  # Top 10
            worst_category=worst_category,
            status=status,
        )

    def _collect_import_lines(self, tree: ast.AST) -> Dict[str, int]:
        """Collect line numbers for each import."""
        import_lines = {}

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    lib_name = alias.name.split(".")[0]
                    import_lines[lib_name] = node.lineno
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    lib_name = node.module.split(".")[0]
                    import_lines[lib_name] = node.lineno

        return import_lines
