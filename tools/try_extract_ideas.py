"""A quick test of the rules the business answers decide (AIML-3152), without
changing the repo: each is switched on in memory, then the normal extract
eval runs. Evidence by sentence number is in the code itself now.

    cd <repo>
    uv run python C:\\tmp\\try_extract_ideas.py --discussed --quote-cue -- \
        --model gemini-3.8-flash --thinking low --allow-labelling-model --dispositions

  --discussed   the topic rule follows the answer key's: something happened about the
                campaign (presented, the customer's reaction, material left)
  --refusal     the same without "material left": only the customer's reaction is added
  --quote-cue   code 1 (Create Opportunity) also lists a quote given
  --own-words   a field's value is given in the rep's own words (not an answer-dependent
                rule: a check on whether field values drifted into paraphrase)

  --one-line    the notes as a spoken transcript with no punctuation: line breaks and the
                marks at the end of words are removed, so every note is one sentence
  --paragraph   the numbered sentences are shown on one line, not one per line (the layout
                that kept IS-003 a Meeting)
  --categories  the outcome (U-04) and issue (U-07) fields start with the business sheet's
                category word ("order placed: ...", "mispick: ...")
  --chunk       a sentence over 25 words is split into pieces of at most 25 words (a
                fallback for text with no sentence ends; scripts that read the run, such
                as sentence_check.py, do not know about it)

Which answer switches on what: material left counts as discussed -> --discussed;
it does not, but a refusal or another brand does -> --refusal; a quote is
code 1 -> --quote-cue.

Everything after "--" goes to evals.extract_eval.run unchanged. The run folder
gets an ideas.txt naming what was on, since summary.json cannot know.
"""

import os
import re
import sys
from pathlib import Path

sys.path.insert(0, os.getcwd())

import importlib  # noqa: E402

# The module, not the function of the same name that the package exports.
ex = importlib.import_module("app.extraction.extract")

IDEAS = ("--discussed", "--refusal", "--quote-cue", "--own-words", "--one-line", "--chunk", "--paragraph", "--categories")
CHUNK_WORDS = 25


def swap(text: str, old: str, new: str) -> str:
    """Replace ``old`` once, whatever its line breaks; fail loudly if the
    wording moved, so a stale script cannot run a no-op test."""
    pattern = r"\s+".join(re.escape(w) for w in old.split())
    out, n = re.subn(pattern, lambda _: new, text)
    assert n == 1, f"wording not found exactly once ({n}): {old[:60]}..."
    return out


# --- idea 1: the answer key's meaning of "discussed" --------------------------

def discussed(left_material: bool = True) -> None:
    """``left_material`` False: the customer's reaction counts, material left
    with no conversation does not (the rule as it is today for that case)."""
    left = ", or the rep leaving its\n  material" if left_material else ""
    ex.RULES = swap(
        ex.RULES,
        "is \"discussed\" ONLY if the rep talks about that campaign's offer or its products; a "
        "related but different product does not count (use the description to tell).",
        "is \"discussed\" when the dictation records something that happened about that campaign's\n"
        "  offer, its products or its brand: the rep presenting it, or the customer's reaction to it\n"
        f"  (including a refusal, or preferring another brand or vendor){left}. A related but\n"
        "  different product does not count (use the description to tell).")


# --- idea 2: a quote given is code 1 ------------------------------------------

def quote_cue(run) -> None:
    load = run.load_dispositions

    def with_cue(*args, **kwargs):
        codes = load(*args, **kwargs)
        assert codes[1].endswith(")"), codes[1]
        codes[1] = codes[1][:-1] + "; gave a quote; quoted)"
        return codes
    run.load_dispositions = with_cue


def own_words() -> None:
    ex.RULES = swap(
        ex.RULES,
        "Must-capture fields: fill a field only when the rep states it.",
        "Must-capture fields: fill a field only when the rep states it, and give the value in\n"
        "  the rep's own words, not reworded.")


def flatten(note: str) -> str:
    """The note as unpunctuated speech: no line breaks, no marks at the end of a
    word ("3.5" and "$3,000" keep theirs)."""
    return " ".join(re.sub(r"[.!?;:,]+(?=\s|$)", "", note).split())


def one_line(run) -> None:
    import dataclasses
    load = run.set_cases

    def flat(*args, **kwargs):
        return [dataclasses.replace(c, note=flatten(c.note)) for c in load(*args, **kwargs)]
    run.set_cases = flat


def chunked(units: list[str], size: int = CHUNK_WORDS) -> list[str]:
    out = []
    for unit in units:
        words = unit.split()
        if len(words) <= size:
            out.append(unit)
            continue
        pieces = -(-len(words) // size)                  # as few pieces as fit, of even length
        step = -(-len(words) // pieces)
        out += [" ".join(words[i:i + step]) for i in range(0, len(words), step)]
    return out


def chunk() -> None:
    base = ex.sentences
    ex.sentences = lambda note: chunked(base(note))


def categories() -> None:
    ex.RULES = swap(
        ex.RULES,
        "- Next step (U-09): when the rep says",
        "- Commercial outcome (U-04) and service issue (U-07) are categories. Start the value with\n"
        "  the category, in these words -- U-04: order placed, quote created, quote pending approval\n"
        "  or return/credit; U-07: backorder, mispick, damage, missing item, ETA request or warranty\n"
        "  -- then the detail after a colon (\"order placed: PO received\", \"mispick: wrong keypad\n"
        "  sent\"). If no category fits what the rep said, describe it without one.\n"
        "- Next step (U-09): when the rep says")


def paragraph() -> None:
    build = ex.build_prompt

    def on_one_line(*args, **kwargs):
        head, body = build(*args, **kwargs).split("Dictation:\n<<<\n", 1)
        return head + "Dictation:\n<<<\n" + body[:-len("\n>>>")].replace("\n", " ") + "\n>>>"
    ex.build_prompt = on_one_line


def main() -> None:
    args = sys.argv[1:]
    cut = args.index("--") if "--" in args else len(args)
    on, rest = [a for a in args[:cut] if a in IDEAS], args[cut + 1:]
    unknown = [a for a in args[:cut] if a not in IDEAS]
    assert on and not unknown, f"choose from {IDEAS}, then '--' and the run's own arguments; got {unknown}"

    from evals.extract_eval import run
    assert not {"--discussed", "--refusal"} <= set(on), "--discussed already includes --refusal"
    if "--discussed" in on:
        discussed()
    if "--refusal" in on:
        discussed(left_material=False)
    if "--quote-cue" in on:
        quote_cue(run)
    if "--own-words" in on:
        own_words()
    if "--one-line" in on:
        one_line(run)
    if "--chunk" in on:
        chunk()
    if "--paragraph" in on:
        paragraph()
    if "--categories" in on:
        categories()
    print(f"ideas on: {' '.join(on)}\n", flush=True)
    before = set(run.RUNS.glob("extract-*"))
    sys.argv = ["run", *rest]
    try:
        run.main()
    finally:
        for folder in set(run.RUNS.glob("extract-*")) - before:
            Path(folder, "ideas.txt").write_text(" ".join(on) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
