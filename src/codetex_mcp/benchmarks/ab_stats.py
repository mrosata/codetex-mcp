"""Statistical comparison functions for A/B benchmark evaluation.

Pure functions — no I/O, fully unit-testable.
Provides paired t-test, Cohen's d effect size, and comparison
summaries for evaluating differences between two conditions.
"""

from __future__ import annotations

import math


def paired_t_test(baseline: list[float], treatment: list[float]) -> tuple[float, float]:
    """Compute paired t-test statistic and two-tailed p-value.

    Tests whether the mean difference between paired observations
    is significantly different from zero.

    Args:
        baseline: Scores under the baseline condition.
        treatment: Scores under the treatment condition.

    Returns:
        Tuple of (t_statistic, p_value). Returns (0.0, 1.0) if
        fewer than 2 pairs or zero variance in differences.

    Raises:
        ValueError: If list lengths don't match.
    """
    if len(baseline) != len(treatment):
        raise ValueError(
            f"Length mismatch: {len(baseline)} baseline vs {len(treatment)} treatment"
        )
    n = len(baseline)
    if n < 2:
        return 0.0, 1.0

    diffs = [t - b for b, t in zip(baseline, treatment)]
    mean_d = sum(diffs) / n
    var_d = sum((d - mean_d) ** 2 for d in diffs) / (n - 1)

    if var_d == 0.0:
        return 0.0, 1.0

    se = math.sqrt(var_d / n)
    t_stat = mean_d / se

    # Two-tailed p-value via Student's t-distribution approximation
    p_value = _t_distribution_p_value(abs(t_stat), n - 1)
    return t_stat, p_value


def cohens_d(baseline: list[float], treatment: list[float]) -> float:
    """Compute Cohen's d effect size for paired samples.

    Uses the mean difference divided by the pooled standard deviation.

    Args:
        baseline: Scores under the baseline condition.
        treatment: Scores under the treatment condition.

    Returns:
        Cohen's d value. Returns 0.0 if fewer than 2 pairs or
        zero pooled variance.

    Raises:
        ValueError: If list lengths don't match.
    """
    if len(baseline) != len(treatment):
        raise ValueError(
            f"Length mismatch: {len(baseline)} baseline vs {len(treatment)} treatment"
        )
    n = len(baseline)
    if n < 2:
        return 0.0

    mean_b = sum(baseline) / n
    mean_t = sum(treatment) / n
    mean_diff = mean_t - mean_b

    var_b = sum((x - mean_b) ** 2 for x in baseline) / (n - 1)
    var_t = sum((x - mean_t) ** 2 for x in treatment) / (n - 1)
    pooled_sd = math.sqrt((var_b + var_t) / 2)

    if pooled_sd == 0.0:
        return 0.0

    return mean_diff / pooled_sd


def mean_improvement(baseline: list[float], treatment: list[float]) -> float:
    """Compute the mean improvement (treatment - baseline).

    Args:
        baseline: Scores under the baseline condition.
        treatment: Scores under the treatment condition.

    Returns:
        Mean of (treatment[i] - baseline[i]) for each pair.
        Returns 0.0 if lists are empty.

    Raises:
        ValueError: If list lengths don't match.
    """
    if len(baseline) != len(treatment):
        raise ValueError(
            f"Length mismatch: {len(baseline)} baseline vs {len(treatment)} treatment"
        )
    if not baseline:
        return 0.0
    return sum(t - b for b, t in zip(baseline, treatment)) / len(baseline)


def improvement_pct(baseline_mean: float, treatment_mean: float) -> float:
    """Compute percentage improvement from baseline to treatment.

    Args:
        baseline_mean: Mean score under baseline condition.
        treatment_mean: Mean score under treatment condition.

    Returns:
        Percentage improvement. Returns 0.0 if baseline_mean is 0.
    """
    if baseline_mean == 0.0:
        return 0.0
    return ((treatment_mean - baseline_mean) / baseline_mean) * 100.0


def significance_summary(
    t_stat: float,
    p_value: float,
    effect_size: float,
    alpha: float = 0.05,
) -> dict[str, object]:
    """Summarize statistical significance results.

    Args:
        t_stat: t-test statistic.
        p_value: Two-tailed p-value.
        effect_size: Cohen's d effect size.
        alpha: Significance level (default 0.05).

    Returns:
        Dictionary with significance indicators and interpretation.
    """
    significant = p_value < alpha
    effect_label = _effect_size_label(abs(effect_size))

    if significant:
        direction = "improvement" if effect_size > 0 else "degradation"
        interpretation = (
            f"Statistically significant {direction} (p={p_value:.4f}) "
            f"with {effect_label} effect size (d={effect_size:.3f})"
        )
    else:
        interpretation = f"No statistically significant difference (p={p_value:.4f})"

    return {
        "t_statistic": round(t_stat, 4),
        "p_value": round(p_value, 4),
        "effect_size_cohens_d": round(effect_size, 4),
        "effect_size_label": effect_label,
        "significant_at_alpha": significant,
        "alpha": alpha,
        "interpretation": interpretation,
    }


def _effect_size_label(d: float) -> str:
    """Classify Cohen's d effect size magnitude."""
    if d < 0.2:
        return "negligible"
    elif d < 0.5:
        return "small"
    elif d < 0.8:
        return "medium"
    else:
        return "large"


def _t_distribution_p_value(t_abs: float, df: int) -> float:
    """Approximate two-tailed p-value for Student's t-distribution.

    Uses the regularized incomplete beta function approximation.
    For large df (>100), uses normal approximation.
    """
    if df <= 0:
        return 1.0
    if t_abs == 0.0:
        return 1.0

    # For large degrees of freedom, use normal approximation
    if df > 100:
        return 2.0 * _normal_sf(t_abs)

    # Use incomplete beta function: p = I_{x}(a, b)
    # where x = df/(df + t^2), a = df/2, b = 0.5
    x = df / (df + t_abs * t_abs)
    p = _regularized_incomplete_beta(x, df / 2.0, 0.5)
    return min(1.0, max(0.0, p))


def _normal_sf(z: float) -> float:
    """Survival function (1 - CDF) for standard normal distribution.

    Uses Abramowitz & Stegun approximation 7.1.26.
    """
    a1 = 0.254829592
    a2 = -0.284496736
    a3 = 1.421413741
    a4 = -1.453152027
    a5 = 1.061405429
    p = 0.3275911

    sign = 1 if z >= 0 else -1
    z = abs(z) / math.sqrt(2)

    t = 1.0 / (1.0 + p * z)
    y = 1.0 - (((((a5 * t + a4) * t) + a3) * t + a2) * t + a1) * t * math.exp(-z * z)

    cdf = 0.5 * (1.0 + sign * y)
    return 1.0 - cdf


def _regularized_incomplete_beta(x: float, a: float, b: float) -> float:
    """Regularized incomplete beta function I_x(a, b).

    Uses continued fraction approximation (Lentz's algorithm).
    """
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0

    # Use the symmetry relation if needed for convergence
    if x > (a + 1.0) / (a + b + 2.0):
        return 1.0 - _regularized_incomplete_beta(1.0 - x, b, a)

    # Log of the prefix: x^a * (1-x)^b / (a * Beta(a, b))
    ln_prefix = a * math.log(x) + b * math.log(1.0 - x) - math.log(a) - _log_beta(a, b)
    prefix = math.exp(ln_prefix)

    # Continued fraction (Lentz's method)
    cf = _beta_continued_fraction(x, a, b)
    return min(1.0, max(0.0, prefix * cf))


def _log_beta(a: float, b: float) -> float:
    """Log of the beta function: log(Beta(a, b)) = lgamma(a) + lgamma(b) - lgamma(a+b)."""
    return math.lgamma(a) + math.lgamma(b) - math.lgamma(a + b)


def _beta_continued_fraction(x: float, a: float, b: float) -> float:
    """Evaluate continued fraction for incomplete beta function."""
    max_iter = 200
    eps = 1e-14

    # Modified Lentz's method
    f = 1.0
    c = 1.0
    d = 1.0 - (a + b) * x / (a + 1.0)
    if abs(d) < eps:
        d = eps
    d = 1.0 / d
    f = d

    for m in range(1, max_iter + 1):
        # Even step
        m2 = 2 * m
        num = m * (b - m) * x / ((a + m2 - 1.0) * (a + m2))
        d = 1.0 + num * d
        if abs(d) < eps:
            d = eps
        c = 1.0 + num / c
        if abs(c) < eps:
            c = eps
        d = 1.0 / d
        f *= c * d

        # Odd step
        num = -(a + m) * (a + b + m) * x / ((a + m2) * (a + m2 + 1.0))
        d = 1.0 + num * d
        if abs(d) < eps:
            d = eps
        c = 1.0 + num / c
        if abs(c) < eps:
            c = eps
        d = 1.0 / d
        delta = c * d
        f *= delta

        if abs(delta - 1.0) < eps:
            break

    return f
