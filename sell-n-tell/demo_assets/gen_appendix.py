"""Generate the appendix slide: input/output payload structures for both flows."""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, Rectangle

NAVY = "#101826"
WHITE = "#FFFFFF"
BLUE = "#3B6FE0"
BLUE_BG = "#EAF0FE"
TEAL = "#17A589"
AMBER = "#E08E3B"
AMBER_BG = "#FDF1E4"
GREY = "#5B6472"
CODE_BG = "#F5F6F8"
TEXT_DARK = "#171B24"

FIGSIZE = (13.333, 7.5)
DPI = 300


def new_fig():
    fig = plt.figure(figsize=FIGSIZE, dpi=DPI)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, 1333)
    ax.set_ylim(0, 750)
    ax.axis("off")
    return fig, ax


def header(ax, title, subtitle):
    ax.add_patch(Rectangle((0, 660), 1333, 90, facecolor=NAVY, edgecolor="none"))
    ax.add_patch(Rectangle((0, 655), 1333, 5, facecolor=TEAL, edgecolor="none"))
    ax.text(40, 715, title, fontsize=24, fontweight="bold", color=WHITE, va="center")
    ax.text(40, 682, subtitle, fontsize=12, color="#B9C2D0", va="center")


def code_block(ax, x, y, w, h, title, code, accent, accent_bg, fontsize=7.8, linespacing=1.45):
    ax.add_patch(FancyBboxPatch((x, y), w, 34, boxstyle="round,pad=0,rounding_size=6",
                                 linewidth=0, facecolor=accent))
    ax.text(x + 14, y + 17, title, fontsize=12.5, color=WHITE, weight="bold", va="center")
    ax.add_patch(Rectangle((x, y - h), w, h, facecolor=CODE_BG, edgecolor=accent, linewidth=1.4))
    ax.text(x + 14, y - 12, code, fontsize=fontsize, color=TEXT_DARK, va="top",
            family="monospace", linespacing=linespacing)


fig, ax = new_fig()
header(ax, "Appendix \u2014 Input / Output Payload Structures",
       "Actual tool-call argument & CRM commit shapes for both flows (fields trimmed for space)")

# ---- IMPLICIT column ----
ix, iw = 40, 610
ax.text(ix, 632, "IMPLICIT \u2014 single Mega-Payload", fontsize=14, color=BLUE, weight="bold")

implicit_input = '''INPUT  \u2192  stage_visit_notes(...)
{
  "event_type": "On-site visit",
  "executive_summary": "Visited Meridian; pricing
    is a concern, RiverEdge has the contract.",
  "raw_transcript_backup": "On-site visit to
    Meridian's warehouse...",
  "topics": [
    { "topic": "New product introduction",
      "disposition_code": 1, "discussed": true,
      "executive_summary": "Wants a quote." },
    { "topic": "Pricing & promotions",
      "disposition_code": 8, "discussed": true,
      "executive_summary": "Budget is tight." }
  ],
  "planned_topics": ["New product introduction", ...]
}'''

implicit_output = '''OUTPUT \u2192  commit_visit_notes(...)
{
  "status": "success",
  "crm_record_id": "CRM-9E3F11A7AC",
  "closing_statement": "Saved successfully.
    Have a great day!"
}

Persisted CRM / BigQuery row also includes:
agent_mode, campaign_type, disposition_label
(joined), missing_topics, correction_count,
staged_at, committed_at, environment.'''

code_block(ax, ix, 615, iw, 240, "INPUT  (rep \u2192 agent, one call)", implicit_input, BLUE, BLUE_BG,
           fontsize=7.2, linespacing=1.35)
code_block(ax, ix, 350, iw, 220, "OUTPUT (agent \u2192 CRM)", implicit_output, TEAL, "#E7F7F3")

# ---- GUIDED column ----
gx, gw = 683, 610
ax.text(gx, 632, "GUIDED \u2014 incremental, one call per stage", fontsize=14, color=AMBER, weight="bold")

guided_input = '''INPUT \u2192 capture_dictation(...)
{ "raw_transcript": "...", "executive_summary": "..." }

INPUT \u2192 set_event_type(...)
{ "event_type": "On-site visit" }

INPUT \u2192 record_topic_disposition(...)   \u00d7 per topic
{
  "topic": "Pricing & promotions",
  "disposition_code": 8,
  "executive_summary": "Budget is tight this quarter.",
  "discussed": true,
  "needs_manual_review": false
}'''

guided_output = '''OUTPUT \u2192 commit_guided_notes(...)
{
  "status": "success",
  "crm_record_id": "CRM-3E8C9998A8",
  "manual_review_topics": [],
  "closing_statement": "All set. I've saved your
    post-call summary notes and updated the outcomes
    for your discussion topics. Have a great day!"
}

Note: unlike implicit, this response has NO event_type /
summary / topics \u2014 the UI must reassemble the record
client-side from the calls above.'''

code_block(ax, gx, 615, gw, 240, "INPUT  (rep \u2192 agent, several calls)", guided_input, AMBER, AMBER_BG,
           fontsize=7.2, linespacing=1.35)
code_block(ax, gx, 350, gw, 220, "OUTPUT (agent \u2192 CRM)", guided_output, TEAL, "#E7F7F3")

fig.savefig("demo_assets/slide5_appendix_payloads.png", dpi=DPI)
plt.close(fig)
print("done")
