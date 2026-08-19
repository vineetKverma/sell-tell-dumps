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
