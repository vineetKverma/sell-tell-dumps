"""Pydantic schemas shared across the voice-notes workflow and tools layer.

Pulled out of mock_db.py (now notes_workflow.py) per the contract-
simplification pass: this module holds data shapes only, no logic, so both
notes_workflow.py and tools.py can import from here without either one
importing the other for type definitions.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class DiscussionTopic(BaseModel):
    """A single call topic within one visit, with its own disposition.

    A visit can cover several distinct call topics (e.g. pricing, then a
    renewal), and each one gets its own disposition + summary.

    Topics line up with the rep's *pre-call planned topics* (now hardcoded
    client-side; the server no longer serves or validates the catalog). A
    planned topic is listed once the rep has addressed it; one the rep did
    not mention is left out, so the tool reminds the rep about it:
    - If it was actually discussed, ``discussed`` is True and
      ``disposition_code`` carries the mapped outcome (one of the fixed
      disposition codes loaded from the workflow module's YAML registry).
    - If, after the reminder, the rep says they did not get to it,
      ``discussed`` is False and ``disposition_code`` may be omitted;
      ``executive_summary`` then holds the rep's feedback on why (e.g. "ran
      out of time, will cover next visit").
    """

    topic: str = Field(
        ..., description="Short label / subject of this call topic"
    )
    disposition_code: int | None = Field(
        default=None,
        description=(
            "Disposition outcome for THIS topic, chosen from the fixed "
            "disposition registry. Required when the topic was discussed; "
            "null for a planned-but-not-discussed topic."
        ),
    )
    executive_summary: str = Field(
        default="",
        description=(
            "Condensed 1-2 sentence summary of THIS topic. Leave empty "
            "rather than inventing one -- a topic the rep skipped without "
            "giving a reason has nothing to summarize, and a required field "
            "here forces the model to confabulate (observed live: 'Rep did "
            "not get to pricing due to time constraints' when the rep never "
            "said so)."
        ),
    )
    discussed: bool = Field(
        default=True,
        description=(
            "Whether this planned topic was actually covered in the "
            "dictation. False means the rep planned it but did not get to "
            "it."
        ),
    )
    needs_manual_review: bool = Field(
        default=False,
        description=(
            "True if the disposition code had to be left unresolved for a "
            "human to fix. NOT partitioned by flow: stage_notes sets this "
            "automatically whenever disposition_code == 99, so the surviving "
            "flow produces both together. The retired guided flow set it "
            "WITHOUT a code (after 3 failed disposition-confirm attempts), "
            "which is the shape validate_payload's no-code exemption was "
            "written for -- that exemption is now vestigial. Unifying the "
            "two shapes is an open decision -- see AIML-2705."
        ),
    )


class TopicOutcome(BaseModel):
    """One planned topic's final outcome, as delivered in Output2.

    Distinct from DiscussionTopic: this is the read-side shape returned by
    the commit tool, not the write-side shape the model stages. It adds
    ``disposition_label`` (the human-readable label, e.g. "Pricing
    concerns") so the UI and the spoken closing statement don't need their
    own copy of the disposition registry to render a code -- the workflow
    module fills it in from the loaded registry at commit time.
    """

    topic: str
    executive_summary: str = ""
    disposition_code: int | None = None
    disposition_label: str | None = None
    discussed: bool = True
    needs_manual_review: bool = False


class CommitResult(BaseModel):
    """Output2: the commit tool's own, authoritative response.

    Replaces both the old REST CommitResponse (which only carried
    {status, crm_record_id, closing_statement}) and the pattern of
    reconstructing the final record client-side from earlier streamed
    tool-call arguments. Identified by ``session_id`` alone -- there is no
    ``crm_record_id``: mock_db/notes_workflow never was a real CRM, and
    session_id is already a fresh UUID per commit (see AIML-2703), so it is
    the one genuine identifier for "this commit event".

    Used for BOTH a first-time commit and an idempotent-retry replay (the
    "already committed" branch in commit_notes returns this same shape,
    just reconstructed from the previously committed record instead of
    freshly built).
    """

    session_id: str
    executive_summary: str = Field(
        ..., description="Condensed whole-call summary."
    )
    planned_topics: list[str] = Field(
        default_factory=list,
        description="The pre-call planned topics the rep selected.",
    )
    topics: list[TopicOutcome] = Field(
        default_factory=list,
        description=(
            "One entry per planned topic: its brief summary and final "
            "disposition."
        ),
    )
    closing_statement: str = Field(
        ..., description="What the agent speaks aloud after a successful save."
    )
