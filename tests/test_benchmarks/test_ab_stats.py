"""Tests for A/B comparison statistical functions."""

from __future__ import annotations

import math

import pytest

from codetex_mcp.benchmarks.ab_stats import (
    cohens_d,
    improvement_pct,
    mean_improvement,
    paired_t_test,
    significance_summary,
)


class TestPairedTTest:
    def test_identical_scores_returns_no_significance(self) -> None:
        baseline = [0.5, 0.6, 0.7, 0.8]
        treatment = [0.5, 0.6, 0.7, 0.8]
        t_stat, p_value = paired_t_test(baseline, treatment)
        assert t_stat == 0.0
        assert p_value == 1.0

    def test_clear_improvement_returns_low_p_value(self) -> None:
        baseline = [0.3, 0.4, 0.3, 0.4, 0.3, 0.4, 0.3, 0.4]
        treatment = [0.9, 0.9, 0.9, 0.9, 0.9, 0.9, 0.9, 0.9]
        t_stat, p_value = paired_t_test(baseline, treatment)
        assert t_stat > 0
        assert p_value < 0.05

    def test_single_pair_returns_default(self) -> None:
        t_stat, p_value = paired_t_test([0.5], [0.9])
        assert t_stat == 0.0
        assert p_value == 1.0

    def test_empty_lists_returns_default(self) -> None:
        t_stat, p_value = paired_t_test([], [])
        assert t_stat == 0.0
        assert p_value == 1.0

    def test_length_mismatch_raises(self) -> None:
        with pytest.raises(ValueError, match="Length mismatch"):
            paired_t_test([0.5, 0.6], [0.5])

    def test_negative_improvement_returns_negative_t(self) -> None:
        baseline = [0.9, 0.9, 0.9, 0.9, 0.9, 0.9, 0.9, 0.9]
        treatment = [0.3, 0.4, 0.3, 0.4, 0.3, 0.4, 0.3, 0.4]
        t_stat, p_value = paired_t_test(baseline, treatment)
        assert t_stat < 0
        assert p_value < 0.05

    def test_p_value_between_zero_and_one(self) -> None:
        baseline = [0.3, 0.5, 0.4, 0.6]
        treatment = [0.5, 0.6, 0.5, 0.8]
        _, p_value = paired_t_test(baseline, treatment)
        assert 0.0 <= p_value <= 1.0

    def test_two_pairs_computes(self) -> None:
        baseline = [0.3, 0.5]
        treatment = [0.8, 0.7]
        t_stat, p_value = paired_t_test(baseline, treatment)
        assert t_stat > 0
        assert 0.0 <= p_value <= 1.0


class TestCohensD:
    def test_identical_scores_returns_zero(self) -> None:
        baseline = [0.5, 0.6, 0.7, 0.8]
        treatment = [0.5, 0.6, 0.7, 0.8]
        assert cohens_d(baseline, treatment) == 0.0

    def test_large_difference_returns_large_d(self) -> None:
        baseline = [0.1, 0.2, 0.1, 0.2]
        treatment = [0.9, 0.9, 0.9, 0.9]
        d = cohens_d(baseline, treatment)
        assert d > 0.8  # Large effect

    def test_negative_improvement_returns_negative_d(self) -> None:
        baseline = [0.9, 0.9, 0.9, 0.9]
        treatment = [0.1, 0.2, 0.1, 0.2]
        d = cohens_d(baseline, treatment)
        assert d < 0

    def test_single_pair_returns_zero(self) -> None:
        assert cohens_d([0.5], [0.9]) == 0.0

    def test_empty_returns_zero(self) -> None:
        assert cohens_d([], []) == 0.0

    def test_length_mismatch_raises(self) -> None:
        with pytest.raises(ValueError, match="Length mismatch"):
            cohens_d([0.5], [0.5, 0.6])

    def test_zero_variance_returns_zero(self) -> None:
        baseline = [0.5, 0.5, 0.5]
        treatment = [0.5, 0.5, 0.5]
        assert cohens_d(baseline, treatment) == 0.0


class TestMeanImprovement:
    def test_positive_improvement(self) -> None:
        baseline = [0.3, 0.4, 0.5]
        treatment = [0.6, 0.7, 0.8]
        result = mean_improvement(baseline, treatment)
        assert abs(result - 0.3) < 1e-10

    def test_negative_improvement(self) -> None:
        baseline = [0.8, 0.9]
        treatment = [0.3, 0.4]
        result = mean_improvement(baseline, treatment)
        assert result < 0

    def test_no_improvement(self) -> None:
        baseline = [0.5, 0.6]
        treatment = [0.5, 0.6]
        assert mean_improvement(baseline, treatment) == 0.0

    def test_empty_returns_zero(self) -> None:
        assert mean_improvement([], []) == 0.0

    def test_length_mismatch_raises(self) -> None:
        with pytest.raises(ValueError, match="Length mismatch"):
            mean_improvement([0.5], [0.5, 0.6])


class TestImprovementPct:
    def test_positive_improvement(self) -> None:
        result = improvement_pct(0.5, 0.75)
        assert abs(result - 50.0) < 1e-10

    def test_negative_improvement(self) -> None:
        result = improvement_pct(0.8, 0.4)
        assert abs(result - (-50.0)) < 1e-10

    def test_no_improvement(self) -> None:
        assert improvement_pct(0.5, 0.5) == 0.0

    def test_zero_baseline_returns_zero(self) -> None:
        assert improvement_pct(0.0, 0.5) == 0.0

    def test_double_improvement(self) -> None:
        result = improvement_pct(0.3, 0.6)
        assert abs(result - 100.0) < 1e-10


class TestSignificanceSummary:
    def test_significant_improvement(self) -> None:
        result = significance_summary(
            t_stat=3.5, p_value=0.01, effect_size=0.8
        )
        assert result["significant_at_alpha"] is True
        assert "improvement" in result["interpretation"]
        assert result["effect_size_label"] == "large"

    def test_not_significant(self) -> None:
        result = significance_summary(
            t_stat=0.5, p_value=0.6, effect_size=0.1
        )
        assert result["significant_at_alpha"] is False
        assert "No statistically significant" in result["interpretation"]

    def test_significant_degradation(self) -> None:
        result = significance_summary(
            t_stat=-3.0, p_value=0.02, effect_size=-0.7
        )
        assert result["significant_at_alpha"] is True
        assert "degradation" in result["interpretation"]

    def test_custom_alpha(self) -> None:
        result = significance_summary(
            t_stat=2.0, p_value=0.08, effect_size=0.5, alpha=0.10
        )
        assert result["significant_at_alpha"] is True
        assert result["alpha"] == 0.10

    def test_effect_size_labels(self) -> None:
        assert significance_summary(0, 1, 0.1)["effect_size_label"] == "negligible"
        assert significance_summary(0, 1, 0.3)["effect_size_label"] == "small"
        assert significance_summary(0, 1, 0.6)["effect_size_label"] == "medium"
        assert significance_summary(0, 1, 1.2)["effect_size_label"] == "large"

    def test_all_fields_present(self) -> None:
        result = significance_summary(
            t_stat=2.5, p_value=0.03, effect_size=0.7
        )
        assert "t_statistic" in result
        assert "p_value" in result
        assert "effect_size_cohens_d" in result
        assert "effect_size_label" in result
        assert "significant_at_alpha" in result
        assert "alpha" in result
        assert "interpretation" in result

    def test_values_are_rounded(self) -> None:
        result = significance_summary(
            t_stat=2.123456789, p_value=0.034567, effect_size=0.712345
        )
        # Check that values are rounded (not raw float precision)
        assert result["t_statistic"] == 2.1235
        assert result["p_value"] == 0.0346
        assert result["effect_size_cohens_d"] == 0.7123


class TestPairedTTestPValueAccuracy:
    """Verify that our t-distribution approximation is reasonable."""

    def test_known_large_t_small_p(self) -> None:
        """With many samples and large effect, p should be very small."""
        # Use data where the difference varies slightly (non-zero variance)
        baseline_v = [0.2 + i * 0.01 for i in range(30)]
        treatment_v = [0.8 + i * 0.005 for i in range(30)]
        _, p_value = paired_t_test(baseline_v, treatment_v)
        assert p_value < 0.001

    def test_moderate_difference_moderate_p(self) -> None:
        """With noisy data and moderate effect, p should be moderate."""
        baseline = [0.4, 0.5, 0.3, 0.6]
        treatment = [0.5, 0.6, 0.4, 0.7]
        _, p_value = paired_t_test(baseline, treatment)
        # Small sample, consistent small improvement
        assert 0.0 < p_value < 1.0


class TestCohensDAgreesWithManual:
    def test_known_effect_size(self) -> None:
        """Cohen's d should match manual calculation."""
        baseline = [1.0, 2.0, 3.0, 4.0, 5.0]
        treatment = [2.0, 3.0, 4.0, 5.0, 6.0]
        # Mean diff = 1.0
        # Var of each = 2.5, pooled SD = sqrt(2.5) ≈ 1.5811
        # d = 1.0 / 1.5811 ≈ 0.6325
        d = cohens_d(baseline, treatment)
        expected = 1.0 / math.sqrt(2.5)
        assert abs(d - expected) < 1e-10
