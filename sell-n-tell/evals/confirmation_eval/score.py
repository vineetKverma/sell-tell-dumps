"""Scoring and metrics for Confirmation Intent Classifier evaluation (AIML-3012).

Computes accuracy, per-intent precision/recall, confusion matrix,
latency percentiles (p50, p95, max, avg), and the safety gating metrics:
False Confirm Rate (must be 0), API Crashes (0), and Timeouts (0).
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from typing import Any

INTENTS = ("confirm", "correction", "skip", "unclear")


@dataclass
class IntentMetrics:
    """Precision, recall, and counts for a single intent category."""

    intent: str
    tp: int = 0
    fp: int = 0
    fn: int = 0
    total_expected: int = 0

    @property
    def precision(self) -> float:
        denom = self.tp + self.fp
        return round(self.tp / denom, 4) if denom > 0 else 0.0

    @property
    def recall(self) -> float:
        denom = self.tp + self.fn
        return round(self.tp / denom, 4) if denom > 0 else 0.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return round(2 * p * r / (p + r), 4) if (p + r) > 0 else 0.0


@dataclass
class ConfirmationEvalScore:
    """Aggregated scorecard for a confirmation eval run."""

    total_cases: int
    correct: int
    accuracy: float
    per_intent: dict[str, IntentMetrics]
    confusion_matrix: dict[str, dict[str, int]]
    false_confirms: int
    false_confirm_rate: float
    errors: int
    gate_passed: bool
    failures: list[dict[str, Any]] = field(default_factory=list)
    error_cases: list[dict[str, Any]] = field(default_factory=list)
    api_errors: int = 0
    timeouts: int = 0
    timeout_cases: list[dict[str, Any]] = field(default_factory=list)
    p50_latency: float = 0.0
    p95_latency: float = 0.0
    max_latency: float = 0.0
    avg_latency: float = 0.0
    retried_count: int = 0
    exceeded_prod_timeout_count: int = 0

    def summary_markdown(self) -> str:
        """Format scorecard as human-readable markdown."""
        status = "PASSED" if self.gate_passed else "FAILED"
        lines = [
            "# Confirmation Classifier Eval Scorecard (AIML-3012)",
            f"\n**Gating Status:** {status}",
            "- **Target False Confirms:** 0 (100% confirmation safety)",
            f"- **Actual False Confirms:** {self.false_confirms} (Rate: {self.false_confirm_rate:.1%})",
            f"- **API Crashes / Errors:** {self.api_errors} (Target: 0)",
            f"- **Timeouts:** {self.timeouts} (Target: 0)",
            f"- **Overall Accuracy:** {self.accuracy:.1%} ({self.correct}/{self.total_cases})",
            "\n## Latency Profile (Model Calls Only)\n",
            f"- **p50 (Median):** {self.p50_latency:.2f}s",
            f"- **p95:** {self.p95_latency:.2f}s",
            f"- **Max:** {self.max_latency:.2f}s",
            f"- **Average:** {self.avg_latency:.2f}s",
            f"- **Calls Exceeding Prod Timeout (5.0s):** {self.exceeded_prod_timeout_count} (informational)",
            f"- **Cases Retried on Timeout:** {self.retried_count} (informational)",
            "\n## Per-Intent Metrics\n",
            "| Intent | Expected | Precision | Recall | F1-Score |",
            "| :--- | :--- | :--- | :--- | :--- |",
        ]
        for intent in INTENTS:
            m = self.per_intent[intent]
            lines.append(
                f"| `{intent}` | {m.total_expected} | {m.precision:.1%} | {m.recall:.1%} | {m.f1:.1%} |"
            )

        lines.extend([
            "\n## Confusion Matrix\n",
            "| Expected \\ Actual | confirm | correction | skip | unclear |",
            "| :--- | :--- | :--- | :--- | :--- |",
        ])
        for exp in INTENTS:
            row = [f"`{exp}`"]
            for act in INTENTS:
                row.append(str(self.confusion_matrix[exp].get(act, 0)))
            lines.append(f"| {' | '.join(row)} |")

        if self.timeout_cases:
            lines.extend([
                f"\n## Timeouts ({len(self.timeout_cases)})\n",
                "| ID | Transcript | Details | Latency |",
                "| :--- | :--- | :--- | :--- |",
            ])
            for to in self.timeout_cases:
                t = to["transcript"].replace("\n", "\\n").replace("|", "\\|")
                reason = str(to.get("reasoning") or "").replace("|", "\\|")
                lat = f"{to.get('latency_s', 0.0):.2f}s"
                lines.append(f"| {to['id']} | \"{t}\" | `{reason}` | {lat} |")

        if self.error_cases:
            lines.extend([
                f"\n## Classifier API Crashes / Errors ({len(self.error_cases)})\n",
                "| ID | Transcript | Error Details |",
                "| :--- | :--- | :--- |",
            ])
            for err in self.error_cases:
                t = err["transcript"].replace("\n", "\\n").replace("|", "\\|")
                reason = str(err.get("reasoning") or err.get("error_message") or "").replace("|", "\\|")
                lines.append(f"| {err['id']} | \"{t}\" | `{reason}` |")

        if self.failures:
            lines.extend([
                f"\n## Misclassifications ({len(self.failures)})\n",
                "| ID | Transcript | Expected | Actual | Category |",
                "| :--- | :--- | :--- | :--- | :--- |",
            ])
            for f in self.failures:
                t = f["transcript"].replace("\n", "\\n").replace("|", "\\|")
                lines.append(
                    f"| {f['id']} | \"{t}\" | `{f['expected']}` | `{f['actual']}` | {f.get('category', '')} |"
                )

        return "\n".join(lines)


def score_eval_results(results: list[dict[str, Any]]) -> ConfirmationEvalScore:
    """Compute score metrics from classified results."""
    total = len(results)
    correct = 0
    failures = []
    api_errors = 0
    timeouts = 0
    error_cases = []
    timeout_cases = []

    confusion = {exp: dict.fromkeys(INTENTS, 0) for exp in INTENTS}
    per_intent = {intent: IntentMetrics(intent=intent) for intent in INTENTS}

    false_confirms = 0
    total_non_confirms = 0

    latencies = [
        r["latency_s"]
        for r in results
        if "latency_s" in r and r["latency_s"] is not None
    ]
    if latencies:
        sorted_latencies = sorted(latencies)
        p50 = round(statistics.median(sorted_latencies), 3)
        idx_95 = int(len(sorted_latencies) * 0.95)
        p95 = round(sorted_latencies[min(idx_95, len(sorted_latencies) - 1)], 3)
        max_lat = round(max(sorted_latencies), 3)
        avg_lat = round(statistics.mean(sorted_latencies), 3)
    else:
        p50 = p95 = max_lat = avg_lat = 0.0

    for r in results:
        exp = r["expected_intent"]
        act = r["actual_intent"]

        reasoning = r.get("reasoning") or ""
        is_to = bool(r.get("is_timeout", False))
        is_err = bool(r.get("is_error", False)) or (
            reasoning.startswith("Classification failed")
            or reasoning.startswith("Empty response")
        )

        if is_to:
            timeouts += 1
            timeout_cases.append(r)
        elif is_err:
            api_errors += 1
            error_cases.append(r)

        if exp in confusion and act in confusion[exp]:
            confusion[exp][act] += 1

        if exp != "confirm":
            total_non_confirms += 1
            if act == "confirm":
                false_confirms += 1

        if exp == act:
            correct += 1
            if exp in per_intent:
                per_intent[exp].tp += 1
        else:
            failures.append({
                "id": r["id"],
                "transcript": r["transcript"],
                "expected": exp,
                "actual": act,
                "category": r.get("category", ""),
                "reasoning": reasoning,
            })
            if exp in per_intent:
                per_intent[exp].fn += 1
            if act in per_intent:
                per_intent[act].fp += 1

        if exp in per_intent:
            per_intent[exp].total_expected += 1

    accuracy = round(correct / total, 4) if total > 0 else 0.0
    fc_rate = (
        round(false_confirms / total_non_confirms, 4)
        if total_non_confirms > 0
        else 0.0
    )
    total_errors = api_errors + timeouts
    retried_count = sum(1 for r in results if r.get("retried"))
    exceeded_prod_timeout_count = sum(
        1 for r in results if r.get("exceeded_prod_timeout")
    )

    # Invariant: 0 False Confirms, 0 API Crashes, and 0 Timeouts allowed
    gate_passed = (false_confirms == 0) and (total_errors == 0)

    return ConfirmationEvalScore(
        total_cases=total,
        correct=correct,
        accuracy=accuracy,
        per_intent=per_intent,
        confusion_matrix=confusion,
        false_confirms=false_confirms,
        false_confirm_rate=fc_rate,
        errors=total_errors,
        gate_passed=gate_passed,
        failures=failures,
        error_cases=error_cases,
        api_errors=api_errors,
        timeouts=timeouts,
        timeout_cases=timeout_cases,
        p50_latency=p50,
        p95_latency=p95,
        max_latency=max_lat,
        avg_latency=avg_lat,
        retried_count=retried_count,
        exceeded_prod_timeout_count=exceeded_prod_timeout_count,
    )
