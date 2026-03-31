"""IR metrics for retrieval quality evaluation.

Pure functions — no I/O, fully unit-testable.
"""

from __future__ import annotations

import math


def precision_at_k(retrieved: list[str], relevant: set[str], k: int) -> float:
    """Fraction of the top-k retrieved items that are relevant.

    Returns 0.0 if k <= 0 or retrieved is empty.
    """
    if k <= 0 or not retrieved:
        return 0.0
    top_k = retrieved[:k]
    hits = sum(1 for item in top_k if item in relevant)
    return hits / len(top_k)


def recall_at_k(retrieved: list[str], relevant: set[str], k: int) -> float:
    """Fraction of relevant items found in the top-k retrieved items.

    Returns 0.0 if there are no relevant items.
    """
    if not relevant:
        return 0.0
    if k <= 0 or not retrieved:
        return 0.0
    top_k = retrieved[:k]
    hits = sum(1 for item in top_k if item in relevant)
    return hits / len(relevant)


def mean_reciprocal_rank(retrieved: list[str], relevant: set[str]) -> float:
    """Reciprocal rank of the first relevant item in the retrieved list.

    Returns 0.0 if no relevant item is found.
    """
    for i, item in enumerate(retrieved):
        if item in relevant:
            return 1.0 / (i + 1)
    return 0.0


def ndcg_at_k(retrieved: list[str], relevant: set[str], k: int) -> float:
    """Normalized Discounted Cumulative Gain at k.

    Uses binary relevance (1 if relevant, 0 otherwise).
    Returns 0.0 if there are no relevant items or k <= 0.
    """
    if k <= 0 or not relevant or not retrieved:
        return 0.0

    top_k = retrieved[:k]

    # DCG: sum of relevance / log2(rank + 1)
    dcg = 0.0
    for i, item in enumerate(top_k):
        if item in relevant:
            dcg += 1.0 / math.log2(i + 2)  # i+2 because log2(1)=0

    # Ideal DCG: all relevant items ranked at top
    ideal_count = min(len(relevant), k)
    idcg = sum(1.0 / math.log2(i + 2) for i in range(ideal_count))

    if idcg == 0.0:
        return 0.0
    return dcg / idcg
