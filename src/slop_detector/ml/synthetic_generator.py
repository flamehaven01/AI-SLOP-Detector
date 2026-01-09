"""
Synthetic Code Generator.

Generates realistic low-quality/noise code samples for training.
"""

import random
from pathlib import Path
from typing import List

# Jargon for ICR inflation
JARGON_TERMS = [
    "neural",
    "quantum",
    "blockchain",
    "AI-powered",
    "deep-learning",
    "transformer",
    "Byzantine",
    "fault-tolerant",
    "state-of-the-art",
    "cutting-edge",
    "novel",
    "robust",
    "optimized",
    "scalable",
    "distributed",
    "microservice",
    "cloud-native",
    "serverless",
]

# Function templates
EMPTY_TEMPLATES = [
    """def {name}({params}):
    \"\"\"{doc}\"\"\"
    pass
""",
    """def {name}({params}):
    \"\"\"{doc}\"\"\"
    ...
""",
    """def {name}({params}):
    \"\"\"{doc}\"\"\"
    # TODO: implement
    return None
""",
]

# Cross-language mistakes
CROSS_LANG_MISTAKES = [
    "items.push(item)",  # JavaScript
    "items.length",  # JavaScript
    "text.equals(other)",  # Java
    "list.isEmpty()",  # Java
    "array.each(fn)",  # Ruby
    "value.nil?()",  # Ruby
]


class SyntheticGenerator:
    """Generate synthetic low-quality code samples."""

    def __init__(self, seed: int = 42):
        """Initialize generator with random seed."""
        random.seed(seed)

    def generate_synthetic_file(
        self,
        output_path: str,
        num_functions: int = 5,
        add_cross_lang: bool = True,
        add_mutable_defaults: bool = True,
        add_bare_except: bool = True,
    ) -> None:
        """
        Generate a complete synthetic file.

        Args:
            output_path: Where to save the generated file
            num_functions: Number of empty functions to generate
            add_cross_lang: Include cross-language mistakes
            add_mutable_defaults: Include mutable default arguments
            add_bare_except: Include bare except blocks
        """
        code_lines = []

        # Add module docstring with jargon
        doc = self._generate_jargon_docstring("module")
        code_lines.append(f'"""\n{doc}\n"""')
        code_lines.append("")

        # Add unused imports (DDC violation)
        code_lines.append("import torch")
        code_lines.append("import tensorflow as tf")
        code_lines.append("import numpy as np")
        code_lines.append("from typing import List, Dict, Any")
        code_lines.append("")

        # Generate empty functions
        for i in range(num_functions):
            func_name = f"function_{i}"
            params = self._generate_params(add_mutable_defaults)
            doc = self._generate_jargon_docstring("function")

            template = random.choice(EMPTY_TEMPLATES)
            func_code = template.format(name=func_name, params=params, doc=doc)
            code_lines.append(func_code)

        # Add cross-language mistakes
        if add_cross_lang:
            code_lines.append("\ndef cross_language_mistakes():")
            code_lines.append('    """Demonstrate cross-language patterns."""')
            code_lines.append("    items = []")

            for mistake in random.sample(CROSS_LANG_MISTAKES, 3):
                code_lines.append(f"    {mistake}")

            code_lines.append("")

        # Add bare except
        if add_bare_except:
            code_lines.append("\ndef risky_operation():")
            code_lines.append('    """Process with bare except."""')
            code_lines.append("    try:")
            code_lines.append("        result = complex_calculation()")
            code_lines.append("    except:")
            code_lines.append("        pass")
            code_lines.append("")

        # Write to file
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)

        with open(output, "w", encoding="utf-8") as f:
            f.write("\n".join(code_lines))

        print(f"[+] Generated synthetic file: {output_path}")

    def _generate_jargon_docstring(self, context: str) -> str:
        """Generate a docstring filled with jargon."""
        words = random.sample(JARGON_TERMS, k=min(5, len(JARGON_TERMS)))

        if context == "module":
            return (
                f"Advanced {words[0]} {words[1]} system.\n\n"
                f"Implements {words[2]} {words[3]} architecture\n"
                f"with {words[4]} processing capabilities."
            )
        else:
            return (
                f"{words[0].capitalize()} {words[1]} processing function.\n\n"
                f"Uses {words[2]} algorithms for {words[3]} performance."
            )

    def _generate_params(self, add_mutable: bool) -> str:
        """Generate function parameters, optionally with mutable defaults."""
        if add_mutable and random.random() < 0.5:
            # Mutable default argument (anti-pattern)
            return random.choice(
                [
                    "data=[]",
                    "config={}",
                    "items=[]",
                    "cache={}",
                ]
            )
        else:
            return random.choice(
                [
                    "",
                    "data",
                    "config",
                    "data, config",
                ]
            )

    def generate_dataset(self, output_dir: str, num_samples: int = 100) -> None:
        """
        Generate a dataset of synthetic samples.

        Args:
            output_dir: Directory to save generated files
            num_samples: Number of samples to generate
        """
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        for i in range(num_samples):
            file_path = output_path / f"synthetic_sample_{i:04d}.py"

            # Randomize which anti-patterns to include
            self.generate_synthetic_file(
                str(file_path),
                num_functions=random.randint(3, 8),
                add_cross_lang=random.random() < 0.7,
                add_mutable_defaults=random.random() < 0.6,
                add_bare_except=random.random() < 0.5,
            )

        print(f"[+] Generated {num_samples} synthetic samples in {output_dir}")


if __name__ == "__main__":
    # Generate synthetic dataset
    generator = SyntheticGenerator()
    generator.generate_dataset("training_data/synthetic_generated", num_samples=100)

    print("[+] Synthetic generation complete!")
