# AIML-2702 pivot — eval harness on ADK native, with a new golden dataset first

Draft story text for Jira. Two stories: a new dataset story that has to land
first, and AIML-2702 rewritten around ADK native evaluation.

---

## AIML-2898 — Curate the vertical golden dataset

### Description

The eval harness needs ground truth, and there is none that fits the current
requirements: the pre-call topic registry, verticals and must-capture fields are
all new.

Build a new golden dataset from the source data behind the must-capture
sheet, labelled against the Campaign Topics list, the disposition registry, and
all 65 must-capture fields, with evaluation metrics categorised by priority.

### Inputs

| Input | Source |
|---|---|
| Post-call notes + pre-call plans | `Event-9_1_2026.xlsb`, the source data named in the must-capture sheet (445,015 calls, 435,044 with a note). Columns: `Account.Industry` (vertical), `Pre-call plan objective`, `Selected_PCP_Topics__c` (comma-separated topic titles), `Description` (the post-call note) |
| Topic registry | Campaign Topics list (`Name`, `Description`, `Industry__c`) |
| Disposition registry | `resources/dispositions.yaml` (codes 1–10, 99) |
| Must-capture fields | `must-capture-fields.xlsx`, all 65 fields with their priority (P1/P2/P3) |

### Each record contains

1. `vertical` and `campaign_type`
2. Planned topics, as `Name` values from the topic registry
3. The note, used as the dictation text
4. Expected `event_type`
5. For each planned topic: expected topic mapping, `discussed`, disposition code
   (including 99, and "not discussed")
6. Expected must-capture values for the 11 universal fields plus the 9 fields
   of the record's vertical (20 per record), each as a value **or an explicit
   "not stated"**, tagged with the field's priority

The explicit "not stated" is what lets the harness measure fabrication, meaning
the agent filling a field the rep never mentioned. A blank would not distinguish
that from a missing label.

### Stratification

Sample stratified, not the first N rows:

- By vertical, all six (MH, HS, HL, IS, TR, IN). Proposal: at least 15 per
  vertical, 90 in total.
- Within each vertical, cover: order placed, quote created, no contact made,
  multi-topic, very short notes (under 40 characters), and notes that mention none
  of the planned topics.

A per-topic quota is no longer possible: there are 1,967 distinct topic strings.

### Labelling method

Model-labelled and cross-checked, with no human review step. Each record is
labelled by two independent builds with the models' roles swapped. In each
build one model drafts the answers, a different model answers blind, and a
judge model settles the disagreements. Where the two builds agree, that is the
answer. Where they disagree, the item is marked contested and left out of
scoring. The models that built each record are recorded on it.

### Acceptance criteria

1. At least 90 records, at least 15 per vertical, covering every stratum above.
2. Every record carries all six fields, including all 20 must-capture labels
   that apply to its vertical. Every label is either a value or "not stated",
   and carries its field's priority.
3. Every record is labelled by two independent model builds with roles
   swapped. The builds agree on at least 95% of answers. Disagreements are
   marked contested and excluded from scoring, and the models used are
   recorded on every record.
4. Carriage-return artefacts are stripped and encoding is verified clean. The
   evidence base shows these artefacts in 3–13% of notes, and the earlier FAR
   export had mojibake.
5. Customer and contact names are removed, or the set is kept out of git.
6. The output loads directly as ADK eval cases (see AIML-2702), with no
   hand-conversion step.

---

## AIML-2702 - Eval harness (rewritten)

**Title:** Eval harness: event type, topic mapping, disposition and
must-capture accuracy

### Description

Build the harness that runs the agent on the AIML-2898 answer key
(`golden_v1`, 90 cases) and scores it.

The agent's whole CRM record is the set of arguments to one tool call,
`stage_visit_notes(event_type, topics, ...)`. So every accuracy question is a
comparison of that call's actual arguments against the expected ones in the
answer key.

**How the agent is run.** The agent uses a live audio model
(`gemini-live-2.5-flash-native-audio`). That model cannot answer an ordinary
text request, and the ADK version on the test environment (2.1.0) has no live
evaluation (`live_model_config` arrived in a later version). So the harness
drives the running app through its own contract, the same way
`scripts/ws_smoke_test.py` already does: `POST /api/sessions` with the case's
planned topics, then the WebSocket with text turns. The rep's side is scripted:
the note as the dictation, "I didn't get to that" when the agent reminds about
a planned topic, then "Save it". The last `stage_visit_notes` call is the
record that gets scored. This tests the production agent, model, turn guard and
session service with no dependency change. The answer key is in ADK's eval-set
format, so the same file loads into `adk eval` once ADK is upgraded.

**How it is scored.** The scoring functions are plain Python, written with
ADK's custom-metric signature, so they register with ADK unchanged later.
Tool-trajectory exact match is not used: it compares every argument
character for character, including the free-text summary, so it can never
pass.

### Scorecard

Reported per case, per vertical and in aggregate. Field-level scores are also
grouped by priority (P1 / P2 / P3), so a P1 miss is never averaged away by P3
hits.

| Metric | What it measures |
|---|---|
| Event-type accuracy | Meeting / Phone Call / On-site visit, including "met with" -> Meeting |
| Topic mapping accuracy | Each planned topic matched to the right entry, with no duplicate rows (the known F7 bug) |
| Disposition accuracy | Correct code per discussed topic, including 99 |
| Summary faithfulness | The agent's summary is grounded in the note (LLM judge; the one metric that makes extra model calls) |
| Extraction precision / recall | Per must-capture field, rolled up per priority and per vertical |
| Fabrication rate | A value produced where the answer key says "not stated" |

Scoring rules, fixed by the answer key:
- Items marked **contested** in the key are skipped.
- A case whose expected event type is "not stated" is not scored on event type.
- A field with no stated example in the key reports recall as n/a, not 0.

### What the first baseline will and will not show

Today's agent does not capture the must-capture fields at all. That is the
vertical build, which is not ticketed yet. So the first baseline scores event
type, topic mapping, disposition and summary. Field extraction shows "not
captured" until the agent is built to capture fields. The same harness then
measures that build without any code change.

### Acceptance criteria

1. One documented command runs the golden_v1 eval set against the live agent,
   verified in a clean environment.
2. Each run produces the scorecard above, per case, per vertical and aggregate,
   with field-level scores also broken down by priority (P1 / P2 / P3).
3. Every failure shows expected against actual: topic, disposition, event type,
   field values.
4. The harness refuses to run unless the eval set is the full golden_v1
   (90 unique cases). golden_v1 runs end to end and produces a recorded
   baseline.
5. Scores are comparable across runs. Run-to-run variance is measured by running
   the same config N times (N >= 3) and documented, so a real change can be told
   apart from model noise.
6. The scoring functions have unit tests against hand-built agent calls. Those
   tests need no model and no credentials, and run with `uv run pytest tests/`.

### Changes from the earlier draft

- **Runner:** drives the live agent directly instead of `adk eval` /
  `AgentEvaluator`, because the test environment's ADK (2.1.0) has no live
  evaluation and the agent's model is live-only.
- **Metrics:** custom scoring functions instead of ADK's built-in tool
  trajectory match, which cannot pass on free-text arguments.
- **Seed set dropped:** golden_v1 exists, so the seven smoke-test scenarios are
  no longer needed as a stand-in.

### Out of scope

- Simulated audio users. Needs the ADK upgrade that adds live evaluation.
- Making the agent capture the must-capture fields (the vertical build).
- Campaign type. The agent does not read it, and in the source data the
  campaign is carried by the topic names. The answer key holds a placeholder.
- Fields with no example in golden_v1 (33 of 54 vertical fields). Needs a
  targeted top-up set.

### Depends on

- AIML-2898 (done): golden_v1 answer key and eval set.
- Vertex credentials on the test environment (the agent and the summary judge).
