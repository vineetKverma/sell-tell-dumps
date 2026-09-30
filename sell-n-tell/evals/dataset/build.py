"""Build the golden answer key in one command (AIML-2898).

    uv run --with pandas --with pyxlsb --with openpyxl --with pyarrow \\
        python -m evals.dataset.build --fresh

Runs every step in order, each one the same script you could run on its own:

  1. sample        pick real notes, spread across industries and outcomes
  2. draft A       model A writes the answers for each note
  3. draft B       model B writes its own answers, without seeing A's
  4. adjudicate    where A and B agree the answer stands; a judge settles the rest
  5. import        save the final answer key and the report

Defaults: gemini-3.8-flash drafts, gemini-3.1-pro-preview gives the blind
second opinion, gemini-3.8-flash judges, all on the global endpoint. Pass
--model-a / --model-b / --judge-model / --location to change. ``--fresh`` deletes this
run's earlier outputs first so nothing is mixed in from before. ``--dry-run``
only prints the commands.

Outputs in evals/data/out/:
  reviewed_<name>.jsonl         the answer key (contains notes -- stays on this machine)
  adjudicate_<name>_summary.md  how often A and B agreed      (counts only, shareable)
  review_<name>_summary.md      how often A's answers held up  (counts only, shareable)
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from evals.dataset.paths import OUT

# Every file a run writes, by name -- all of it is removed by --fresh.
RUN_FILES = (
    "sample_{n}.jsonl", "sample_{n}_summary.md",
    "drafts_{n}.jsonl", "drafts_{n}_second.jsonl",
    "review_{n}.xlsx", "adjudicate_{n}_summary.md",
    "reviewed_{n}.jsonl", "review_{n}_summary.md",
)


def steps(args) -> list[tuple[str, list[str]]]:
    py = [sys.executable, "-m"]
    loc = ["--location", args.location]
    common = ["--name", args.name, "--out", str(args.out)]
    if args.sampler == "topup":
        pick = [*py, "evals.dataset.sample_topup", *common, "--per-field", str(args.per_field)]
    else:
        pick = [*py, "evals.dataset.sample", *common, "--per-vertical", str(args.per_vertical)]
    return [
        ("1/5 Pick notes", pick),
        ("2/5 Model A answers", [*py, "evals.dataset.draft_labels", *common,
                                 "--model", args.model_a, *loc]),
        ("3/5 Model B answers (blind)", [*py, "evals.dataset.draft_labels", *common,
                                         "--model", args.model_b, "--tag", "second", *loc]),
        ("4/5 Compare, judge the disagreements", [*py, "evals.dataset.adjudicate", *common,
                                                  "--second-tag", "second",
                                                  "--judge-model", args.judge_model, *loc, "--force"]),
        ("5/5 Save the answer key", [*py, "evals.dataset.review", "import", *common]),
    ]


# Loaded before any model call. If one file was copied and another was not, an
# import fails here in seconds instead of after twenty minutes of drafting.
PIPELINE_MODULES = (
    "evals.dataset.text", "evals.dataset.fields", "evals.dataset.source",
    "evals.dataset.answers", "evals.dataset.draft_labels", "evals.dataset.sample",
    "evals.dataset.adjudicate", "evals.dataset.review", "evals.dataset.compare_keys",
    "evals.dataset.sample_topup",
)


def preflight() -> str | None:
    """None if every pipeline module loads; otherwise the error text."""
    code = "import " + ", ".join(PIPELINE_MODULES)
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=False)
    if result.returncode == 0:
        return None
    return (result.stderr.strip().splitlines() or ["unknown import error"])[-1]


def remove_previous(out: Path, name: str) -> list[Path]:
    removed = []
    for pattern in RUN_FILES:
        path = out / pattern.format(n=name)
        if path.exists():
            path.unlink()
            removed.append(path)
    return removed


def main() -> None:
    ap = argparse.ArgumentParser(description="Build the golden answer key end to end.")
    ap.add_argument("--name", default="pilot")
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--per-vertical", type=int, default=2)
    # "topup": notes picked per missing vertical field (sample_topup.py)
    # instead of per outcome. Same seed in both builds -> the same notes.
    ap.add_argument("--sampler", choices=("outcome", "topup"), default="outcome")
    ap.add_argument("--per-field", type=int, default=6)
    # The 3.x models exist only on the global endpoint (checked with
    # probe_models); global use for sampled, masked notes is approved.
    ap.add_argument("--location", default="global")
    ap.add_argument("--model-a", default="gemini-3.8-flash")
    # B must differ from A: a blind second opinion from the same model mostly
    # agrees with itself and hides exactly the errors it is there to catch.
    ap.add_argument("--model-b", default="gemini-3.1-pro-preview")
    ap.add_argument("--judge-model", default="gemini-3.8-flash")
    ap.add_argument("--fresh", action="store_true", help="delete this run's earlier outputs first")
    ap.add_argument("--dry-run", action="store_true", help="print the commands, run nothing")
    args = ap.parse_args()

    if args.model_a == args.model_b:
        raise SystemExit(
            "--model-a and --model-b must be different models: the second labelling "
            "is only a check if it can disagree."
        )
    problem = preflight()
    if problem:
        raise SystemExit(
            f"The scripts don't load together: {problem}\n"
            "Some files in evals/dataset/ are out of date -- copy the whole folder "
            "again, then re-run. No model was called."
        )
    plan = steps(args)
    if args.dry_run:
        if args.fresh:
            print("would delete:", ", ".join(p.format(n=args.name) for p in RUN_FILES))
        for title, cmd in plan:
            print(f"{title}:\n    {subprocess.list2cmdline(cmd)}")
        return

    if args.fresh:
        for path in remove_previous(args.out, args.name):
            print(f"removed {path.name}")

    for title, cmd in plan:
        print(f"\n===== {title}")
        if subprocess.run(cmd, check=False).returncode != 0:
            raise SystemExit(f"\nStopped at '{title}'. Fix the error above, then re-run the same "
                             "command WITHOUT --fresh: finished steps are reused.")

    print("\n===== Done. Send back these two files (counts only):")
    print(f"    {args.out / f'adjudicate_{args.name}_summary.md'}")
    print(f"    {args.out / f'review_{args.name}_summary.md'}")
    print(f"The answer key itself stays here: {args.out / f'reviewed_{args.name}.jsonl'}")


if __name__ == "__main__":
    main()
