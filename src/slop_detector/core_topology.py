"""Deterministic structural-coherence calculations for project analysis."""

from __future__ import annotations

import ast
from collections import Counter
from math import log, sqrt
from typing import Callable, Dict, List, Sequence


def compute_dcf(tree: ast.AST) -> Dict[str, float]:
    """Return the normalized AST node distribution for one parsed source file."""
    counts = Counter(type(node).__name__ for node in ast.walk(tree))
    total = sum(counts.values()) or 1
    return {name: count / total for name, count in counts.items()}


def js_divergence(p: List[float], q: List[float]) -> float:
    """Return Jensen-Shannon divergence for two probability vectors."""
    midpoint = [(left + right) / 2.0 for left, right in zip(p, q)]
    epsilon = 1e-12

    def kl_divergence(left: List[float], right: List[float]) -> float:
        return sum(
            left_value * log(left_value / right_value)
            for left_value, right_value in zip(left, right)
            if left_value > epsilon and right_value > epsilon
        )

    divergence = 0.5 * kl_divergence(p, midpoint) + 0.5 * kl_divergence(q, midpoint)
    return max(0.0, min(1.0, divergence))


def deterministic_sample_indices(total: int, sample_size: int) -> List[int]:
    """Pick stable, evenly distributed indices from an ordered sequence."""
    if sample_size >= total:
        return list(range(total))
    if sample_size <= 1:
        return [0]

    last = total - 1
    raw = [round(index * last / (sample_size - 1)) for index in range(sample_size)]
    indices: List[int] = []
    seen = set()
    for index in raw:
        candidate = int(index)
        while candidate in seen and candidate < total - 1:
            candidate += 1
        while candidate in seen and candidate > 0:
            candidate -= 1
        if candidate not in seen:
            indices.append(candidate)
            seen.add(candidate)

    for candidate in range(total):
        if len(indices) >= sample_size:
            break
        if candidate not in seen:
            indices.append(candidate)
            seen.add(candidate)
    return sorted(indices)


def compute_coherence_vr_exact(file_dcfs: Sequence[Dict[str, float]]) -> float:
    """Return MST H0 persistence coherence across parsed-file DCFs."""
    count = len(file_dcfs)
    if count <= 1:
        return 1.0

    distances = [[0.0] * count for _ in range(count)]
    for left_index in range(count):
        for right_index in range(left_index + 1, count):
            keys = sorted(set(file_dcfs[left_index]) | set(file_dcfs[right_index]))
            left = [file_dcfs[left_index].get(key, 0.0) for key in keys]
            right = [file_dcfs[right_index].get(key, 0.0) for key in keys]
            distance = sqrt(js_divergence(left, right))
            distances[left_index][right_index] = distance
            distances[right_index][left_index] = distance

    in_mst = [False] * count
    min_edge = [float("inf")] * count
    min_edge[0] = 0.0
    mst_edge_weights: List[float] = []
    for _ in range(count):
        current = min(
            (index for index in range(count) if not in_mst[index]),
            key=lambda index: min_edge[index],
        )
        in_mst[current] = True
        if min_edge[current] > 0.0:
            mst_edge_weights.append(min_edge[current])
        for candidate in range(count):
            if not in_mst[candidate] and distances[current][candidate] < min_edge[candidate]:
                min_edge[candidate] = distances[current][candidate]

    max_persistence = max(mst_edge_weights) if mst_edge_weights else 0.0
    return max(0.0, 1.0 - max_persistence)


def compute_coherence_vr(
    file_dcfs: List[Dict[str, float]],
    exact_ceiling: int,
    mode_above_ceiling: str,
    exact_calculator: Callable[[Sequence[Dict[str, float]]], float] = compute_coherence_vr_exact,
) -> tuple[float, str]:
    """Return exact coherence or deterministic sampled coherence above the configured ceiling."""
    if len(file_dcfs) <= 1:
        return 1.0, "none"
    if len(file_dcfs) <= exact_ceiling or mode_above_ceiling == "exact":
        return exact_calculator(file_dcfs), "vr_structural"

    sample_indices = deterministic_sample_indices(len(file_dcfs), exact_ceiling)
    sampled_dcfs = [file_dcfs[index] for index in sample_indices]
    return exact_calculator(sampled_dcfs), "vr_structural_approx"
