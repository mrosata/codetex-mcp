"""Token efficiency metrics for context density evaluation.

Pure functions — no I/O, fully unit-testable.
Token counting uses tiktoken cl100k_base (same as the analysis module).
"""

from __future__ import annotations

import tiktoken

# Lazy-loaded tiktoken encoder
_encoder: tiktoken.Encoding | None = None


def _get_encoder() -> tiktoken.Encoding:
    global _encoder
    if _encoder is None:
        _encoder = tiktoken.get_encoding("cl100k_base")
    return _encoder


def count_tokens(text: str) -> int:
    """Count tokens in text using tiktoken cl100k_base encoding."""
    if not text:
        return 0
    return len(_get_encoder().encode(text))


def compression_ratio(baseline_tokens: int, compressed_tokens: int) -> float:
    """Ratio of baseline tokens to compressed tokens.

    Higher is better — means codetex uses fewer tokens.
    Returns 0.0 if compressed_tokens is 0.
    """
    if compressed_tokens <= 0:
        return 0.0
    return baseline_tokens / compressed_tokens


def coverage_score(content: str, gold_symbols: list[str]) -> float:
    """Fraction of expected symbols/concepts that appear in the content.

    Performs case-insensitive substring matching.
    Returns 0.0 if gold_symbols is empty.
    """
    if not gold_symbols:
        return 0.0
    content_lower = content.lower()
    hits = sum(1 for symbol in gold_symbols if symbol.lower() in content_lower)
    return hits / len(gold_symbols)


def token_density(relevant_tokens: int, total_tokens: int) -> float:
    """Fraction of total tokens that are relevant.

    Higher is better — means less noise in the context.
    Returns 0.0 if total_tokens is 0.
    """
    if total_tokens <= 0:
        return 0.0
    return relevant_tokens / total_tokens
