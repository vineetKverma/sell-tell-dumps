"""Unit tests for Confirmation Eval Scorer and Gating (AIML-3012)."""

from __future__ import annotations

from pathlib import Path

from evals.confirmation_eval.run import load_cases
from evals.confirmation_eval.score import score_eval_results


class TestConfirmationScorer:
    """Test eval metrics and gating rules."""

    def test_perfect_run_passes_gate(self):
        results = [
            {"id": "1", "transcript": "Yeah", "expected_intent": "confirm", "actual_intent": "confirm"},
            {"id": "2", "transcript": "Change date", "expected_intent": "correction", "actual_intent": "correction"},
            {"id": "3", "transcript": "Don't save", "expected_intent": "skip", "actual_intent": "skip"},
            {"id": "4", "transcript": "...", "expected_intent": "unclear", "actual_intent": "unclear"},
        ]
        score = score_eval_results(results)
        assert score.accuracy == 1.0
        assert score.false_confirms == 0
        assert score.false_confirm_rate == 0.0
        assert score.errors == 0
        assert score.gate_passed is True

    def test_classifier_error_fails_gate(self):
        # 0 false confirms, but a call crashed and degraded to unclear
        results = [
            {"id": "1", "transcript": "Yeah", "expected_intent": "confirm", "actual_intent": "confirm"},
            {"id": "2", "transcript": "Change date", "expected_intent": "unclear", "actual_intent": "unclear", "is_error": True, "reasoning": "Classification failed: NetworkError"},
        ]
        score = score_eval_results(results)
        assert score.false_confirms == 0
        assert score.errors == 1
        assert score.gate_passed is False
        assert len(score.error_cases) == 1

    def test_false_confirm_fails_gate(self):
        # User said "Yes, but change date" (correction), but classifier returned "confirm"
        results = [
            {"id": "1", "transcript": "Yeah", "expected_intent": "confirm", "actual_intent": "confirm"},
            {"id": "2", "transcript": "Yes, but change date", "expected_intent": "correction", "actual_intent": "confirm"},
            {"id": "3", "transcript": "Don't save", "expected_intent": "skip", "actual_intent": "skip"},
        ]
        score = score_eval_results(results)
        assert score.false_confirms == 1
        assert score.gate_passed is False
        assert len(score.failures) == 1

    def test_noise_classified_as_confirm_fails_gate(self):
        # User coughed / ambient noise, but classifier guessed "confirm"
        results = [
            {"id": "1", "transcript": "[cough]", "expected_intent": "unclear", "actual_intent": "confirm"},
        ]
        score = score_eval_results(results)
        assert score.false_confirms == 1
        assert score.gate_passed is False

    def test_confusion_matrix_and_markdown(self):
        results = [
            {"id": "1", "transcript": "Yeah", "expected_intent": "confirm", "actual_intent": "confirm"},
            {"id": "2", "transcript": "No save", "expected_intent": "skip", "actual_intent": "skip"},
            {"id": "3", "transcript": "Wait", "expected_intent": "unclear", "actual_intent": "unclear"},
        ]
        score = score_eval_results(results)
        md = score.summary_markdown()
        assert "PASSED" in md
        assert "| `confirm` |" in md
        assert "Confusion Matrix" in md

    def test_timeout_fails_gate_and_records_timeout_case(self):
        # Classification timed out on dev network
        results = [
            {"id": "1", "transcript": "Yeah", "expected_intent": "confirm", "actual_intent": "confirm"},
            {
                "id": "2",
                "transcript": "Change date",
                "expected_intent": "unclear",
                "actual_intent": "unclear",
                "is_timeout": True,
                "reasoning": "Classification timed out after retry (10.0s)",
                "latency_s": 10.05,
            },
        ]
        score = score_eval_results(results)
        assert score.false_confirms == 0
        assert score.timeouts == 1
        assert score.api_errors == 0
        assert score.errors == 1
        assert score.gate_passed is False
        assert len(score.timeout_cases) == 1
        assert score.timeout_cases[0]["id"] == "2"

    def test_latency_metrics_and_markdown_summary(self):
        results = [
            {"id": "1", "transcript": "Yeah", "expected_intent": "confirm", "actual_intent": "confirm", "latency_s": 1.0},
            {"id": "2", "transcript": "No", "expected_intent": "skip", "actual_intent": "skip", "latency_s": 2.0},
            {"id": "3", "transcript": "Wait", "expected_intent": "unclear", "actual_intent": "unclear", "latency_s": 3.0},
        ]
        score = score_eval_results(results)
        assert score.p50_latency == 2.0
        assert score.max_latency == 3.0
        assert score.avg_latency == 2.0
        md = score.summary_markdown()
        assert "Latency Profile" in md
        assert "- **p50 (Median):** 2.00s" in md

    def test_reasoning_mentioning_timeout_does_not_false_timeout(self):
        # Transcripts or LLM reasoning mentioning "timed out" shouldn't trigger timeout failure
        results = [
            {
                "id": "1",
                "transcript": "the call timed out, yes save it",
                "expected_intent": "confirm",
                "actual_intent": "confirm",
                "reasoning": "User mentions that the call timed out, but clearly confirms saving",
                "is_timeout": False,
                "latency_s": 0.45,
            },
        ]
        score = score_eval_results(results)
        assert score.timeouts == 0
        assert score.errors == 0
        assert score.gate_passed is True

    def test_prefiltered_none_latency_excluded_and_prod_timeout_tracked(self):
        results = [
            # Prefiltered fast cases with latency_s=None
            {"id": "1", "transcript": "yes", "expected_intent": "confirm", "actual_intent": "confirm", "latency_s": None},
            {"id": "2", "transcript": "", "expected_intent": "unclear", "actual_intent": "unclear", "latency_s": None},
            # Model calls
            {
                "id": "3",
                "transcript": "go ahead and commit everything",
                "expected_intent": "confirm",
                "actual_intent": "confirm",
                "latency_s": 6.2,
                "exceeded_prod_timeout": True,
                "retried": True,
            },
            {
                "id": "4",
                "transcript": "nope leave it out",
                "expected_intent": "skip",
                "actual_intent": "skip",
                "latency_s": 1.8,
            },
        ]
        score = score_eval_results(results)
        # Latency calculations should only reflect id 3 and id 4 (1.8s, 6.2s)
        assert score.p50_latency == 4.0
        assert score.max_latency == 6.2
        assert score.exceeded_prod_timeout_count == 1
        assert score.retried_count == 1
        md = score.summary_markdown()
        assert "- **Calls Exceeding Prod Timeout (5.0s):** 1 (informational)" in md
        assert "- **Cases Retried on Timeout:** 1 (informational)" in md

    def test_dataset_contains_at_least_100_cases(self):
        dataset_path = (
            Path(__file__).resolve().parents[1]
            / "evals"
            / "confirmation_eval"
            / "confirmation_eval_cases.json"
        )
        cases = load_cases(dataset_path)
        assert len(cases) >= 100
        intents = {c["expected_intent"] for c in cases}
        assert intents == {"confirm", "correction", "skip", "unclear"}
