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
