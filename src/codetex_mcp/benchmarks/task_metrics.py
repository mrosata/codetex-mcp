"""Task completion metrics for evaluating LLM coding task correctness.

Pure functions — no I/O, fully unit-testable.
Used by Approach 3 (task completion A/B) benchmark runners.
"""

from __future__ import annotations


def exact_match(expected: str, actual: str) -> float:
    """Returns 1.0 if expected equals actual (stripped), else 0.0.

    Case-sensitive comparison after stripping leading/trailing whitespace.
    Returns 0.0 if either string is empty.
    """
    if not expected or not actual:
        return 0.0
    return 1.0 if expected.strip() == actual.strip() else 0.0


def line_coverage(expected_lines: list[str], actual: str) -> float:
    """Fraction of expected lines found (as substrings) in actual output.

    Performs stripped, case-sensitive substring matching.
    Returns 0.0 if expected_lines is empty.
    """
    if not expected_lines:
        return 0.0
    hits = sum(
        1 for line in expected_lines if line.strip() in actual
    )
    return hits / len(expected_lines)


def symbol_presence(expected_symbols: list[str], actual: str) -> float:
    """Fraction of expected symbol names found in actual output.

    Performs case-sensitive substring matching.
    Returns 0.0 if expected_symbols is empty or actual is empty.
    """
    if not expected_symbols or not actual:
        return 0.0
    hits = sum(1 for sym in expected_symbols if sym in actual)
    return hits / len(expected_symbols)


def keyword_overlap(expected_keywords: list[str], actual: str) -> float:
    """Fraction of expected keywords found in actual output.

    Performs case-insensitive substring matching.
    Returns 0.0 if expected_keywords is empty or actual is empty.
    """
    if not expected_keywords or not actual:
        return 0.0
    actual_lower = actual.lower()
    hits = sum(1 for kw in expected_keywords if kw.lower() in actual_lower)
    return hits / len(expected_keywords)


def aggregate_correctness(
    symbol_score: float,
    keyword_score: float,
    line_score: float,
) -> float:
    """Weighted aggregate of correctness sub-scores.

    Weights: symbol_presence 0.4, keyword_overlap 0.3, line_coverage 0.3.
    All inputs should be in [0.0, 1.0].
    """
    return 0.4 * symbol_score + 0.3 * keyword_score + 0.3 * line_score


def success_rate(scores: list[float], threshold: float = 0.5) -> float:
    """Fraction of tasks with correctness score >= threshold.

    Returns 0.0 if scores is empty.
    """
    if not scores:
        return 0.0
    passing = sum(1 for s in scores if s >= threshold)
    return passing / len(scores)
