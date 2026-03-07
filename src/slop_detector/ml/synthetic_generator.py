"""
Synthetic Code Generator (v2.8.0)

Generates labeled Python code samples for ML training.
Produces generate_slop_file() / generate_clean_file() for MLPipeline.

Slop characteristics:
  - Low LDR: empty/placeholder functions (pass, ..., TODO)
  - High inflation: jargon-heavy docstrings without real code
  - Low DDC: unused imports (torch, tensorflow, keras imported but unused)
  - Anti-patterns: bare_except, mutable_default_arg, cross-language, dead code
  - God functions: many branches, deep nesting
  - Dead code: unreachable statements after return

Clean characteristics:
  - High LDR: real logic lines, meaningful computation
  - Low inflation: no jargon or justified by actual library usage
  - High DDC: all imports are used
  - No anti-patterns
  - Small focused functions, shallow nesting
"""

import random
import textwrap
from pathlib import Path
from typing import List

# ------------------------------------------------------------------
# Jargon vocabulary (for inflation in slop files)
# ------------------------------------------------------------------

_JARGON_POOL = [
    "neural",
    "transformer",
    "deep learning",
    "embedding",
    "semantic reasoning",
    "Byzantine",
    "fault-tolerant",
    "enterprise-grade",
    "production-ready",
    "mission-critical",
    "cloud-native",
    "microservices",
    "serverless",
    "robust",
    "resilient",
    "performant",
    "optimized",
    "sophisticated",
    "comprehensive",
    "holistic",
    "state-of-the-art",
    "cutting-edge",
    "advanced algorithm",
    "scalable",
    "distributed",
]

# ------------------------------------------------------------------
# Cross-language mistakes
# ------------------------------------------------------------------

_CROSS_LANG_MISTAKES = [
    "items.push(item)  # js idiom",
    "n = items.length  # js idiom",
    "ok = text.equals(other)  # java idiom",
    "empty = lst.isEmpty()  # java idiom",
    "# array.each { |x| process(x) }  # ruby",
]

# ------------------------------------------------------------------
# Clean function templates (diverse, realistic)
# ------------------------------------------------------------------

_CLEAN_FUNCTIONS = [
    # Simple math utility
    """def clamp(value: float, lo: float, hi: float) -> float:
    if value < lo:
        return lo
    if value > hi:
        return hi
    return value
""",
    # List processing
    """def deduplicate(items: list) -> list:
    seen = set()
    result = []
    for item in items:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result
""",
    # String utility
    """def truncate(text: str, max_len: int, suffix: str = "...") -> str:
    if len(text) <= max_len:
        return text
    return text[: max_len - len(suffix)] + suffix
""",
    # Dict merge
    """def merge_dicts(base: dict, override: dict) -> dict:
    result = dict(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = merge_dicts(result[key], value)
        else:
            result[key] = value
    return result
""",
    # File reading
    """def read_lines(path: str) -> list:
    with open(path, "r", encoding="utf-8") as f:
        return [line.rstrip("\\n") for line in f]
""",
    # Chunking
    """def chunk(items: list, size: int) -> list:
    return [items[i : i + size] for i in range(0, len(items), size)]
""",
    # Retry logic
    """def retry(fn, attempts: int = 3, default=None):
    for i in range(attempts):
        try:
            return fn()
        except Exception:
            if i == attempts - 1:
                return default
    return default
""",
    # Flatten nested list
    """def flatten(nested: list) -> list:
    result = []
    for item in nested:
        if isinstance(item, list):
            result.extend(flatten(item))
        else:
            result.append(item)
    return result
""",
    # Safe dict get
    """def deep_get(d: dict, *keys, default=None):
    current = d
    for key in keys:
        if not isinstance(current, dict):
            return default
        current = current.get(key, default)
        if current is default:
            return default
    return current
""",
    # Simple counter
    """def count_by(items: list, key_fn) -> dict:
    counts = {}
    for item in items:
        k = key_fn(item)
        counts[k] = counts.get(k, 0) + 1
    return counts
""",
    # Moving average
    """def moving_average(values: list, window: int) -> list:
    if window < 1 or not values:
        return []
    result = []
    for i in range(len(values)):
        start = max(0, i - window + 1)
        window_vals = values[start : i + 1]
        result.append(sum(window_vals) / len(window_vals))
    return result
""",
    # Normalize scores
    """def normalize(values: list) -> list:
    if not values:
        return []
    lo = min(values)
    hi = max(values)
    span = hi - lo
    if span == 0:
        return [0.5] * len(values)
    return [(v - lo) / span for v in values]
""",
]

# ------------------------------------------------------------------
# Slop patterns to inject
# ------------------------------------------------------------------

_SLOP_EMPTY_FN_TEMPLATES = [
    'def {name}({params}):\n    """{doc}"""\n    pass\n',
    'def {name}({params}):\n    """{doc}"""\n    ...\n',
    'def {name}({params}):\n    """{doc}"""\n    # TODO: implement\n    return None\n',
    'def {name}({params}):\n    """{doc}"""\n    raise NotImplementedError("not implemented")\n',
]

_SLOP_GOD_FN_TEMPLATE = '''def process_all_{suffix}(data, config, opts, extra, flags):
    """
    Advanced {jargon1} {jargon2} processing function.
    Uses {jargon3} algorithms for {jargon4} performance.
    """
    result = []
    if data:
        if config:
            if opts:
                for item in data:
                    if item:
                        if flags:
                            if "key" in item:
                                if item["key"] > 0:
                                    result.append(item)
                                elif item["key"] < 0:
                                    result.append(None)
                        elif extra:
                            for subitem in item:
                                if subitem:
                                    result.append(subitem)
    elif config:
        while len(result) < 10:
            result.append(0)
    return result
    print("done processing")
'''

_SLOP_BARE_EXCEPT = '''def risky_{suffix}():
    """Byzantine fault-tolerant operation."""
    try:
        result = do_something()
        return result
    except:
        pass
'''

_SLOP_DEAD_CODE = '''def compute_{suffix}(x, y):
    """Robust computation."""
    if x > 0:
        return x + y
    return x - y
    print("unreachable")
    x = x * 2
'''

_SLOP_MUTABLE_DEFAULT = '''def accumulate_{suffix}(item, items=[]):
    """Optimized accumulator."""
    items.append(item)
    return items
'''


class SyntheticGenerator:
    """
    Generate labeled synthetic Python code samples for ML training.

    v2.8.0: Provides generate_slop_file() and generate_clean_file()
    as expected by MLPipeline. Diverse templates ensure good feature
    coverage across LDR, inflation, DDC, and pattern dimensions.
    """

    def __init__(self, seed: int = 42):
        self._rng = random.Random(seed)

    # ------------------------------------------------------------------
    # Pipeline interface (used by MLPipeline)
    # ------------------------------------------------------------------

    def generate_slop_file(self) -> str:
        """Generate a realistic slop Python file as a string.

        Combines multiple anti-patterns with randomized intensity so
        the training set covers the full feature space.
        """
        parts: List[str] = []

        # 1. Jargon module docstring
        jargon = self._rng.sample(_JARGON_POOL, 5)
        parts.append(
            f'"""\n{jargon[0].capitalize()} {jargon[1]} system.\n'
            f"Implements {jargon[2]} {jargon[3]} architecture\n"
            f'with {jargon[4]} processing.\n"""\n'
        )

        # 2. Unused imports (DDC violation)
        n_unused = self._rng.randint(2, 5)
        unused_pool = [
            "import torch",
            "import tensorflow as tf",
            "import keras",
            "import numpy as np",
            "import pandas as pd",
            "from sklearn.ensemble import RandomForestClassifier",
        ]
        for imp in self._rng.sample(unused_pool, min(n_unused, len(unused_pool))):
            parts.append(imp)
        parts.append("")

        # 3. Empty / placeholder functions
        n_empty = self._rng.randint(3, 7)
        for i in range(n_empty):
            jargon2 = self._rng.sample(_JARGON_POOL, 4)
            doc = (
                f"{jargon2[0].capitalize()} {jargon2[1]} function. "
                f"Uses {jargon2[2]} for {jargon2[3]} performance."
            )
            params = self._rng.choice(["", "data", "data=[]", "config={}", "items, opts={}"])
            tmpl = self._rng.choice(_SLOP_EMPTY_FN_TEMPLATES)
            parts.append(tmpl.format(name=f"func_{i}", params=params, doc=doc))

        # 4. God function (always present in slop)
        suffix = self._rng.randint(1000, 9999)
        j = self._rng.sample(_JARGON_POOL, 4)
        parts.append(
            _SLOP_GOD_FN_TEMPLATE.format(
                suffix=suffix, jargon1=j[0], jargon2=j[1], jargon3=j[2], jargon4=j[3]
            )
        )

        # 5. Bare except (50% chance)
        if self._rng.random() < 0.6:
            parts.append(_SLOP_BARE_EXCEPT.format(suffix=suffix))

        # 6. Dead code (50% chance)
        if self._rng.random() < 0.5:
            parts.append(_SLOP_DEAD_CODE.format(suffix=suffix))

        # 7. Mutable default (40% chance)
        if self._rng.random() < 0.4:
            parts.append(_SLOP_MUTABLE_DEFAULT.format(suffix=suffix))

        # 8. Cross-language mistake (40% chance)
        if self._rng.random() < 0.4:
            mistake = self._rng.choice(_CROSS_LANG_MISTAKES)
            parts.append(f"\ndef cross_lang_{suffix}():\n    items = []\n    {mistake}\n")

        return "\n".join(parts)

    def generate_clean_file(self) -> str:
        """Generate a realistic clean Python file as a string.

        Selects 3-5 diverse, real utility functions with no anti-patterns.
        """
        parts: List[str] = []

        # 1. Minimal module docstring (no jargon)
        topics = [
            "string utilities",
            "list helpers",
            "math utilities",
            "file helpers",
            "dict utilities",
            "data processing",
        ]
        parts.append(f'"""Utility functions for {self._rng.choice(topics)}."""\n')

        # 2. Only imports that will actually be used
        use_os = self._rng.random() < 0.3
        use_re = self._rng.random() < 0.2
        if use_os:
            parts.append("import os")
        if use_re:
            parts.append("import re")
        if use_os or use_re:
            parts.append("")

        # 3. 3-5 clean, diverse functions
        selected = self._rng.sample(_CLEAN_FUNCTIONS, k=self._rng.randint(3, 5))
        for fn in selected:
            parts.append(fn)

        # 4. Add os/re usage if those were imported
        if use_os:
            parts.append(
                'def get_env(key: str, default: str = "") -> str:\n'
                "    return os.environ.get(key, default)\n"
            )
        if use_re:
            parts.append(
                "def extract_digits(text: str) -> list:\n" '    return re.findall(r"\\d+", text)\n'
            )

        return "\n".join(parts)

    # ------------------------------------------------------------------
    # Legacy interface (backward compat)
    # ------------------------------------------------------------------

    def generate_synthetic_file(
        self,
        output_path: str,
        num_functions: int = 5,
        add_cross_lang: bool = True,
        add_mutable_defaults: bool = True,
        add_bare_except: bool = True,
    ) -> None:
        """Write a slop file to disk (legacy API)."""
        code = self.generate_slop_file()
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(code, encoding="utf-8")

    def generate_dataset(self, output_dir: str, num_samples: int = 100) -> None:
        """Generate a dataset of synthetic slop files (legacy API)."""
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)
        for i in range(num_samples):
            fpath = output_path / f"synthetic_sample_{i:04d}.py"
            fpath.write_text(self.generate_slop_file(), encoding="utf-8")
        print(f"[+] Generated {num_samples} synthetic samples in {output_dir}")


if __name__ == "__main__":
    gen = SyntheticGenerator()
    print("=== SLOP SAMPLE ===")
    print(gen.generate_slop_file()[:800])
    print("\n=== CLEAN SAMPLE ===")
    print(gen.generate_clean_file()[:800])
