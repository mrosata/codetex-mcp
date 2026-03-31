"""Unit tests for LLM-as-judge scoring system."""

from __future__ import annotations

import json

import pytest

from codetex_mcp.benchmarks.judge import (
    CalibrationResult,
    JudgeScore,
    build_judge_prompt,
    calibrate,
    parse_judge_response,
    _pearson_correlation,
    _validate_score,
    JUDGE_SYSTEM_PROMPT,
)


class TestJudgeScore:
    def test_fields(self) -> None:
        score = JudgeScore(correctness=8, completeness=7, relevance=9, reasoning="good")
        assert score.correctness == 8
        assert score.completeness == 7
        assert score.relevance == 9
        assert score.reasoning == "good"

    def test_aggregate_perfect(self) -> None:
        score = JudgeScore(correctness=10, completeness=10, relevance=10, reasoning="")
        assert score.aggregate == pytest.approx(1.0)

    def test_aggregate_zero(self) -> None:
        score = JudgeScore(correctness=0, completeness=0, relevance=0, reasoning="")
        assert score.aggregate == 0.0

    def test_aggregate_weights(self) -> None:
        # correctness=0.5, completeness=0.3, relevance=0.2
        score = JudgeScore(correctness=10, completeness=0, relevance=0, reasoning="")
        assert score.aggregate == pytest.approx(0.5)

    def test_aggregate_completeness_weight(self) -> None:
        score = JudgeScore(correctness=0, completeness=10, relevance=0, reasoning="")
        assert score.aggregate == pytest.approx(0.3)

    def test_aggregate_relevance_weight(self) -> None:
        score = JudgeScore(correctness=0, completeness=0, relevance=10, reasoning="")
        assert score.aggregate == pytest.approx(0.2)

    def test_aggregate_mixed(self) -> None:
        score = JudgeScore(correctness=8, completeness=6, relevance=9, reasoning="")
        expected = (0.5 * 8 + 0.3 * 6 + 0.2 * 9) / 10.0
        assert score.aggregate == pytest.approx(expected)


class TestBuildJudgePrompt:
    def test_basic_prompt(self) -> None:
        prompt = build_judge_prompt("Write a sort function", "def sort(arr): ...")
        assert "## Task" in prompt
        assert "Write a sort function" in prompt
        assert "## Candidate Response" in prompt
        assert "def sort(arr): ..." in prompt

    def test_without_context(self) -> None:
        prompt = build_judge_prompt("task", "response")
        assert "## Context Provided" not in prompt

    def test_with_context(self) -> None:
        prompt = build_judge_prompt("task", "response", context="some context")
        assert "## Context Provided" in prompt
        assert "some context" in prompt

    def test_code_block_wrapping(self) -> None:
        prompt = build_judge_prompt("task", "def foo(): pass")
        assert "```\ndef foo(): pass\n```" in prompt

    def test_ends_with_instruction(self) -> None:
        prompt = build_judge_prompt("task", "response")
        assert prompt.endswith("Evaluate the candidate response and return the JSON score object.")


class TestParseJudgeResponse:
    def test_parse_raw_json(self) -> None:
        text = json.dumps({
            "correctness": 8,
            "completeness": 7,
            "relevance": 9,
            "reasoning": "Good implementation",
        })
        score = parse_judge_response(text)
        assert score.correctness == 8
        assert score.completeness == 7
        assert score.relevance == 9
        assert score.reasoning == "Good implementation"

    def test_parse_json_in_code_block(self) -> None:
        text = '```json\n{"correctness": 10, "completeness": 10, "relevance": 10, "reasoning": "Perfect"}\n```'
        score = parse_judge_response(text)
        assert score.correctness == 10

    def test_parse_json_in_plain_code_block(self) -> None:
        text = '```\n{"correctness": 5, "completeness": 5, "relevance": 5, "reasoning": "ok"}\n```'
        score = parse_judge_response(text)
        assert score.correctness == 5

    def test_parse_embedded_json(self) -> None:
        text = 'Here is my evaluation:\n{"correctness": 7, "completeness": 6, "relevance": 8, "reasoning": "decent"}\nDone.'
        score = parse_judge_response(text)
        assert score.correctness == 7
        assert score.reasoning == "decent"

    def test_missing_reasoning_defaults_empty(self) -> None:
        text = json.dumps({"correctness": 5, "completeness": 5, "relevance": 5})
        score = parse_judge_response(text)
        assert score.reasoning == ""

    def test_invalid_json_raises(self) -> None:
        with pytest.raises(ValueError, match="Could not parse"):
            parse_judge_response("this is not json at all")

    def test_missing_field_raises(self) -> None:
        text = json.dumps({"correctness": 5, "completeness": 5})
        with pytest.raises(ValueError, match="Missing required field"):
            parse_judge_response(text)

    def test_score_out_of_range_raises(self) -> None:
        text = json.dumps({
            "correctness": 11,
            "completeness": 5,
            "relevance": 5,
            "reasoning": "",
        })
        with pytest.raises(ValueError, match="must be 0-10"):
            parse_judge_response(text)

    def test_negative_score_raises(self) -> None:
        text = json.dumps({
            "correctness": -1,
            "completeness": 5,
            "relevance": 5,
            "reasoning": "",
        })
        with pytest.raises(ValueError, match="must be 0-10"):
            parse_judge_response(text)

    def test_float_integer_accepted(self) -> None:
        text = json.dumps({
            "correctness": 8.0,
            "completeness": 7.0,
            "relevance": 9.0,
            "reasoning": "",
        })
        score = parse_judge_response(text)
        assert score.correctness == 8

    def test_non_integer_float_rejected(self) -> None:
        text = json.dumps({
            "correctness": 8.5,
            "completeness": 7,
            "relevance": 9,
            "reasoning": "",
        })
        with pytest.raises(ValueError, match="must be an integer"):
            parse_judge_response(text)


class TestValidateScore:
    def test_valid_data(self) -> None:
        data = {"correctness": 8, "completeness": 7, "relevance": 9, "reasoning": "ok"}
        score = _validate_score(data)
        assert score.correctness == 8

    def test_non_dict_raises(self) -> None:
        with pytest.raises(ValueError, match="Expected JSON object"):
            _validate_score([1, 2, 3])

    def test_boundary_zero(self) -> None:
        data = {"correctness": 0, "completeness": 0, "relevance": 0}
        score = _validate_score(data)
        assert score.correctness == 0

    def test_boundary_ten(self) -> None:
        data = {"correctness": 10, "completeness": 10, "relevance": 10}
        score = _validate_score(data)
        assert score.correctness == 10

    def test_string_score_raises(self) -> None:
        data = {"correctness": "8", "completeness": 7, "relevance": 9}
        with pytest.raises(ValueError, match="must be an integer"):
            _validate_score(data)


class TestCalibrate:
    def _make_judge(self, c: int, cm: int, r: int) -> JudgeScore:
        return JudgeScore(correctness=c, completeness=cm, relevance=r, reasoning="")

    def test_perfect_agreement(self) -> None:
        judge = [self._make_judge(10, 10, 10), self._make_judge(5, 5, 5)]
        human = [
            {"correctness": 10, "completeness": 10, "relevance": 10},
            {"correctness": 5, "completeness": 5, "relevance": 5},
        ]
        result = calibrate(judge, human)
        assert result.mean_absolute_error == 0.0
        assert result.max_absolute_error == 0.0
        assert result.correlation == pytest.approx(1.0)

    def test_some_disagreement(self) -> None:
        judge = [self._make_judge(8, 7, 9)]
        human = [{"correctness": 10, "completeness": 7, "relevance": 8}]
        result = calibrate(judge, human)
        # Errors: |8-10|=2, |7-7|=0, |9-8|=1 → mean=1.0, max=2
        assert result.mean_absolute_error == pytest.approx(1.0)
        assert result.max_absolute_error == 2.0

    def test_per_example_breakdown(self) -> None:
        judge = [self._make_judge(8, 7, 9)]
        human = [{"correctness": 10, "completeness": 7, "relevance": 8}]
        result = calibrate(judge, human)
        assert len(result.per_example) == 1
        ex = result.per_example[0]
        assert ex["correctness_judge"] == 8
        assert ex["correctness_human"] == 10
        assert ex["correctness_error"] == 2
        assert ex["completeness_error"] == 0
        assert ex["relevance_error"] == 1

    def test_length_mismatch_raises(self) -> None:
        judge = [self._make_judge(5, 5, 5)]
        human = [
            {"correctness": 5, "completeness": 5, "relevance": 5},
            {"correctness": 3, "completeness": 3, "relevance": 3},
        ]
        with pytest.raises(ValueError, match="Length mismatch"):
            calibrate(judge, human)

    def test_empty_lists_raises(self) -> None:
        with pytest.raises(ValueError, match="empty"):
            calibrate([], [])

    def test_multiple_examples_correlation(self) -> None:
        # Perfect positive correlation
        judge = [
            self._make_judge(2, 2, 2),
            self._make_judge(5, 5, 5),
            self._make_judge(8, 8, 8),
        ]
        human = [
            {"correctness": 2, "completeness": 2, "relevance": 2},
            {"correctness": 5, "completeness": 5, "relevance": 5},
            {"correctness": 8, "completeness": 8, "relevance": 8},
        ]
        result = calibrate(judge, human)
        assert result.correlation == pytest.approx(1.0)


class TestPearsonCorrelation:
    def test_perfect_positive(self) -> None:
        assert _pearson_correlation([1, 2, 3], [2, 4, 6]) == pytest.approx(1.0)

    def test_perfect_negative(self) -> None:
        assert _pearson_correlation([1, 2, 3], [6, 4, 2]) == pytest.approx(-1.0)

    def test_zero_variance(self) -> None:
        assert _pearson_correlation([5, 5, 5], [1, 2, 3]) == 0.0

    def test_single_element(self) -> None:
        assert _pearson_correlation([1.0], [2.0]) == 0.0

    def test_empty(self) -> None:
        assert _pearson_correlation([], []) == 0.0


class TestJudgeSystemPrompt:
    def test_prompt_non_empty(self) -> None:
        assert len(JUDGE_SYSTEM_PROMPT) > 100

    def test_prompt_mentions_dimensions(self) -> None:
        assert "Correctness" in JUDGE_SYSTEM_PROMPT
        assert "Completeness" in JUDGE_SYSTEM_PROMPT
        assert "Relevance" in JUDGE_SYSTEM_PROMPT

    def test_prompt_mentions_json(self) -> None:
        assert "JSON" in JUDGE_SYSTEM_PROMPT

    def test_prompt_score_range(self) -> None:
        assert "0-10" in JUDGE_SYSTEM_PROMPT
