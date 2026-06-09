#!/usr/bin/env python3
"""
PostgreSQL TPC-C / TPC-H Benchmark Report Generator
Produces benchmarks/postgresql/results/postgresql_benchmark_report.pdf
"""
import math
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm, mm
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    HRFlowable, PageBreak, KeepTogether
)
from reportlab.platypus.flowables import BalancedColumns
from reportlab.graphics.shapes import Drawing, Rect, String, Line, Polygon
from reportlab.graphics.charts.barcharts import VerticalBarChart
from reportlab.graphics.charts.lineplots import LinePlot
from reportlab.graphics import renderPDF
from reportlab.graphics.widgets.markers import makeMarker
import os, datetime

OUT = os.path.join(os.path.dirname(__file__), "postgresql_benchmark_report.pdf")
W, H = A4

# ── Colour palette ────────────────────────────────────────────────────────────
C_BLUE      = colors.HexColor("#1565C0")
C_BLUE_LITE = colors.HexColor("#E3F2FD")
C_BLUE_MID  = colors.HexColor("#90CAF9")
C_GREEN     = colors.HexColor("#2E7D32")
C_GREEN_LITE= colors.HexColor("#E8F5E9")
C_ORANGE    = colors.HexColor("#E65100")
C_GREY      = colors.HexColor("#546E7A")
C_GREY_LITE = colors.HexColor("#ECEFF1")
C_WHITE     = colors.white
C_BLACK     = colors.HexColor("#212121")
C_RED       = colors.HexColor("#C62828")

# ── Styles ────────────────────────────────────────────────────────────────────
styles = getSampleStyleSheet()

def S(name, **kw):
    base = styles[name] if name in styles else styles["Normal"]
    return ParagraphStyle(name + str(id(kw)), parent=base, **kw)

TITLE     = S("Title",    fontSize=26, textColor=C_BLUE,  spaceAfter=4,  leading=30, alignment=TA_CENTER)
SUBTITLE  = S("Normal",   fontSize=13, textColor=C_GREY,  spaceAfter=2,  alignment=TA_CENTER)
H1        = S("Heading1", fontSize=15, textColor=C_BLUE,  spaceAfter=6,  spaceBefore=14, leading=18)
H2        = S("Heading2", fontSize=12, textColor=C_GREY,  spaceAfter=4,  spaceBefore=8,  leading=15)
BODY      = S("Normal",   fontSize=9,  textColor=C_BLACK, spaceAfter=4,  leading=13)
SMALL     = S("Normal",   fontSize=8,  textColor=C_GREY,  spaceAfter=2,  leading=11)
BOLD      = S("Normal",   fontSize=9,  textColor=C_BLACK, spaceAfter=4,  leading=13, fontName="Helvetica-Bold")
CELL      = S("Normal",   fontSize=8.5,textColor=C_BLACK, leading=12,    alignment=TA_CENTER)
CELL_L    = S("Normal",   fontSize=8.5,textColor=C_BLACK, leading=12,    alignment=TA_LEFT)
CELL_H    = S("Normal",   fontSize=8.5,textColor=C_WHITE, leading=12,    alignment=TA_CENTER, fontName="Helvetica-Bold")
RESULT    = S("Normal",   fontSize=22, textColor=C_GREEN, leading=26,    alignment=TA_CENTER, fontName="Helvetica-Bold")
RESULT_LBL= S("Normal",   fontSize=9,  textColor=C_GREY,  leading=12,    alignment=TA_CENTER)
CAPTION   = S("Normal",   fontSize=8,  textColor=C_GREY,  leading=11,    alignment=TA_CENTER, spaceAfter=6)

def hr():
    return HRFlowable(width="100%", thickness=0.5, color=C_BLUE_MID, spaceAfter=8, spaceBefore=4)

def section(title):
    return [Spacer(1, 4*mm), Paragraph(title, H1), hr()]

def tbl_style(header_rows=1, row_colors=True):
    base = [
        ("BACKGROUND", (0,0), (-1, header_rows-1), C_BLUE),
        ("TEXTCOLOR",  (0,0), (-1, header_rows-1), C_WHITE),
        ("FONTNAME",   (0,0), (-1, header_rows-1), "Helvetica-Bold"),
        ("FONTSIZE",   (0,0), (-1,-1), 8.5),
        ("ROWBACKGROUND", (0, header_rows), (-1,-1),
         [C_WHITE, C_GREY_LITE] if row_colors else [C_WHITE]),
        ("GRID",       (0,0), (-1,-1), 0.25, colors.HexColor("#B0BEC5")),
        ("TOPPADDING",    (0,0), (-1,-1), 4),
        ("BOTTOMPADDING", (0,0), (-1,-1), 4),
        ("LEFTPADDING",   (0,0), (-1,-1), 6),
        ("RIGHTPADDING",  (0,0), (-1,-1), 6),
        ("VALIGN",     (0,0), (-1,-1), "MIDDLE"),
    ]
    return TableStyle(base)

# ── Data ──────────────────────────────────────────────────────────────────────
POWER_TIMES = {
    1: 33.2,  2: 28.8,  3: 36.1,  4: 6.5,   5: 18.8,
    6: 7.4,   7: 14.0,  8: 15.7,  9: 50.1,  10: 32.7,
    11: 7.1,  12: 12.0, 13: 138.2,14: 117.8, 15: 47.2,
    16: 39.9, 17: 102.6,18: 92.6,  19: 2.1,  20: 53.9,
    21: 20.5, 22: 2.1,
}
THRU_VU_TIMES  = [1631, 1563, 1556, 1563, 1584]
THRU_GEO_MEANS = [46.605, 41.174, 41.769, 42.087, 43.030]

GEO_MEAN_POWER = math.exp(sum(math.log(t) for t in POWER_TIMES.values()) / 22)
POWER_SCORE    = 100 * 3600 / GEO_MEAN_POWER
THRU_SCORE     = (5 * 22 * 100 * 3600) / max(THRU_VU_TIMES)
QPHH           = math.sqrt(POWER_SCORE * THRU_SCORE)

# ── Bar chart helper ──────────────────────────────────────────────────────────
def query_time_chart(width=16*cm, height=6*cm):
    d = Drawing(width, height)
    bc = VerticalBarChart()
    bc.x, bc.y = 30, 20
    bc.width  = width  - 40
    bc.height = height - 30
    bc.data   = [list(POWER_TIMES[q] for q in range(1,23))]
    bc.bars[0].fillColor = C_BLUE
    bc.bars[0].strokeColor = None
    bc.categoryAxis.categoryNames = [f"Q{q}" for q in range(1,23)]
    bc.categoryAxis.labels.fontSize   = 7
    bc.categoryAxis.labels.angle      = 0
    bc.valueAxis.valueMin             = 0
    bc.valueAxis.valueMax             = 150
    bc.valueAxis.valueStep            = 25
    bc.valueAxis.labels.fontSize      = 7
    bc.valueAxis.labelTextFormat      = "%ds"
    bc.barWidth   = 0.6
    bc.groupSpacing = 0.3
    d.add(bc)
    d.add(String(8, height/2, "Time (s)", fontSize=7, fillColor=C_GREY,
                 textAnchor="middle"))
    return d

def comparison_chart(width=10*cm, height=6*cm):
    d = Drawing(width, height)
    bc = VerticalBarChart()
    bc.x, bc.y = 40, 20
    bc.width  = width  - 55
    bc.height = height - 30
    bc.data   = [[14644, round(QPHH)]]
    bc.bars[0].fillColor = C_ORANGE
    bc.bars[1] = bc.bars[0]
    bc.bars[0].fillColor = C_BLUE_MID
    bc.bars[1].fillColor = C_GREEN
    bc.categoryAxis.categoryNames = ["EPYC 9454\n(Viettel PoC)", f"EPYC 9555P\n(This run)"]
    bc.categoryAxis.labels.fontSize   = 8
    bc.valueAxis.valueMin  = 0
    bc.valueAxis.valueMax  = 22000
    bc.valueAxis.valueStep = 5000
    bc.valueAxis.labels.fontSize = 7
    bc.valueAxis.labelTextFormat = "%d"
    bc.barWidth    = 0.8
    bc.groupSpacing = 0.5
    d.add(bc)
    d.add(String(20, height/2, "QphH@SF100", fontSize=7, fillColor=C_GREY,
                 textAnchor="middle"))
    return d

# ── Build document ─────────────────────────────────────────────────────────────
doc = SimpleDocTemplate(
    OUT, pagesize=A4,
    leftMargin=2*cm, rightMargin=2*cm,
    topMargin=2*cm,  bottomMargin=2*cm,
    title="PostgreSQL Benchmark Report — AMD EPYC 9555P",
    author="skariapaul/postgresql-bench",
)
story = []

# ── Cover / header ─────────────────────────────────────────────────────────────
story += [
    Spacer(1, 8*mm),
    Paragraph("PostgreSQL Benchmark Report", TITLE),
    Paragraph("TPC-C (OLTP)  ·  TPC-H SF10 &amp; SF100 (OLAP)", SUBTITLE),
    Paragraph(f"Generated {datetime.date.today().strftime('%B %d, %Y')}  ·  "
              f"<a href='https://github.com/skariapaul/postgresql-bench' color='#1565C0'>"
              f"github.com/skariapaul/postgresql-bench</a>", SMALL),
    Spacer(1, 6*mm),
    hr(),
]

# ── Key metrics boxes ──────────────────────────────────────────────────────────
metrics = [
    ["973,227", "NOPM", "TPC-C New Orders / min"],
    [f"{QPHH:,.0f}", "QphH@SF100", "TPC-H composite score"],
    [f"{POWER_SCORE:,.0f}", "Power@SF100", f"Geo mean {GEO_MEAN_POWER:.1f}s / query"],
    [f"{THRU_SCORE:,.0f}", "Throughput@SF100", f"5 streams · {max(THRU_VU_TIMES)}s"],
]
box_data = [[
    Table([[Paragraph(v, RESULT)], [Paragraph(l, RESULT_LBL)], [Paragraph(n, SMALL)]],
          colWidths=[4*cm], style=TableStyle([
              ("ALIGN", (0,0), (-1,-1), "CENTER"),
              ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
              ("BACKGROUND", (0,0), (-1,-1), C_BLUE_LITE),
              ("BOX", (0,0), (-1,-1), 1, C_BLUE_MID),
              ("TOPPADDING",    (0,0), (-1,-1), 5),
              ("BOTTOMPADDING", (0,0), (-1,-1), 5),
          ]))
    for v, l, n in metrics
]]
story.append(Table(box_data, colWidths=[4.2*cm]*4,
                   style=TableStyle([("ALIGN",(0,0),(-1,-1),"CENTER"),
                                     ("LEFTPADDING",(0,0),(-1,-1),2),
                                     ("RIGHTPADDING",(0,0),(-1,-1),2)])))
story.append(Spacer(1, 4*mm))

# ── System ─────────────────────────────────────────────────────────────────────
story += section("Reference System")
sys_data = [
    [Paragraph("Component", CELL_H), Paragraph("Detail", CELL_H)],
    ["CPU",        "AMD EPYC 9555P — 64 cores / 128 threads, single socket"],
    ["NUMA",       "NPS4 — 4 nodes; benchmarks pinned to node 0 (CPUs 0-15, 64-79, 32 logical CPUs)"],
    ["RAM",        "377 GiB DDR5"],
    ["Storage",    "465 GB NVMe SSD"],
    ["OS",         "Ubuntu 24.04 LTS"],
    ["PostgreSQL", "17 (Docker image postgres:17)"],
    ["HammerDB",   "5.0"],
]
t = Table([[Paragraph(r[0] if isinstance(r[0],str) else r[0], CELL_L),
            Paragraph(r[1] if isinstance(r[1],str) else r[1], CELL_L)]
           if i > 0 else r for i, r in enumerate(sys_data)],
          colWidths=[3.5*cm, 13*cm])
t.setStyle(tbl_style(1))
story += [t, Spacer(1, 2*mm)]

# ── TPC-C ──────────────────────────────────────────────────────────────────────
story += section("TPC-C — OLTP Benchmark")
story.append(Paragraph(
    "TPC-C simulates an order-entry workload with five transaction types "
    "(New Order, Payment, Order Status, Delivery, Stock Level). "
    "The primary metric is <b>NOPM</b> — New Orders Per Minute.", BODY))

cfg_data = [
    [Paragraph("Parameter", CELL_H), Paragraph("Value", CELL_H),
     Paragraph("Parameter", CELL_H), Paragraph("Value", CELL_H)],
    ["Warehouses", "64",  "shared_buffers",       "80 GB"],
    ["Build VUs",  "8",   "synchronous_commit",   "off"],
    ["Run VUs",    "32",  "jit",                  "off"],
    ["Ramp-up",    "2 min","max_parallel_workers", "64"],
    ["Timed run",  "10 min","effective_cache_size","280 GB"],
]
t = Table([[Paragraph(str(c), CELL_L if j % 2 == 0 else CELL) for j,c in enumerate(row)]
           if i > 0 else row for i, row in enumerate(cfg_data)],
          colWidths=[3.5*cm, 3*cm, 4.5*cm, 5.5*cm])
t.setStyle(tbl_style(1))
story += [t, Spacer(1, 3*mm)]

res_data = [
    [Paragraph(h, CELL_H) for h in ["VUs", "Warehouses", "NOPM", "TPM", "Config"]],
    ["32", "64", Paragraph("<b>973,227</b>", CELL), Paragraph("<b>2,240,247</b>", CELL),
     Paragraph("sync_commit=off, jit=off, shared_buffers=80GB", CELL_L)],
]
t = Table([[Paragraph(str(c), CELL) if not isinstance(c, Paragraph) else c for c in row]
           if i > 0 else row for i, row in enumerate(res_data)],
          colWidths=[1.5*cm, 2.5*cm, 2.5*cm, 2.5*cm, 7.5*cm])
t.setStyle(tbl_style(1))
story += [t, Spacer(1, 2*mm),
          Paragraph("973,227 NOPM is the sustained New-Order transaction rate over the 10-minute "
                    "timed window after a 2-minute ramp-up.", SMALL)]

# ── TPC-H overview ─────────────────────────────────────────────────────────────
story += section("TPC-H — OLAP Benchmark")
story.append(Paragraph(
    "TPC-H measures decision-support performance using 22 complex analytical queries "
    "over a synthetic supply-chain database. The composite metric is "
    "<b>QphH@Size = √(Power@Size × Throughput@Size)</b>. "
    "Higher is better.", BODY))

cfg2_data = [
    [Paragraph("Parameter", CELL_H), Paragraph("Value", CELL_H),
     Paragraph("Parameter", CELL_H), Paragraph("Value", CELL_H)],
    ["shared_buffers",  "100 GB",  "wal_level",          "minimal"],
    ["work_mem",        "4 GB",    "autovacuum",          "off"],
    ["jit",             "on",      "max_parallel_workers","64"],
    ["Power test",      "1 VU, dop=8", "Throughput test","5 VUs, dop=3"],
]
t = Table([[Paragraph(str(c), CELL_L if j % 2 == 0 else CELL) for j,c in enumerate(row)]
           if i > 0 else row for i, row in enumerate(cfg2_data)],
          colWidths=[3.5*cm, 3*cm, 4.5*cm, 5.5*cm])
t.setStyle(tbl_style(1))
story += [t, Spacer(1, 3*mm)]

sf_data = [
    [Paragraph(h, CELL_H) for h in ["Scale", "Test", "Total Time", "Geo Mean", "Score"]],
    ["SF10",  "Power",      "78 s",    "1.88 s", "—"],
    ["SF10",  "Throughput", "~105 s",  "2.75 s", "—"],
    ["SF100", "Power",
     Paragraph("<b>879 s</b>", CELL),
     Paragraph("<b>23.4 s</b>", CELL),
     Paragraph("<b>15,375</b>", CELL)],
    ["SF100", "Throughput",
     Paragraph("<b>1,631 s</b>", CELL),
     Paragraph("<b>42.9 s</b>", CELL),
     Paragraph("<b>24,280</b>", CELL)],
]
t = Table([[Paragraph(str(c), CELL) if not isinstance(c, Paragraph) else c for c in row]
           if i > 0 else row for i, row in enumerate(sf_data)],
          colWidths=[2*cm, 3*cm, 2.5*cm, 2.5*cm, 6.5*cm])
t.setStyle(tbl_style(1))

# Merge SF100 rows label
ts2 = TableStyle([
    ("SPAN",       (0, 3), (0, 4)),
    ("BACKGROUND", (0, 3), (-1, 4), C_GREEN_LITE),
    ("FONTNAME",   (0, 3), (0, 4), "Helvetica-Bold"),
])
t.setStyle(ts2)
story += [t, Spacer(1, 2*mm)]

# QphH highlight
qphh_box = Table(
    [[Paragraph(f"QphH@SF100 = √({POWER_SCORE:,.0f} × {THRU_SCORE:,.0f}) = <b>{QPHH:,.0f}</b>",
                S("Normal", fontSize=13, textColor=C_GREEN, fontName="Helvetica-Bold",
                  alignment=TA_CENTER, leading=18))]],
    colWidths=[16.5*cm],
    style=TableStyle([
        ("BACKGROUND", (0,0), (-1,-1), C_GREEN_LITE),
        ("BOX",        (0,0), (-1,-1), 1.5, C_GREEN),
        ("TOPPADDING",    (0,0),(-1,-1), 8),
        ("BOTTOMPADDING", (0,0),(-1,-1), 8),
    ])
)
story += [qphh_box, Spacer(1, 4*mm)]

# ── Per-query chart + table ────────────────────────────────────────────────────
story += [Paragraph("SF100 Power Test — Per-Query Execution Times", H2)]
story.append(query_time_chart())
story.append(Paragraph(
    "Query execution times for the SF100 power test (1 VU, dop=8). "
    "Q13 (138 s) and Q14 (118 s) are the longest — both involve large "
    "aggregations over the 600M-row lineitem table.", CAPTION))

# Per-query table (3-column layout)
q_rows = [
    [Paragraph(h, CELL_H) for h in ["Query", "Time (s)", "Query", "Time (s)", "Query", "Time (s)"]],
]
qs = list(POWER_TIMES.items())
for i in range(0, 22, 3):
    row = []
    for j in range(3):
        if i+j < 22:
            q, t = qs[i+j]
            row += [Paragraph(f"Q{q}", CELL), Paragraph(f"{t:.1f}", CELL)]
        else:
            row += ["", ""]
    q_rows.append(row)

t = Table(q_rows, colWidths=[1.5*cm, 2*cm]*3)
t.setStyle(tbl_style(1))
story += [t, Spacer(1, 4*mm)]

# ── Comparison ─────────────────────────────────────────────────────────────────
story += section("Comparison with Viettel PoC Reference")
story.append(Paragraph(
    "The Viettel PoC document benchmarked an AMD EPYC 9454 system at SF100 and "
    "reported QphH@SF100 = 14,644. Our EPYC 9555P result of "
    f"<b>{QPHH:,.0f}</b> is <b>32% higher</b>, consistent with the "
    "generational improvement from the Genoa (9004) to Genoa-X/next-gen architecture "
    "and the higher core frequency of the 9555P (3.1 GHz base vs 2.25 GHz for 9454).", BODY))

cmp_data = [
    [Paragraph(h, CELL_H) for h in ["System", "CPU", "Cores (bench)", "QphH@SF100", "vs Viettel"]],
    [Paragraph("Viettel PoC", CELL_L), "EPYC 9454", "—", "14,644", "baseline"],
    [Paragraph("<b>This run</b>", CELL_L),
     Paragraph("<b>EPYC 9555P</b>", CELL),
     "32 (NPS4 node0)",
     Paragraph(f"<b>{QPHH:,.0f}</b>", CELL),
     Paragraph("<b>+32%</b>", S("Normal", fontSize=8.5, textColor=C_GREEN,
                                 fontName="Helvetica-Bold", alignment=TA_CENTER))],
]
t = Table([[Paragraph(str(c), CELL) if not isinstance(c, Paragraph) else c for c in row]
           if i > 0 else row for i, row in enumerate(cmp_data)],
          colWidths=[3.5*cm, 3.5*cm, 3.5*cm, 3*cm, 3*cm])
t.setStyle(tbl_style(1))
story += [t, Spacer(1, 4*mm)]

story.append(comparison_chart(width=9*cm, height=6*cm))
story.append(Paragraph("QphH@SF100 comparison — EPYC 9454 (Viettel PoC) vs EPYC 9555P (this run).", CAPTION))

# ── Tuning notes ───────────────────────────────────────────────────────────────
story += section("Key Tuning Decisions")

tuning = [
    [Paragraph("Setting", CELL_H), Paragraph("Value", CELL_H), Paragraph("Rationale", CELL_H)],
    ["synchronous_commit = off", "TPC-C only",
     "Allows WAL writer to batch flushes; dramatically improves OLTP throughput. "
     "Data is not lost on PostgreSQL crash (WAL is still written)."],
    ["jit = off", "TPC-C only",
     "JIT compilation overhead exceeds savings for short OLTP transactions. "
     "Enabled for TPC-H where queries are long-running."],
    ["shared_buffers = 100 GB", "TPC-H",
     "Keeps the hot portion of the 103 GB lineitem heap in memory after warm-up, "
     "avoiding repeated disk I/O during analytical queries."],
    ["wal_level = minimal", "TPC-H build",
     "Eliminates WAL overhead for load-only workloads; CREATE INDEX uses the "
     "fast non-WAL path. Replication disabled (max_wal_senders=0)."],
    ["--cpuset-cpus only\n(no --cpuset-mems)", "Both",
     "CPU pinning to NUMA node 0 maintains cache locality without restricting memory "
     "to node 0's ~94 GB. With --cpuset-mems 0, the kernel OOM-kills PostgreSQL when "
     "shared_buffers exceeds available node memory during checkpoints."],
    ["dop = 8 (power) / dop = 3 (throughput)", "TPC-H",
     "Power test uses higher parallelism since only one stream runs. "
     "Throughput test uses lower dop so 5 concurrent streams share CPU resources."],
]
rows = []
for i, row in enumerate(tuning):
    if i == 0:
        rows.append(row)
    else:
        rows.append([
            Paragraph(row[0], S("Normal", fontSize=8, fontName="Helvetica-Bold",
                                textColor=C_BLUE, leading=11)),
            Paragraph(row[1], CELL),
            Paragraph(row[2], SMALL),
        ])
t = Table(rows, colWidths=[4.5*cm, 2*cm, 10*cm])
t.setStyle(tbl_style(1))
story += [t, Spacer(1, 4*mm)]

# ── Repo & reproducibility ─────────────────────────────────────────────────────
story += section("Reproducing These Results")
story.append(Paragraph(
    "All scripts, configurations, and this report are available at "
    "<a href='https://github.com/skariapaul/postgresql-bench' color='#1565C0'>"
    "github.com/skariapaul/postgresql-bench</a>. "
    "The runner scripts auto-detect RAM, CPU count, and NUMA topology and scale "
    "all parameters accordingly — no manual tuning required.", BODY))

repo_data = [
    [Paragraph("Path", CELL_H), Paragraph("Purpose", CELL_H)],
    ["benchmarks/postgresql/run_tpcc.sh",     "Auto-scaling TPC-C runner (detects RAM/CPU/NUMA)"],
    ["benchmarks/postgresql/run_tpch.sh",     "Auto-scaling TPC-H runner — arg: sf10 | sf100"],
    ["benchmarks/postgresql/docker/tpcc/",    "OLTP-tuned postgresql.conf (reference)"],
    ["benchmarks/postgresql/docker/tpch/",    "OLAP-tuned postgresql.conf (reference)"],
    ["benchmarks/postgresql/tcl/",            "HammerDB TCL scripts for build / power / throughput"],
    ["benchmarks/postgresql/results/",        "Run logs (gitignored) and this report"],
]
t = Table([[Paragraph(str(c), CELL_L) for c in row] if i > 0 else row
           for i, row in enumerate(repo_data)],
          colWidths=[7*cm, 9.5*cm])
t.setStyle(tbl_style(1))
story += [t, Spacer(1, 3*mm)]

story.append(Paragraph(
    "Quick-start:", BOLD))
story.append(Paragraph(
    "git clone https://github.com/skariapaul/postgresql-bench &amp;&amp; "
    "cd postgresql-bench/benchmarks/postgresql<br/>"
    "HAMMERDB_DIR=/path/to/HammerDB ./run_tpcc.sh<br/>"
    "HAMMERDB_DIR=/path/to/HammerDB ./run_tpch.sh sf100",
    S("Normal", fontSize=8.5, fontName="Courier", textColor=C_BLACK,
      backColor=C_GREY_LITE, leading=14, leftIndent=8, spaceAfter=6,
      borderPad=6)))

# ── Footer note ────────────────────────────────────────────────────────────────
story += [
    Spacer(1, 6*mm), hr(),
    Paragraph(
        "This is an informal benchmark for hardware evaluation purposes. "
        "Results are not TPC-audited. All configurations, logs, and scripts "
        f"are publicly available. Report generated {datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}.",
        SMALL),
]

doc.build(story)
print(f"Report written to: {OUT}")
