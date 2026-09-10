# demo_assets

branch: `feature/AIML-2751-remove-guided`  commit: `6ffd86f`  files: 3

<!-- FILE: demo_assets/gen_appendix.py -->
````python
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
````
<!-- END: demo_assets/gen_appendix.py -->

<!-- FILE: demo_assets/gen_flows.py -->
````python
"""Generate crisp flow-diagram PNGs for the implicit vs guided voice-notes flows."""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch, Circle
import matplotlib.patches as mpatches

NAVY = "#101826"
WHITE = "#FFFFFF"
BLUE = "#3B6FE0"
BLUE_BG = "#EAF0FE"
TEAL = "#17A589"
TEAL_BG = "#E7F7F3"
AMBER = "#E08E3B"
AMBER_BG = "#FDF1E4"
GREY = "#5B6472"
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


def header(ax, title, subtitle, accent):
    ax.add_patch(mpatches.Rectangle((0, 660), 1333, 90, facecolor=NAVY, edgecolor="none"))
    ax.add_patch(mpatches.Rectangle((0, 655), 1333, 5, facecolor=accent, edgecolor="none"))
    ax.text(40, 715, title, fontsize=25, fontweight="bold", color=WHITE, va="center")
    ax.text(40, 682, subtitle, fontsize=12.5, color="#B9C2D0", va="center")


def box(ax, cx, cy, w, h, lines, face, edge, textcolor=TEXT_DARK, fontsize=11.5,
        weight="normal", radius=14, step=None):
    b = FancyBboxPatch(
        (cx - w / 2, cy - h / 2), w, h,
        boxstyle=f"round,pad=0,rounding_size={radius}",
        linewidth=2.2, edgecolor=edge, facecolor=face, mutation_aspect=1,
        zorder=2,
    )
    ax.add_patch(b)
    text = "\n".join(lines)
    ax.text(cx, cy, text, ha="center", va="center", fontsize=fontsize,
             color=textcolor, weight=weight, linespacing=1.6, zorder=3)
    if step is not None:
        c = Circle((cx, cy + h / 2), 20, facecolor=edge, edgecolor=WHITE, linewidth=2.5, zorder=4)
        ax.add_patch(c)
        ax.text(cx, cy + h / 2, str(step), ha="center", va="center", fontsize=14,
                 color=WHITE, weight="bold", zorder=5)
    return b


def arrow(ax, x1, y1, x2, y2, color=GREY, style="-|>", lw=2.4, connectionstyle="arc3,rad=0.0"):
    a = FancyArrowPatch((x1, y1), (x2, y2), arrowstyle=style, mutation_scale=18,
                         color=color, linewidth=lw, connectionstyle=connectionstyle,
                         shrinkA=0, shrinkB=0, zorder=1)
    ax.add_patch(a)


def tag(ax, cx, cy, text, color, fontsize=13):
    # Measure the actual rendered text width so the pill never clips it.
    t = ax.text(cx, cy, text, ha="center", va="center", fontsize=fontsize, color=WHITE,
                 weight="bold", zorder=4)
    ax.figure.canvas.draw()
    bbox = t.get_window_extent(renderer=ax.figure.canvas.get_renderer())
    bbox_data = bbox.transformed(ax.transData.inverted())
    text_w = bbox_data.width
    w = max(260, text_w + 70)
    pill = FancyBboxPatch((cx - w / 2, cy - 24), w, 48,
                           boxstyle="round,pad=0,rounding_size=24",
                           linewidth=0, facecolor=color, zorder=3)
    ax.add_patch(pill)
    t.set_zorder(4)


# ---------------------------------------------------------------------------
# Slide 1: Implicit flow
# ---------------------------------------------------------------------------
fig, ax = new_fig()
header(ax, "Implicit Flow \u2014 Single Mega-Payload Extraction",
       "AI/ML team's approach: one continuous dictation, one silent extraction call", BLUE)

y = 470
w, h = 218, 175
xs = [115, 390, 665, 940, 1210]

box(ax, xs[0], y, w, h,
    ["Rep dictates the", "ENTIRE visit in one", "continuous turn", "", "(VAD detects the pause)"],
    BLUE_BG, BLUE, step=1)
box(ax, xs[1], y, w, h,
    ["Agent silently calls", "stage_visit_notes", "", "event type + summary +", "ALL topic dispositions", "in ONE tool call"],
    BLUE_BG, BLUE, step=2, fontsize=11)
box(ax, xs[2], y, w, h,
    ["Staged CRM record", "renders instantly.", "", "Agent speaks ONE", "confirmation readback"],
    BLUE_BG, BLUE, step=3)
box(ax, xs[3], y, w, h,
    ["Rep says \u201cSave\u201d", "", "(or requests a", "correction)"],
    BLUE_BG, BLUE, step=4)
box(ax, xs[4], y, w, h,
    ["commit_visit_notes", "", "CRM record created,", "closing statement", "spoken"],
    TEAL_BG, TEAL, weight="bold", step=5)

for i in range(4):
    arrow(ax, xs[i] + w / 2, y, xs[i + 1] - w / 2, y)

arrow(ax, xs[3], y - h / 2 - 10, xs[1], y - h / 2 - 10, color=AMBER, lw=2,
      connectionstyle="arc3,rad=-0.3", style="-|>")
ax.text((xs[1] + xs[3]) / 2, y - h / 2 - 65, "correction requested \u2192 re-stage (rare)",
        ha="center", fontsize=11, color=AMBER, style="italic")

tag(ax, 666, 195, "~2 conversational turns per session", BLUE)
ax.text(666, 140, "Everything the rep says is captured in ONE dictation \u2192 ONE structured extraction \u2192 ONE save.",
        ha="center", fontsize=13, color=GREY)
ax.text(666, 108, "No explicit event-type question, no per-topic Q&A \u2014 the model infers structure from freeform speech.",
        ha="center", fontsize=13, color=GREY)

fig.savefig("demo_assets/slide1_implicit_flow.png", dpi=DPI)
plt.close(fig)

# ---------------------------------------------------------------------------
# Slide 2: Guided flow
# ---------------------------------------------------------------------------
fig, ax = new_fig()
header(ax, "Guided Flow \u2014 Explicit Turn-by-Turn Script",
       "Alternate UX proposal: fixed script, one explicit question at a time", AMBER)

y = 480
w, h = 202, 175
xs = [100, 335, 570, 805, 1040, 1250]

box(ax, xs[0], y, w, h, ["Stage 0", "Greeting:", "\u201cReady to", "begin?\u201d"], AMBER_BG, AMBER, step=1, fontsize=12)
box(ax, xs[1], y, w, h, ["Stage 1", "Rep dictates \u2192", "agent reads back", "summary \u2192 Save /", "Playback / Re-record?"],
    AMBER_BG, AMBER, step=2, fontsize=10.7)
box(ax, xs[2], y, w, h, ["Stage 3", "Explicit question:", "\u201cMeeting or", "on-site visit?\u201d"], AMBER_BG, AMBER, step=3, fontsize=11.5)
box(ax, xs[3], y, w, h, ["Stage 4 (PER TOPIC)", "\u201cWhat was the", "outcome for [topic]?\u201d", "\u2192 deduce \u2192 confirm", "(up to 3 tries)"],
    AMBER_BG, AMBER, step=4, fontsize=10.3)
box(ax, xs[4], y, w, h, ["Stage 5", "commit_guided_notes", "", "CRM saved +", "closing statement"], TEAL_BG, TEAL, step=5, fontsize=10.7, weight="bold")

for i in range(4):
    arrow(ax, xs[i] + w / 2, y, xs[i + 1] - w / 2, y)

tag(ax, xs[3], y - h / 2 - 45, "\u00d7 N topics, repeats per topic (avg 2.37/session)", AMBER, fontsize=12)

tag(ax, 660, 195, "~5 + N topics conversational turns (avg ~7\u20138)", AMBER)
ax.text(660, 140, "Every field is asked for explicitly, one at a time \u2014 event type, then a full",
        ha="center", fontsize=13, color=GREY)
ax.text(660, 108, "ask \u2192 deduce \u2192 confirm round-trip for EACH topic before the record can be saved.",
        ha="center", fontsize=13, color=GREY)

fig.savefig("demo_assets/slide2_guided_flow.png", dpi=DPI)
plt.close(fig)

print("done")
````
<!-- END: demo_assets/gen_flows.py -->

<!-- FILE: demo_assets/gen_stats.py -->
````python
"""Generate the cost/time comparison table, fold-change callout, and payload
appendix slides. Numbers here mirror the methodology footnoted on-slide:
  - Session counts / avg topics / avg transcript length: REAL BigQuery
    aggregates (queried live from voice_notes_poc.{implicit,guided}_flow_calls).
  - Avg time-to-save / avg cost per session: MODELED. Anchored to one real
    live-tested guided-flow session today (3 topics, standard_sales):
    251.9s elapsed, $0.011758 (from actual Gemini Live usageMetadata), i.e.
    ~31.49s and ~$0.001470 per conversational "turn" (8 turns = 5 fixed +
    3 topics). That per-turn rate is applied to each flow's real avg turn
    count (implicit: fixed ~2 turns; guided: 5 + avg 2.37 topics = ~7.37
    turns) to produce a directional, non-billed estimate.
"""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, Rectangle

NAVY = "#101826"
WHITE = "#FFFFFF"
BLUE = "#3B6FE0"
BLUE_BG = "#EAF0FE"
TEAL = "#17A589"
TEAL_BG = "#E7F7F3"
AMBER = "#E08E3B"
AMBER_BG = "#FDF1E4"
GREY = "#5B6472"
LIGHT_GREY = "#EDEFF3"
TEXT_DARK = "#171B24"

FIGSIZE = (13.333, 7.5)
DPI = 300

# ---- the numbers ----
PER_TURN_SEC = 251.9 / 8.0          # 31.4875
PER_TURN_COST = 0.011758 / 8.0      # 0.00146975
IMPLICIT_TURNS = 2.0
GUIDED_TURNS = 5.0 + 2.368421052631579

implicit_time = PER_TURN_SEC * IMPLICIT_TURNS
guided_time = PER_TURN_SEC * GUIDED_TURNS
implicit_cost = PER_TURN_COST * IMPLICIT_TURNS
guided_cost = PER_TURN_COST * GUIDED_TURNS

time_fold = guided_time / implicit_time
cost_fold = guided_cost / implicit_cost
time_pct = (1 - implicit_time / guided_time) * 100
cost_pct = (1 - implicit_cost / guided_cost) * 100


def fmt_mmss(seconds):
    m = int(seconds // 60)
    s = seconds - m * 60
    return f"{m}m {s:04.1f}s" if m else f"{s:.1f}s"


print("implicit_time", implicit_time, fmt_mmss(implicit_time))
print("guided_time", guided_time, fmt_mmss(guided_time))
print("implicit_cost", implicit_cost)
print("guided_cost", guided_cost)
print("time_fold", time_fold, "time_pct", time_pct)
print("cost_fold", cost_fold, "cost_pct", cost_pct)


def new_fig():
    fig = plt.figure(figsize=FIGSIZE, dpi=DPI)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, 1333)
    ax.set_ylim(0, 750)
    ax.axis("off")
    return fig, ax


def header(ax, title, subtitle, accent):
    ax.add_patch(Rectangle((0, 660), 1333, 90, facecolor=NAVY, edgecolor="none"))
    ax.add_patch(Rectangle((0, 655), 1333, 5, facecolor=accent, edgecolor="none"))
    ax.text(40, 715, title, fontsize=25, fontweight="bold", color=WHITE, va="center")
    ax.text(40, 682, subtitle, fontsize=12.5, color="#B9C2D0", va="center")


# ---------------------------------------------------------------------------
# Slide 3: comparison table
# ---------------------------------------------------------------------------
fig, ax = new_fig()
header(ax, "Implicit vs Guided \u2014 Cost & Time per Session",
       "Real BigQuery usage data + a modeled cost/time estimate", TEAL)

rows = [
    ("Sessions logged to date  (BigQuery)", "62", "19", False),
    ("Avg. topics per session  (real)", "1.71", "2.37", False),
    ("Avg. transcript length  (real)", "306 chars  (~61 words)", "447 chars  (~89 words)", False),
    ("Avg. conversational turns / session  (structural)", "~2", "~7\u20138", False),
    ("Modeled avg. TIME-TO-SAVE", fmt_mmss(implicit_time), fmt_mmss(guided_time), True),
    ("Modeled avg. COST / session", f"${implicit_cost:.4f}", f"${guided_cost:.4f}", True),
]

top = 590
row_h = 72
left, col1, col2, right = 40, 700, 990, 1293

# column headers
ax.add_patch(Rectangle((left, top), right - left, 50, facecolor=NAVY))
ax.text(left + 20, top + 25, "Metric", fontsize=14, color=WHITE, weight="bold", va="center")
ax.text((left + 20 + col1) / 2 + 200, top + 25, "Implicit\n(Mega-Payload)", fontsize=13.5, color=BLUE_BG,
        weight="bold", va="center", ha="center", linespacing=1.3)
ax.text((col1 + col2) / 2 + 145, top + 25, "Guided\n(Explicit Script)", fontsize=13.5, color=AMBER_BG,
        weight="bold", va="center", ha="center", linespacing=1.3)

y = top
for i, (label, v_imp, v_gui, highlight) in enumerate(rows):
    y -= row_h
    bg = LIGHT_GREY if i % 2 == 0 else WHITE
    if highlight:
        bg = "#FFF7E8"
    ax.add_patch(Rectangle((left, y), right - left, row_h, facecolor=bg, edgecolor="#D6DAE1", linewidth=0.8))
    ax.text(left + 20, y + row_h / 2, label, fontsize=12.5,
             color=TEXT_DARK, va="center", weight=("bold" if highlight else "normal"))
    ax.text((left + 20 + col1) / 2 + 260, y + row_h / 2, v_imp, fontsize=15 if highlight else 13,
             color=BLUE if highlight else TEXT_DARK, va="center", ha="center",
             weight="bold" if highlight else "normal")
    ax.text((col1 + col2) / 2 + 175, y + row_h / 2, v_gui, fontsize=15 if highlight else 13,
             color=AMBER if highlight else TEXT_DARK, va="center", ha="center",
             weight="bold" if highlight else "normal")
    # vertical divider
    ax.plot([col1, col1], [y, y + row_h], color="#D6DAE1", linewidth=0.8)

ax.text(left, y - 30,
        "Methodology: session counts / avg topics / avg transcript length are real BigQuery aggregates. Time & cost are a directional model,\n"
        "anchored to one live-tested guided session today (3 topics: 251.9s, $0.011758) scaled per conversational turn \u2014 not measured billing.",
        fontsize=10, color=GREY, va="top", linespacing=1.6)

fig.savefig("demo_assets/slide3_cost_time_table.png", dpi=DPI)
plt.close(fig)

# ---------------------------------------------------------------------------
# Slide 4: fold-change callout
# ---------------------------------------------------------------------------
fig, ax = new_fig()
header(ax, "The Bottom Line", "Modeled impact of Implicit vs Guided, per session", TEAL)

# two big stat cards
cardw, cardh = 560, 380
cx1, cx2 = 366, 966
cy = 330

for cx, big, sub1, sub2, color, bg in [
    (cx1, f"{time_fold:.1f}\u00d7 FASTER", f"~{fmt_mmss(implicit_time)} vs ~{fmt_mmss(guided_time)} to save",
     f"\u2248 {time_pct:.0f}% less time to save", BLUE, BLUE_BG),
    (cx2, f"{cost_fold:.1f}\u00d7 CHEAPER", f"~\\${implicit_cost:.4f} vs ~\\${guided_cost:.4f} / session",
     f"\u2248 {cost_pct:.0f}% fewer tokens billed", TEAL, TEAL_BG),
]:
    ax.add_patch(FancyBboxPatch((cx - cardw / 2, cy - cardh / 2), cardw, cardh,
                                 boxstyle="round,pad=0,rounding_size=22",
                                 linewidth=3, edgecolor=color, facecolor=bg))
    ax.text(cx, cy + 90, big, ha="center", va="center", fontsize=44, weight="bold", color=color)
    ax.text(cx, cy + 10, "Implicit vs Guided", ha="center", va="center", fontsize=15, color=GREY)
    ax.text(cx, cy - 55, sub1, ha="center", va="center", fontsize=15, color=TEXT_DARK, weight="bold")
    ax.text(cx, cy - 100, sub2, ha="center", va="center", fontsize=13.5, color=GREY)

turn_pct = IMPLICIT_TURNS / GUIDED_TURNS * 100
ax.text(666, 90,
        f"Implicit's single silent Mega-Payload extraction needs only ~{turn_pct:.0f}% of the conversational turns\n"
        "Guided's explicit per-topic script requires \u2014 fewer VAD pauses, fewer LLM round-trips, fewer TTS turns.",
        ha="center", fontsize=13.5, color=GREY, linespacing=1.6)
ax.text(666, 40, "See appendix for the full methodology and real BigQuery grounding data.",
        ha="center", fontsize=11.5, color=GREY, style="italic")

fig.savefig("demo_assets/slide4_fold_change_callout.png", dpi=DPI)
plt.close(fig)

print("done")
````
<!-- END: demo_assets/gen_stats.py -->

