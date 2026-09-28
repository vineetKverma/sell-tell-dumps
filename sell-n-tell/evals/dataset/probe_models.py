"""Which models can this project actually call? (for picking the second labeller / judge)

    uv run python -m evals.dataset.probe_models
    uv run --with "anthropic[vertex]" python -m evals.dataset.probe_models --claude

Uses the same Vertex settings as the app (``app/.env``). Two steps:

1. List the Gemini models Vertex reports for this project.
2. Send every candidate a one-word prompt, in each region asked for. A model
   being listed does not mean the project may call it -- region, quota and org
   policy all get a say -- so only a real call counts as "available".

``--claude`` also probes Claude models through Vertex Model Garden. That needs
the anthropic SDK and the models enabled for the project; the model names tried
are best guesses, and the error text says which part failed.

Writes ``evals/data/out/model_probe.md`` (no customer data; safe to share).
"""

from __future__ import annotations

import argparse
import os
import time
from pathlib import Path

from evals.dataset.paths import APP_ENV, OUT

# Always tried, whether or not the listing returns them. Newer names are
# guesses; a "not found" for them is an answer, not a bug.
GEMINI_CANDIDATES = (
    "gemini-2.5-pro",
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
    "gemini-2.0-flash-001",
    "gemini-3-pro-preview",
    "gemini-3-flash-preview",
)
CLAUDE_CANDIDATES = (
    "claude-opus-5",
    "claude-sonnet-5",
    "claude-haiku-4-5@20251001",
    "claude-sonnet-4-5@20250929",
    "claude-opus-4-1@20250805",
)
CLAUDE_REGIONS = ("us-east5", "global")
# Listed models that cannot do plain text generation.
SKIP_WORDS = ("embedding", "tts", "live", "audio", "image", "imagen", "veo", "vision", "aqa")
PROMPT = "Reply with the single word OK."


def _short(exc: Exception) -> str:
    text = " ".join(str(exc).split())
    return f"{type(exc).__name__}: {text[:140]}"


def list_gemini(project: str, location: str) -> list[str]:
    from google import genai  # noqa: PLC0415

    client = genai.Client(vertexai=True, project=project, location=location)
    names = []
    try:
        for m in client.models.list(config={"query_base": True, "page_size": 200}):
            name = (m.name or "").rsplit("/", 1)[-1]
            if name.startswith("gemini") and not any(w in name for w in SKIP_WORDS):
                names.append(name)
    except Exception as exc:
        print(f"  (listing failed in {location}: {_short(exc)})")
    return sorted(set(names))


def probe_gemini(project: str, location: str, model: str) -> tuple[bool, float, str]:
    from google import genai  # noqa: PLC0415
    from google.genai import types  # noqa: PLC0415

    client = genai.Client(vertexai=True, project=project, location=location)
    start = time.perf_counter()
    try:
        resp = client.models.generate_content(
            model=model, contents=PROMPT,
            config=types.GenerateContentConfig(temperature=0.0, max_output_tokens=256),
        )
        return True, time.perf_counter() - start, (resp.text or "").strip()[:20]
    except Exception as exc:
        return False, time.perf_counter() - start, _short(exc)


def probe_claude(project: str, region: str, model: str) -> tuple[bool, float, str]:
    start = time.perf_counter()
    try:
        from anthropic import AnthropicVertex  # noqa: PLC0415

        client = AnthropicVertex(project_id=project, region=region)
        msg = client.messages.create(
            model=model, max_tokens=16, messages=[{"role": "user", "content": PROMPT}]
        )
        text = "".join(getattr(b, "text", "") for b in msg.content).strip()
        return True, time.perf_counter() - start, text[:20]
    except Exception as exc:
        return False, time.perf_counter() - start, _short(exc)


def main() -> None:
    from dotenv import load_dotenv  # noqa: PLC0415

    ap = argparse.ArgumentParser(description="Probe which LLMs this project can call.")
    ap.add_argument("--locations", nargs="+", help="Vertex regions to try (default: app region + global)")
    ap.add_argument("--claude", action="store_true", help="also probe Claude via Vertex Model Garden")
    ap.add_argument("--out", type=Path, default=OUT / "model_probe.md")
    args = ap.parse_args()

    load_dotenv(APP_ENV)
    project = os.getenv("GOOGLE_CLOUD_PROJECT")
    if not project:
        raise SystemExit(f"GOOGLE_CLOUD_PROJECT is not set (looked in {APP_ENV}).")
    app_region = os.getenv("GOOGLE_CLOUD_LOCATION") or "us-central1"
    locations = args.locations or list(dict.fromkeys([app_region, "global"]))

    lines = ["# Model probe (no customer data)", "", f"project: {project}", ""]
    for location in locations:
        print(f"\n== Gemini, {location}")
        listed = list_gemini(project, location)
        candidates = list(dict.fromkeys([*GEMINI_CANDIDATES, *listed]))
        lines += [f"## Gemini -- {location}", "",
                  f"listed by Vertex: {len(listed)}", "",
                  "| model | works | seconds | reply or error |", "|---|---|---|---|"]
        for model in candidates:
            ok, secs, detail = probe_gemini(project, location, model)
            mark = "yes" if ok else "no"
            print(f"  {mark:<4}{secs:>6.1f}s  {model:<28} {detail}")
            lines.append(f"| {model}{'' if model in listed else ' (not listed)'} | {mark} | {secs:.1f} | {detail} |")
        lines.append("")

    if args.claude:
        for region in CLAUDE_REGIONS:
            print(f"\n== Claude via Vertex, {region}")
            lines += [f"## Claude via Vertex -- {region}", "",
                      "| model | works | seconds | reply or error |", "|---|---|---|---|"]
            for model in CLAUDE_CANDIDATES:
                ok, secs, detail = probe_claude(project, region, model)
                mark = "yes" if ok else "no"
                print(f"  {mark:<4}{secs:>6.1f}s  {model:<28} {detail}")
                lines.append(f"| {model} | {mark} | {secs:.1f} | {detail} |")
            lines.append("")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\nWritten to {args.out}")


if __name__ == "__main__":
    main()
