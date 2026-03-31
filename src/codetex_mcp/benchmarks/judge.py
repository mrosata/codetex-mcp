"""LLM-as-judge scoring system for coding task evaluation.

Provides prompt templates and response parsing for using an LLM
to evaluate coding task completion quality across multiple dimensions.

Pure functions — prompt builders and parsers have no I/O.
The `judge_score` async function requires an LLM provider.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

JUDGE_SYSTEM_PROMPT = """\
You are an expert code reviewer evaluating whether a coding task was completed correctly.
You will be given a task description and a candidate response (code).
Score the response on three dimensions, each from 0 to 10.

Respond ONLY with a JSON object in exactly this format:
{
  "correctness": <int 0-10>,
  "completeness": <int 0-10>,
  "relevance": <int 0-10>,
  "reasoning": "<brief explanation>"
}

Scoring guidelines:

**Correctness** (0-10): Does the code work as intended?
- 10: Perfectly correct, handles edge cases
- 7-9: Correct for common cases, minor issues
- 4-6: Partially correct, some bugs or logic errors
- 1-3: Mostly incorrect, fundamental flaws
- 0: Completely wrong or does not compile/parse

**Completeness** (0-10): Does the response fully address the task?
- 10: All requirements addressed, nothing missing
- 7-9: Most requirements met, minor omissions
- 4-6: About half the requirements addressed
- 1-3: Major parts missing
- 0: Empty or unrelated response

**Relevance** (0-10): Is the response focused on the task?
- 10: Precisely addresses the task, no extraneous content
- 7-9: Mostly on-topic with minor tangents
- 4-6: Somewhat related but includes significant noise
- 1-3: Largely off-topic
- 0: Completely unrelated"""


@dataclass
class JudgeScore:
    """Result from LLM-as-judge evaluation."""

    correctness: int
    completeness: int
    relevance: int
    reasoning: str

    @property
    def aggregate(self) -> float:
        """Weighted aggregate score normalized to [0.0, 1.0].

        Weights: correctness 0.5, completeness 0.3, relevance 0.2.
        """
        return (
            0.5 * self.correctness + 0.3 * self.completeness + 0.2 * self.relevance
        ) / 10.0


def build_judge_prompt(task: str, response: str, context: str | None = None) -> str:
    """Build the evaluation prompt for the LLM judge.

    Args:
        task: The coding task description.
        response: The candidate code response to evaluate.
        context: Optional additional context provided to the original task.

    Returns:
        A formatted prompt string for the judge LLM.
    """
    parts: list[str] = []
    parts.append("## Task")
    parts.append(task)
    parts.append("")

    if context:
        parts.append("## Context Provided")
        parts.append(context)
        parts.append("")

    parts.append("## Candidate Response")
    parts.append("```")
    parts.append(response)
    parts.append("```")
    parts.append("")
    parts.append("Evaluate the candidate response and return the JSON score object.")

    return "\n".join(parts)


def parse_judge_response(text: str) -> JudgeScore:
    """Parse the LLM judge's JSON response into a JudgeScore.

    Extracts JSON from the response text, handling both raw JSON
    and JSON embedded in markdown code blocks.

    Args:
        text: Raw LLM response text.

    Returns:
        Parsed JudgeScore with validated dimension scores.

    Raises:
        ValueError: If the response cannot be parsed or scores are invalid.
    """
    # Try to extract JSON from markdown code block first
    code_block = re.search(r"```(?:json)?\s*\n?(.*?)\n?\s*```", text, re.DOTALL)
    if code_block:
        json_str = code_block.group(1).strip()
    else:
        # Try the whole text as JSON
        json_str = text.strip()

    try:
        data = json.loads(json_str)
    except json.JSONDecodeError as e:
        # Try to find any JSON object in the text
        obj_match = re.search(r"\{[^{}]*\}", text, re.DOTALL)
        if obj_match:
            try:
                data = json.loads(obj_match.group(0))
            except json.JSONDecodeError:
                raise ValueError(f"Could not parse judge response as JSON: {e}") from e
        else:
            raise ValueError(f"Could not parse judge response as JSON: {e}") from e

    return _validate_score(data)


def _validate_score(data: Any) -> JudgeScore:
    """Validate and construct a JudgeScore from parsed JSON data.

    Raises:
        ValueError: If required fields are missing or scores out of range.
    """
    if not isinstance(data, dict):
        raise ValueError(f"Expected JSON object, got {type(data).__name__}")

    required = ("correctness", "completeness", "relevance")
    for field in required:
        if field not in data:
            raise ValueError(f"Missing required field: {field}")

    scores: dict[str, int] = {}
    for field in required:
        val = data[field]
        if isinstance(val, float) and val == int(val):
            val = int(val)
        if not isinstance(val, int):
            raise ValueError(
                f"Field '{field}' must be an integer, got {type(val).__name__}"
            )
        if val < 0 or val > 10:
            raise ValueError(f"Field '{field}' must be 0-10, got {val}")
        scores[field] = val

    reasoning = str(data.get("reasoning", ""))

    return JudgeScore(
        correctness=scores["correctness"],
        completeness=scores["completeness"],
        relevance=scores["relevance"],
        reasoning=reasoning,
    )


@dataclass
class CalibrationResult:
    """Result of calibrating judge scores against human evaluations."""

    mean_absolute_error: float
    max_absolute_error: float
    correlation: float
    per_example: list[dict[str, Any]]


def calibrate(
    judge_scores: list[JudgeScore],
    human_scores: list[dict[str, int]],
) -> CalibrationResult:
    """Compare judge scores against human-evaluated reference scores.

    Args:
        judge_scores: Scores produced by the LLM judge.
        human_scores: Reference scores with 'correctness', 'completeness',
            'relevance' integer fields (0-10 scale).

    Returns:
        CalibrationResult with error statistics and per-example breakdown.

    Raises:
        ValueError: If list lengths don't match or lists are empty.
    """
    if len(judge_scores) != len(human_scores):
        raise ValueError(
            f"Length mismatch: {len(judge_scores)} judge scores "
            f"vs {len(human_scores)} human scores"
        )
    if not judge_scores:
        raise ValueError("Cannot calibrate with empty score lists")

    dimensions = ("correctness", "completeness", "relevance")
    all_errors: list[float] = []
    per_example: list[dict[str, Any]] = []

    judge_agg: list[float] = []
    human_agg: list[float] = []

    for i, (js, hs) in enumerate(zip(judge_scores, human_scores)):
        example: dict[str, Any] = {"index": i}
        example_errors: list[float] = []

        for dim in dimensions:
            j_val = getattr(js, dim)
            h_val = hs[dim]
            err = abs(j_val - h_val)
            example_errors.append(err)
            all_errors.append(err)
            example[f"{dim}_judge"] = j_val
            example[f"{dim}_human"] = h_val
            example[f"{dim}_error"] = err

        example["mean_error"] = sum(example_errors) / len(example_errors)
        per_example.append(example)

        # Aggregate scores for correlation
        judge_agg.append(js.aggregate * 10.0)  # scale back to 0-10
        human_agg.append(
            0.5 * hs["correctness"] + 0.3 * hs["completeness"] + 0.2 * hs["relevance"]
        )

    mae = sum(all_errors) / len(all_errors)
    max_err = max(all_errors)
    corr = _pearson_correlation(judge_agg, human_agg)

    return CalibrationResult(
        mean_absolute_error=mae,
        max_absolute_error=max_err,
        correlation=corr,
        per_example=per_example,
    )


def _pearson_correlation(x: list[float], y: list[float]) -> float:
    """Compute Pearson correlation coefficient between two lists.

    Returns 0.0 if either list has zero variance.
    """
    n = len(x)
    if n < 2:
        return 0.0

    mean_x = sum(x) / n
    mean_y = sum(y) / n

    cov = sum((xi - mean_x) * (yi - mean_y) for xi, yi in zip(x, y))
    var_x = sum((xi - mean_x) ** 2 for xi in x)
    var_y = sum((yi - mean_y) ** 2 for yi in y)

    denom = (var_x * var_y) ** 0.5
    if denom == 0.0:
        return 0.0
    return cov / denom
