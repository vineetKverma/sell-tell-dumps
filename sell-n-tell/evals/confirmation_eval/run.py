"""Run Confirmation Intent Classifier Evaluation (AIML-3012).

CLI entrypoint to run the 110-case evaluation against Gemini Flash,
generate the scorecard, and enforce the 0% false confirm release gate.

Usage:
    uv run python -m evals.confirmation_eval.run
    uv run python -m evals.confirmation_eval.run --model gemini-3.8-flash
    uv run python -m evals.confirmation_eval.run --timeout 10.0
    uv run python -m evals.confirmation_eval.run --output evals/scorecard_confirmation.md
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
import time
from pathlib import Path

from app.voice_notes_agent.confirmation import (
    CONFIRMATION_TIMEOUT_S,
    DEFAULT_INTERPRET_MODEL,
    ConfirmationResult,
    fast_prefilter,
    interpret_async,
    prewarm_confirmation_client,
)
from evals.confirmation_eval.score import score_eval_results

logger = logging.getLogger(__name__)

DEFAULT_DATASET = Path(__file__).resolve().parent / "confirmation_eval_cases.json"
DEFAULT_EVAL_TIMEOUT_S = float(os.getenv("EVAL_CONFIRMATION_TIMEOUT_S", "10.0"))


def load_cases(path: Path) -> list[dict]:
    """Load JSON eval cases."""
    if not path.exists():
        raise FileNotFoundError(f"Eval dataset not found at {path}")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


async def run_eval_async(
    cases: list[dict],
    model: str = DEFAULT_INTERPRET_MODEL,
    client=None,
    timeout: float = DEFAULT_EVAL_TIMEOUT_S,
) -> list[dict]:
    """Execute classification across all cases using the production async path.

    Pre-warms the client to avoid cold-start livelock/timeouts on the first case,
    measures per-case latency, retries once on transient timeout, and isolates
    network timeouts from model crashes.
    """
    results = []
    total = len(cases)
    print(
        f"Running confirmation intent eval on {total} cases using {model} "
        f"(timeout={timeout}s, async)..."
    )

    # Pre-warm client to eliminate first-case cold-start initialization latency
    prewarm_confirmation_client(client)
    try:
        print("Pre-warming confirmation client with initial probe...")
        await asyncio.wait_for(
            interpret_async("yes", client=client, model=model),
            timeout=timeout,
        )
        print("Pre-warm complete.")
    except Exception as exc:
        print(f"Warning: Pre-warm probe encountered {type(exc).__name__}: {exc}")

    for i, c in enumerate(cases, 1):
        is_error = False
        is_timeout = False
        res = None

        pre = fast_prefilter(c["transcript"])
        if pre is not None:
            # Answered by fast_prefilter in 0ms without invoking the model
            res = pre
            latency_s = None
            retried = False
            exceeded_prod_timeout = False
        else:
            retried = False
            t0 = time.monotonic()
            try:
                res = await asyncio.wait_for(
                    interpret_async(c["transcript"], client=client, model=model),
                    timeout=timeout,
                )
                attempt_1_latency = time.monotonic() - t0
                exceeded_prod_timeout = attempt_1_latency > CONFIRMATION_TIMEOUT_S
                latency_s = round(attempt_1_latency, 3)
            except asyncio.TimeoutError:
                retried = True
                exceeded_prod_timeout = True
                logger.warning(
                    "Case %s timed out after %.1fs; retrying once...",
                    c["id"],
                    timeout,
                )
                try:
                    res = await asyncio.wait_for(
                        interpret_async(c["transcript"], client=client, model=model),
                        timeout=timeout,
                    )
                    total_latency = time.monotonic() - t0
                    latency_s = round(total_latency, 3)
                except asyncio.TimeoutError:
                    is_timeout = True
                    is_error = True
                    total_latency = time.monotonic() - t0
                    latency_s = round(total_latency, 3)
                    res = ConfirmationResult(
                        intent="unclear",
                        reasoning=f"Classification timed out after retry ({timeout}s)",
                    )
                except Exception as exc:
                    is_error = True
                    total_latency = time.monotonic() - t0
                    latency_s = round(total_latency, 3)
                    res = ConfirmationResult(
                        intent="unclear",
                        reasoning=f"Classification failed on retry: {type(exc).__name__}",
                    )
            except Exception as exc:
                is_error = True
                total_latency = time.monotonic() - t0
                latency_s = round(total_latency, 3)
                exceeded_prod_timeout = total_latency > CONFIRMATION_TIMEOUT_S
                res = ConfirmationResult(
                    intent="unclear",
                    reasoning=f"Classification failed with exception: {type(exc).__name__}",
                )

        if res.reasoning and (
            res.reasoning.startswith("Classification failed")
            or res.reasoning.startswith("Empty response")
        ):
            is_error = True

        results.append({
            "id": c["id"],
            "transcript": c["transcript"],
            "expected_intent": c["expected_intent"],
            "actual_intent": res.intent,
            "category": c.get("category", ""),
            "correction_detail": res.correction_detail,
            "reasoning": res.reasoning,
            "latency_s": latency_s,
            "retried": retried,
            "exceeded_prod_timeout": exceeded_prod_timeout,
            "is_error": is_error,
            "is_timeout": is_timeout,
        })
        if i % 20 == 0 or i == total:
            print(f"  Processed {i}/{total} cases...")

    return results


def run_eval(
    cases: list[dict],
    model: str = DEFAULT_INTERPRET_MODEL,
    client=None,
    timeout: float = DEFAULT_EVAL_TIMEOUT_S,
) -> list[dict]:
    """Synchronous wrapper for run_eval_async."""
    return asyncio.run(
        run_eval_async(cases, model=model, client=client, timeout=timeout)
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run confirmation intent evaluation (AIML-3012)."
    )
    parser.add_argument(
        "--dataset",
        type=Path,
        default=DEFAULT_DATASET,
        help="Path to labeled evaluation cases JSON file.",
    )
    parser.add_argument(
        "--model",
        type=str,
        default=DEFAULT_INTERPRET_MODEL,
        help=f"Gemini model for classification (default: {DEFAULT_INTERPRET_MODEL}).",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_EVAL_TIMEOUT_S,
        help=f"Per-case timeout in seconds (default: {DEFAULT_EVAL_TIMEOUT_S}s).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Optional path to write markdown scorecard.",
    )

    args = parser.parse_args()

    cases = load_cases(args.dataset)
    results = run_eval(cases, model=args.model, timeout=args.timeout)
    scorecard = score_eval_results(results)

    summary_md = scorecard.summary_markdown()
    print("\n" + summary_md)

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(summary_md, encoding="utf-8")
        print(f"\nScorecard written to: {args.output}")

    if not scorecard.gate_passed:
        if scorecard.false_confirms > 0:
            print(
                f"\n[GATE FAILED] Observed {scorecard.false_confirms} false confirms. Target is 0.",
                file=sys.stderr,
            )
        if scorecard.api_errors > 0:
            print(
                f"\n[GATE FAILED] Observed {scorecard.api_errors} classifier API crashes/errors. Target is 0.",
                file=sys.stderr,
            )
        if scorecard.timeouts > 0:
            print(
                f"\n[GATE FAILED] Observed {scorecard.timeouts} classifier timeouts. Target is 0.",
                file=sys.stderr,
            )
        return 1

    print("\n[GATE PASSED] 0 False Confirms, 0 Timeouts & 0 Errors! Safe to proceed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
