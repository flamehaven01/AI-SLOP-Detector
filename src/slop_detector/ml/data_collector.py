"""
ML Training Data Collection and Management.

This module handles:
- Feature extraction from analyzed code
- Training dataset creation
- Good code collection from repos
- Slop code collection and generation
"""

import json
import ast
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import List, Dict, Any, Optional

from slop_detector.core import SlopDetector
from slop_detector.models import FileAnalysis


@dataclass
class TrainingFeatures:
    """Features extracted for ML training."""
    
    # File metadata
    file_path: str
    file_size: int
    total_lines: int
    
    # Metric-based features (v2.0)
    ldr_score: float
    bcr_score: float
    ddc_score: float
    
    # Pattern-based features (v2.1)
    pattern_count_critical: int
    pattern_count_high: int
    pattern_count_medium: int
    pattern_count_low: int
    pattern_count_total: int
    
    # Code complexity features
    avg_function_length: float
    avg_complexity: float
    max_nesting_depth: int
    num_functions: int
    num_classes: int
    
    # Style features
    comment_ratio: float
    docstring_ratio: float
    blank_line_ratio: float
    avg_line_length: float
    
    # Cross-language violations
    js_pattern_count: int
    java_pattern_count: int
    ruby_pattern_count: int
    go_pattern_count: int
    csharp_pattern_count: int
    php_pattern_count: int
    
    # Label
    is_slop: int  # 0 = good, 1 = slop
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return asdict(self)
    
    @classmethod
    def from_analysis(
        cls,
        analysis: FileAnalysis,
        is_slop: int,
        additional_features: Optional[Dict[str, Any]] = None
    ) -> "TrainingFeatures":
        """
        Extract features from FileAnalysis result.
        
        Args:
            analysis: SlopDetector analysis result
            is_slop: Label (0=good, 1=slop)
            additional_features: Extra computed features
        """
        additional = additional_features or {}
        
        # Count patterns by severity
        pattern_counts = {
            "critical": 0,
            "high": 0,
            "medium": 0,
            "low": 0,
        }
        for issue in analysis.pattern_issues:
            severity = issue.severity.value
            if severity in pattern_counts:
                pattern_counts[severity] += 1
        
        # Count cross-language patterns
        cross_lang_counts = {
            "js": 0,
            "java": 0,
            "ruby": 0,
            "go": 0,
            "csharp": 0,
            "php": 0,
        }
        for issue in analysis.pattern_issues:
            pattern_id = issue.pattern_id
            if pattern_id.startswith("js_"):
                cross_lang_counts["js"] += 1
            elif pattern_id.startswith("java_"):
                cross_lang_counts["java"] += 1
            elif pattern_id.startswith("ruby_"):
                cross_lang_counts["ruby"] += 1
            elif pattern_id.startswith("go_"):
                cross_lang_counts["go"] += 1
            elif pattern_id.startswith("csharp_"):
                cross_lang_counts["csharp"] += 1
            elif pattern_id.startswith("php_"):
                cross_lang_counts["php"] += 1
        
        return cls(
            file_path=analysis.file_path,
            file_size=additional.get("file_size", 0),
            total_lines=analysis.ldr.total_lines,
            
            ldr_score=analysis.ldr.ldr_score,
            bcr_score=min(analysis.bcr.bcr_score, 5.0),  # Cap at 5.0 for inf handling
            ddc_score=analysis.ddc.usage_ratio,
            
            pattern_count_critical=pattern_counts["critical"],
            pattern_count_high=pattern_counts["high"],
            pattern_count_medium=pattern_counts["medium"],
            pattern_count_low=pattern_counts["low"],
            pattern_count_total=len(analysis.pattern_issues),
            
            avg_function_length=additional.get("avg_function_length", 0.0),
            avg_complexity=analysis.bcr.avg_complexity,
            max_nesting_depth=additional.get("max_nesting_depth", 0),
            num_functions=additional.get("num_functions", 0),
            num_classes=additional.get("num_classes", 0),
            
            comment_ratio=additional.get("comment_ratio", 0.0),
            docstring_ratio=additional.get("docstring_ratio", 0.0),
            blank_line_ratio=additional.get("blank_line_ratio", 0.0),
            avg_line_length=additional.get("avg_line_length", 0.0),
            
            js_pattern_count=cross_lang_counts["js"],
            java_pattern_count=cross_lang_counts["java"],
            ruby_pattern_count=cross_lang_counts["ruby"],
            go_pattern_count=cross_lang_counts["go"],
            csharp_pattern_count=cross_lang_counts["csharp"],
            php_pattern_count=cross_lang_counts["php"],
            
            is_slop=is_slop,
        )


class TrainingDataCollector:
    """Collect and manage training data for ML models."""
    
    def __init__(self, output_dir: str = "training_data"):
        """Initialize collector with output directory."""
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True)
        
        self.detector = SlopDetector()
        self.good_samples: List[TrainingFeatures] = []
        self.slop_samples: List[TrainingFeatures] = []
    
    def collect_file(
        self,
        file_path: str,
        is_slop: int,
        additional_features: Optional[Dict[str, Any]] = None
    ) -> Optional[TrainingFeatures]:
        """
        Analyze and collect features from a single file.
        
        Args:
            file_path: Path to Python file
            is_slop: 0 for good code, 1 for slop
            additional_features: Extra features to include
            
        Returns:
            TrainingFeatures or None if analysis failed
        """
        try:
            # Analyze file
            analysis = self.detector.analyze_file(file_path)
            
            # Extract additional features if not provided
            if additional_features is None:
                additional_features = self._compute_additional_features(file_path)
            
            # Create training features
            features = TrainingFeatures.from_analysis(
                analysis,
                is_slop,
                additional_features
            )
            
            # Store in appropriate list
            if is_slop == 0:
                self.good_samples.append(features)
            else:
                self.slop_samples.append(features)
            
            return features
            
        except Exception as e:
            print(f"[!] Failed to collect {file_path}: {e}")
            return None
    
    def _compute_additional_features(self, file_path: str) -> Dict[str, Any]:
        """Compute additional features not in FileAnalysis."""
        import ast
        
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
            
            tree = ast.parse(content)
            
            # Count functions and classes
            num_functions = sum(1 for node in ast.walk(tree) if isinstance(node, ast.FunctionDef))
            num_classes = sum(1 for node in ast.walk(tree) if isinstance(node, ast.ClassDef))
            
            # Calculate average function length
            function_lengths = []
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef):
                    if hasattr(node, 'end_lineno') and hasattr(node, 'lineno'):
                        length = node.end_lineno - node.lineno
                        function_lengths.append(length)
            
            avg_function_length = sum(function_lengths) / len(function_lengths) if function_lengths else 0
            
            # Calculate max nesting depth
            max_depth = self._get_max_nesting_depth(tree)
            
            # Calculate comment and blank line ratios
            lines = content.split('\n')
            total_lines = len(lines)
            comment_lines = sum(1 for line in lines if line.strip().startswith('#'))
            blank_lines = sum(1 for line in lines if not line.strip())
            
            comment_ratio = comment_lines / total_lines if total_lines > 0 else 0
            blank_line_ratio = blank_lines / total_lines if total_lines > 0 else 0
            
            # Calculate docstring ratio
            docstring_count = 0
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.ClassDef, ast.Module)):
                    if ast.get_docstring(node):
                        docstring_count += 1
            
            docstring_ratio = docstring_count / (num_functions + num_classes + 1) if (num_functions + num_classes) > 0 else 0
            
            # Average line length
            non_blank_lines = [line for line in lines if line.strip()]
            avg_line_length = sum(len(line) for line in non_blank_lines) / len(non_blank_lines) if non_blank_lines else 0
            
            return {
                "file_size": len(content),
                "num_functions": num_functions,
                "num_classes": num_classes,
                "avg_function_length": avg_function_length,
                "max_nesting_depth": max_depth,
                "comment_ratio": comment_ratio,
                "docstring_ratio": docstring_ratio,
                "blank_line_ratio": blank_line_ratio,
                "avg_line_length": avg_line_length,
            }
            
        except Exception as e:
            print(f"[!] Failed to compute additional features: {e}")
            return {}
    
    def _get_max_nesting_depth(self, node: ast.AST, current_depth: int = 0) -> int:
        """Calculate maximum nesting depth in AST."""
        max_depth = current_depth
        
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.If, ast.For, ast.While, ast.With, ast.Try)):
                child_depth = self._get_max_nesting_depth(child, current_depth + 1)
                max_depth = max(max_depth, child_depth)
        
        return max_depth
    
    def save_dataset(self, split_name: str = "train") -> None:
        """
        Save collected samples to JSON files.
        
        Args:
            split_name: Name of the split (train, val, test)
        """
        split_dir = self.output_dir / split_name
        split_dir.mkdir(exist_ok=True)
        
        # Save good samples
        good_path = split_dir / "good_samples.json"
        with open(good_path, 'w', encoding='utf-8') as f:
            json.dump([s.to_dict() for s in self.good_samples], f, indent=2)
        
        print(f"[+] Saved {len(self.good_samples)} good samples to {good_path}")
        
        # Save slop samples
        slop_path = split_dir / "slop_samples.json"
        with open(slop_path, 'w', encoding='utf-8') as f:
            json.dump([s.to_dict() for s in self.slop_samples], f, indent=2)
        
        print(f"[+] Saved {len(self.slop_samples)} slop samples to {slop_path}")
        
        # Save combined dataset
        all_samples = self.good_samples + self.slop_samples
        combined_path = split_dir / "dataset.json"
        with open(combined_path, 'w', encoding='utf-8') as f:
            json.dump([s.to_dict() for s in all_samples], f, indent=2)
        
        print(f"[+] Saved {len(all_samples)} total samples to {combined_path}")
        
        # Save statistics
        stats = {
            "good_count": len(self.good_samples),
            "slop_count": len(self.slop_samples),
            "total_count": len(all_samples),
            "balance_ratio": len(self.slop_samples) / len(self.good_samples) if self.good_samples else 0,
        }
        
        stats_path = split_dir / "stats.json"
        with open(stats_path, 'w', encoding='utf-8') as f:
            json.dump(stats, f, indent=2)
        
        print(f"[+] Dataset statistics saved to {stats_path}")
    
    def clear(self) -> None:
        """Clear collected samples."""
        self.good_samples.clear()
        self.slop_samples.clear()
