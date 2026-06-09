#!/usr/bin/env python3
"""
TPC-H SF10 Benchmark Report with Power Consumption
Reads live results from results/tpch/ and produces sf10_benchmark_report.pdf
"""
import math, csv, os, datetime, glob

RESULTS_DIR = os.path.join(os.path.dirname(__file__), "tpch")
OUT         = os.path.join(os.path.dirname(__file__), "sf10_benchmark_report.pdf")

# ── Locate latest SF10 result files ───────────────────────────────────────────
log_files   = sorted(glob.glob(os.path.join(RESULTS_DIR, "tpch-sf10-*.log")))
power_files = sorted(glob.glob(os.path.join(RESULTS_DIR, "power-sf10-*.csv")))
if not log_files:
    raise FileNotFoundError("No tpch-sf10-*.log found")
LOG_FILE   = log_files[-1]
POWER_FILE = power_files[-1] if power_files else None
RUN_TS     = os.path.basename(LOG_FILE).replace("tpch-sf10-","").replace(".log","")
RUN_DATE   = datetime.datetime.strptime(RUN_TS, "%Y%m%d-%H%M%S").strftime("%B %d, %Y  %H:%M UTC")

# ── Parse benchmark log ────────────────────────────────────────────────────────
power_times  = {}   # {query_num: seconds}  — first pass = power test
thru_streams = {}   # {vu_num: (total_s, geo_mean)}
geo_mean_power = None
power_total_s  = None
thru_longest   = 0

in_power = False
in_thru  = False
power_done = False

with open(LOG_FILE) as f:
    for line in f:
        line = line.strip()
        # Detect phase transitions
        if "Running power test" in line:
            in_power = True; in_thru = False
        elif "Running throughput test" in line:
            in_power = False; in_thru = True; power_done = True

        if in_power and not power_done:
            m = __import__('re').match(r'Vuser 1:query (\d+) completed in ([\d.]+) seconds', line)
            if m:
                power_times[int(m.group(1))] = float(m.group(2))
            m2 = __import__('re').match(r'Vuser 1:Completed 1 query set.+in (\d+) seconds', line)
            if m2:
                power_total_s = int(m2.group(1))
            m3 = __import__('re').match(r'Vuser 1:Geometric mean of query times.*is ([\d.]+)', line)
            if m3:
                geo_mean_power = float(m3.group(1))

        if in_thru:
            m = __import__('re').match(r'Vuser (\d+):Completed 1 query set.+in (\d+) seconds', line)
            if m:
                vu, t = int(m.group(1)), int(m.group(2))
                thru_longest = max(thru_longest, t)
                if vu not in thru_streams:
                    thru_streams[vu] = [t, None]
                else:
                    thru_streams[vu][0] = t
            m2 = __import__('re').match(r'Vuser (\d+):Geometric mean of query times.*is ([\d.]+)', line)
            if m2:
                vu, gm = int(m2.group(1)), float(m2.group(2))
                if vu in thru_streams:
                    thru_streams[vu][1] = gm

# Fallback: parse per-query from first Vuser 1 block if phase detection missed
if not power_times:
    import re
    with open(LOG_FILE) as f:
        content = f.read()
    for m in re.finditer(r'Vuser 1:query (\d+) completed in ([\d.]+) seconds', content):
        q, t = int(m.group(1)), float(m.group(2))
        if q not in power_times:
            power_times[q] = t
    gm_m = re.search(r'Geometric mean of query times returning rows \(22\) is ([\d.]+)', content)
    if gm_m:
        geo_mean_power = float(gm_m.group(1))
    tot_m = re.search(r'Completed 1 query set.s. in (\d+) seconds', content)
    if tot_m:
        power_total_s = int(tot_m.group(1))
    import re as _re
    for m in _re.finditer(r'Vuser (\d+):Completed 1 query set.+in (\d+) seconds', content):
        vu, t = int(m.group(1)), int(m.group(2))
        thru_longest = max(thru_longest, t)
        thru_streams.setdefault(vu, [t, None])[0] = t
    for m in _re.finditer(r'Vuser (\d+):Geometric mean of query times.*is ([\d.]+)', content):
        vu, gm = int(m.group(1)), float(m.group(2))
        if vu in thru_streams:
            thru_streams[vu][1] = gm

thru_vus = len(thru_streams)
if not geo_mean_power:
    geo_mean_power = math.exp(sum(math.log(t) for t in power_times.values()) / 22)

SF = 10
POWER_SCORE = SF * 3600 / geo_mean_power
THRU_SCORE  = (thru_vus * 22 * SF * 3600) / thru_longest if thru_longest else 0
QPHH        = math.sqrt(POWER_SCORE * THRU_SCORE)

# ── Parse power CSV ────────────────────────────────────────────────────────────
power_rows = []   # [(ts_str, phase, watts)]
phase_stats = {}  # {phase: {min,max,sum,n}}
if POWER_FILE:
    with open(POWER_FILE) as f:
        for row in csv.reader(f):
            if len(row) == 3:
                ts, phase, w = row[0], row[1], float(row[2])
                power_rows.append((ts, phase, w))
                s = phase_stats.setdefault(phase, {"min":w,"max":w,"sum":0,"n":0})
                s["min"] = min(s["min"], w)
                s["max"] = max(s["max"], w)
                s["sum"] += w; s["n"] += 1

# ── ReportLab setup ────────────────────────────────────────────────────────────
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm, mm
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    HRFlowable, PageBreak, KeepTogether
)
from reportlab.graphics.shapes import Drawing, String, Line, Rect
from reportlab.graphics.charts.barcharts import VerticalBarChart
from reportlab.graphics.charts.lineplots import LinePlot

W_PAGE, H_PAGE = A4

C_BLUE      = colors.HexColor("#1565C0")
C_BLUE_LITE = colors.HexColor("#E3F2FD")
C_BLUE_MID  = colors.HexColor("#90CAF9")
C_GREEN     = colors.HexColor("#2E7D32")
C_GREEN_LITE= colors.HexColor("#E8F5E9")
C_ORANGE    = colors.HexColor("#E65100")
C_TEAL      = colors.HexColor("#00695C")
C_TEAL_LITE = colors.HexColor("#E0F2F1")
C_GREY      = colors.HexColor("#546E7A")
C_GREY_LITE = colors.HexColor("#ECEFF1")
C_WHITE     = colors.white
C_BLACK     = colors.HexColor("#212121")
C_RED       = colors.HexColor("#C62828")
C_AMBER     = colors.HexColor("#FF8F00")

styles = getSampleStyleSheet()

def S(name, **kw):
    base = styles[name] if name in styles else styles["Normal"]
    return ParagraphStyle(name + str(hash(str(kw))), parent=base, **kw)

TITLE     = S("Title",    fontSize=24, textColor=C_BLUE,  spaceAfter=4,  leading=28, alignment=TA_CENTER)
SUBTITLE  = S("Normal",   fontSize=12, textColor=C_GREY,  spaceAfter=2,  alignment=TA_CENTER)
H1        = S("Heading1", fontSize=14, textColor=C_BLUE,  spaceAfter=6,  spaceBefore=12, leading=17)
H2        = S("Heading2", fontSize=11, textColor=C_GREY,  spaceAfter=4,  spaceBefore=6,  leading=14)
BODY      = S("Normal",   fontSize=9,  textColor=C_BLACK, spaceAfter=4,  leading=13)
SMALL     = S("Normal",   fontSize=8,  textColor=C_GREY,  spaceAfter=2,  leading=11)
BOLD      = S("Normal",   fontSize=9,  textColor=C_BLACK, spaceAfter=4,  leading=13, fontName="Helvetica-Bold")
CELL      = S("Normal",   fontSize=8.5,textColor=C_BLACK, leading=12,    alignment=TA_CENTER)
CELL_L    = S("Normal",   fontSize=8.5,textColor=C_BLACK, leading=12,    alignment=TA_LEFT)
CELL_H    = S("Normal",   fontSize=8.5,textColor=C_WHITE, leading=12,    alignment=TA_CENTER, fontName="Helvetica-Bold")
RESULT    = S("Normal",   fontSize=20, textColor=C_GREEN, leading=24,    alignment=TA_CENTER, fontName="Helvetica-Bold")
RESULT_LBL= S("Normal",   fontSize=8,  textColor=C_GREY,  leading=11,    alignment=TA_CENTER)
CAPTION   = S("Normal",   fontSize=8,  textColor=C_GREY,  leading=11,    alignment=TA_CENTER, spaceAfter=4)
PWR_VAL   = S("Normal",   fontSize=20, textColor=C_AMBER, leading=24,    alignment=TA_CENTER, fontName="Helvetica-Bold")

def hr():
    return HRFlowable(width="100%", thickness=0.5, color=C_BLUE_MID, spaceAfter=6, spaceBefore=3)

def section(title):
    return [Spacer(1, 3*mm), Paragraph(title, H1), hr()]

def tbl_style(header_rows=1):
    return TableStyle([
        ("BACKGROUND",    (0,0), (-1, header_rows-1), C_BLUE),
        ("TEXTCOLOR",     (0,0), (-1, header_rows-1), C_WHITE),
        ("FONTNAME",      (0,0), (-1, header_rows-1), "Helvetica-Bold"),
        ("FONTSIZE",      (0,0), (-1,-1), 8.5),
        ("ROWBACKGROUND", (0, header_rows), (-1,-1), [C_WHITE, C_GREY_LITE]),
        ("GRID",          (0,0), (-1,-1), 0.25, colors.HexColor("#B0BEC5")),
        ("TOPPADDING",    (0,0), (-1,-1), 4),
        ("BOTTOMPADDING", (0,0), (-1,-1), 4),
        ("LEFTPADDING",   (0,0), (-1,-1), 6),
        ("RIGHTPADDING",  (0,0), (-1,-1), 6),
        ("VALIGN",        (0,0), (-1,-1), "MIDDLE"),
    ])

def metric_box(value, label, note, val_style=None, bg=C_BLUE_LITE, border=C_BLUE_MID):
    vs = val_style or RESULT
    inner = Table(
        [[Paragraph(value, vs)],
         [Paragraph(label, RESULT_LBL)],
         [Paragraph(note,  SMALL)]],
        colWidths=[4*cm],
        style=TableStyle([
            ("ALIGN",         (0,0),(-1,-1),"CENTER"),
            ("VALIGN",        (0,0),(-1,-1),"MIDDLE"),
            ("BACKGROUND",    (0,0),(-1,-1), bg),
            ("BOX",           (0,0),(-1,-1), 1, border),
            ("TOPPADDING",    (0,0),(-1,-1), 5),
            ("BOTTOMPADDING", (0,0),(-1,-1), 5),
        ])
    )
    return inner

# ── Power time-series chart ────────────────────────────────────────────────────
PHASE_COLORS = {
    "build":           colors.HexColor("#90CAF9"),
    "power_test":      colors.HexColor("#A5D6A7"),
    "throughput_test": colors.HexColor("#FFCC80"),
}
PHASE_LABELS = {
    "build":           "Schema Build",
    "power_test":      "Power Test",
    "throughput_test": "Throughput Test",
}

def power_timeseries_chart(width=16*cm, height=6*cm):
    if not power_rows:
        return Spacer(1, 1*mm)
    d = Drawing(width, height)
    chart_x, chart_y = 38, 22
    chart_w = float(width) - chart_x - 8
    chart_h = float(height) - chart_y - 18

    # Axis ranges
    all_w   = [r[2] for r in power_rows]
    max_w   = max(all_w) * 1.12
    n       = len(power_rows)
    x_scale = chart_w / max(n - 1, 1)
    y_scale = chart_h / max_w

    # Phase background bands
    phase_starts = {}
    phase_ends   = {}
    for i, (ts, phase, w) in enumerate(power_rows):
        if phase not in phase_starts:
            phase_starts[phase] = i
        phase_ends[phase] = i

    for phase, start in phase_starts.items():
        end   = phase_ends[phase]
        x0    = chart_x + start * x_scale
        x1    = chart_x + end   * x_scale
        bclr  = PHASE_COLORS.get(phase, colors.lightgrey)
        d.add(Rect(x0, chart_y, x1 - x0, chart_h,
                   fillColor=bclr, strokeColor=None, strokeWidth=0))

    # Grid lines
    step = 50 if max_w > 200 else 25
    y_val = 0
    while y_val <= max_w:
        y_px = chart_y + y_val * y_scale
        d.add(Line(chart_x, y_px, chart_x + chart_w, y_px,
                   strokeColor=colors.HexColor("#CFD8DC"), strokeWidth=0.3))
        d.add(String(chart_x - 4, y_px - 3, f"{int(y_val)}",
                     fontSize=6, fillColor=C_GREY, textAnchor="end"))
        y_val += step

    # Power line
    pts = [(chart_x + i * x_scale, chart_y + power_rows[i][2] * y_scale)
           for i in range(n)]
    for i in range(len(pts) - 1):
        d.add(Line(pts[i][0], pts[i][1], pts[i+1][0], pts[i+1][1],
                   strokeColor=C_BLUE, strokeWidth=1.2))

    # Axes
    d.add(Line(chart_x, chart_y, chart_x, chart_y + chart_h,
               strokeColor=C_GREY, strokeWidth=0.8))
    d.add(Line(chart_x, chart_y, chart_x + chart_w, chart_y,
               strokeColor=C_GREY, strokeWidth=0.8))

    # Y-axis label
    d.add(String(8, chart_y + chart_h/2, "Watts",
                 fontSize=7, fillColor=C_GREY, textAnchor="middle"))

    # Phase labels centered in each band
    for phase, start in phase_starts.items():
        end  = phase_ends[phase]
        mid  = chart_x + (start + end) / 2 * x_scale
        lbl  = PHASE_LABELS.get(phase, phase)
        d.add(String(mid, chart_y + chart_h + 6, lbl,
                     fontSize=6.5, fillColor=C_GREY, textAnchor="middle"))

    return d

# ── Per-query bar chart ────────────────────────────────────────────────────────
def query_bar_chart(width=16*cm, height=5.5*cm):
    d = Drawing(width, height)
    bc = VerticalBarChart()
    bc.x, bc.y = 30, 20
    bc.width  = float(width) - 42
    bc.height = float(height) - 30
    bc.data   = [[power_times.get(q, 0) for q in range(1, 23)]]
    bc.bars[0].fillColor   = C_BLUE
    bc.bars[0].strokeColor = None
    bc.categoryAxis.categoryNames     = [f"Q{q}" for q in range(1, 23)]
    bc.categoryAxis.labels.fontSize   = 7
    bc.valueAxis.valueMin             = 0
    bc.valueAxis.valueMax             = max(power_times.values()) * 1.15
    bc.valueAxis.valueStep            = 5 if max(power_times.values()) < 30 else 2
    bc.valueAxis.labels.fontSize      = 7
    bc.valueAxis.labelTextFormat      = "%ds"
    bc.barWidth   = 0.6
    bc.groupSpacing = 0.3
    d.add(bc)
    d.add(String(8, float(height)/2, "Time (s)",
                 fontSize=7, fillColor=C_GREY, textAnchor="middle"))
    return d

# ── Build document ─────────────────────────────────────────────────────────────
doc = SimpleDocTemplate(
    OUT, pagesize=A4,
    leftMargin=2*cm, rightMargin=2*cm,
    topMargin=2*cm,  bottomMargin=2*cm,
    title=f"TPC-H SF10 Benchmark Report — AMD EPYC 9555P",
    author="skariapaul/postgresql-bench",
)
story = []

# ── Cover ──────────────────────────────────────────────────────────────────────
story += [
    Spacer(1, 6*mm),
    Paragraph("TPC-H SF10 Benchmark Report", TITLE),
    Paragraph("PostgreSQL 17  ·  AMD EPYC 9555P  ·  with Power Consumption", SUBTITLE),
    Paragraph(f"Run date: {RUN_DATE}", SMALL),
    Spacer(1, 5*mm),
    hr(),
]

# ── Key metrics ────────────────────────────────────────────────────────────────
metrics = [
    (f"{QPHH:,.0f}",         "QphH@SF10",         "Composite score", RESULT, C_BLUE_LITE, C_BLUE_MID),
    (f"{POWER_SCORE:,.0f}",  "Power@SF10",         f"Geo mean {geo_mean_power:.2f}s", RESULT, C_BLUE_LITE, C_BLUE_MID),
    (f"{THRU_SCORE:,.0f}",   "Throughput@SF10",    f"{thru_vus} streams · {thru_longest}s", RESULT, C_BLUE_LITE, C_BLUE_MID),
    (f"{phase_stats.get('power_test',{}).get('sum',0)/max(phase_stats.get('power_test',{}).get('n',1),1):.0f} W",
     "Avg Power (query)",    "Package-0 during power test", PWR_VAL, C_TEAL_LITE, C_TEAL),
]
box_row = [[metric_box(v, l, n, vs, bg, bo) for v, l, n, vs, bg, bo in metrics]]
story.append(Table(box_row, colWidths=[4.2*cm]*4,
    style=TableStyle([("ALIGN",(0,0),(-1,-1),"CENTER"),
                      ("LEFTPADDING",(0,0),(-1,-1),2),
                      ("RIGHTPADDING",(0,0),(-1,-1),2)])))
story.append(Spacer(1, 4*mm))

# ── System & config ────────────────────────────────────────────────────────────
story += section("System & Configuration")

sys_data = [
    [Paragraph("Component", CELL_H), Paragraph("Detail", CELL_H)],
    ["CPU",          "AMD EPYC 9555P — 64 cores / 128 threads, single socket (Turin / Zen 5)"],
    ["Bench CPUs",   "32 logical CPUs — NUMA node 0 (CPUs 0-15, 64-79), NPS4"],
    ["RAM",          "377 GiB DDR5, 12 memory channels"],
    ["Storage",      "465 GB NVMe SSD"],
    ["OS",           "Ubuntu 24.04 LTS (kernel 6.8.0-83-generic)"],
    ["PostgreSQL",   "17 (Docker image postgres:17)"],
    ["HammerDB",     "5.0"],
    ["Scale factor", "SF10 — 10 GB raw data, ~20 GB on disk with indexes"],
]
t = Table([[Paragraph(str(r[0]), CELL_L), Paragraph(str(r[1]), CELL_L)]
           if i > 0 else r for i, r in enumerate(sys_data)],
          colWidths=[3.5*cm, 13*cm])
t.setStyle(tbl_style(1))
story += [t, Spacer(1, 3*mm)]

cfg_data = [
    [Paragraph("Parameter", CELL_H), Paragraph("Value", CELL_H),
     Paragraph("Parameter", CELL_H), Paragraph("Value", CELL_H)],
    ["shared_buffers",  "150 GB",    "wal_level",             "minimal"],
    ["work_mem",        "8 GB",      "autovacuum",            "off"],
    ["jit",             "on",        "max_parallel_workers",  "64"],
    ["Build threads",   "16",        "Power test dop",        "8"],
    [f"Throughput VUs", f"{thru_vus}",
     f"Throughput dop", "4"],
]
t = Table([[Paragraph(str(c), CELL_L if j%2==0 else CELL) for j,c in enumerate(row)]
           if i > 0 else row for i, row in enumerate(cfg_data)],
          colWidths=[3.5*cm, 3*cm, 4.5*cm, 5.5*cm])
t.setStyle(tbl_style(1))
story += [t, Spacer(1, 3*mm)]

# ── Power test ─────────────────────────────────────────────────────────────────
story += section("TPC-H Power Test (1 VU, dop=8)")
story.append(Paragraph(
    "The power test runs all 22 queries sequentially with a single virtual user at degree-of-"
    "parallelism 8. The primary metric is <b>Power@SF10</b> = SF × 3600 / geometric_mean_query_time.", BODY))

story.append(query_bar_chart())
story.append(Paragraph(
    f"Per-query execution times. Q13 ({power_times.get(13,0):.1f}s), "
    f"Q14 ({power_times.get(14,0):.1f}s), and Q18 ({power_times.get(18,0):.1f}s) "
    f"are the longest — all involve heavy aggregations or large joins.", CAPTION))

# Per-query table 3-col
q_items = sorted(power_times.items())
q_rows  = [[Paragraph(h, CELL_H) for h in
            ["Query","Time (s)","Query","Time (s)","Query","Time (s)"]]]
for i in range(0, 22, 3):
    row = []
    for j in range(3):
        if i+j < 22:
            q, t = q_items[i+j]
            row += [Paragraph(f"Q{q}", CELL), Paragraph(f"{t:.3f}", CELL)]
        else:
            row += ["", ""]
    q_rows.append(row)
t = Table(q_rows, colWidths=[1.5*cm, 2.2*cm]*3)
t.setStyle(tbl_style(1))

power_summary_data = [
    [Paragraph(h, CELL_H) for h in ["Total time", "Geo mean", "Power@SF10"]],
    [Paragraph(f"<b>{power_total_s} s</b>", CELL),
     Paragraph(f"<b>{geo_mean_power:.3f} s</b>", CELL),
     Paragraph(f"<b>{POWER_SCORE:,.0f}</b>", CELL)],
]
t2 = Table([[Paragraph(str(c), CELL) if not isinstance(c, Paragraph) else c for c in row]
            if i > 0 else row for i, row in enumerate(power_summary_data)],
           colWidths=[3*cm, 3*cm, 3*cm])
t2.setStyle(tbl_style(1))
story += [t, Spacer(1, 3*mm), t2, Spacer(1, 3*mm)]

# ── Throughput test ────────────────────────────────────────────────────────────
story += section(f"TPC-H Throughput Test ({thru_vus} VUs, dop=4)")
story.append(Paragraph(
    f"The throughput test runs all 22 queries across {thru_vus} concurrent streams. "
    "The primary metric is <b>Throughput@SF10</b> = (S × Q × SF × 3600) / T<sub>TT</sub>, "
    "where T<sub>TT</sub> is the elapsed time of the longest stream.", BODY))

thru_rows = [[Paragraph(h, CELL_H) for h in
              ["Stream (VU)", "Total Time (s)", "Geo Mean (s)", "vs Longest"]]]
for vu in sorted(thru_streams.keys()):
    t_s, gm = thru_streams[vu]
    delta = t_s - thru_longest
    flag = " (longest)" if t_s == thru_longest else f" (+{delta}s)" if delta > 0 else ""
    thru_rows.append([
        Paragraph(f"Stream {vu}", CELL_L),
        Paragraph(f"<b>{t_s}</b>" if t_s == thru_longest else str(t_s), CELL),
        Paragraph(f"{gm:.3f}" if gm else "—", CELL),
        Paragraph(f"baseline{flag}" if t_s == thru_longest else f"+{delta}s", CELL),
    ])

t = Table([[Paragraph(str(c), CELL) if not isinstance(c, Paragraph) else c for c in row]
           if i > 0 else row for i, row in enumerate(thru_rows)],
          colWidths=[3*cm, 3*cm, 3*cm, 7.5*cm])
t.setStyle(tbl_style(1))

thru_summary = [
    [Paragraph(h, CELL_H) for h in ["Streams", "Longest stream", "Throughput@SF10"]],
    [str(thru_vus),
     Paragraph(f"<b>{thru_longest} s</b>", CELL),
     Paragraph(f"<b>{THRU_SCORE:,.0f}</b>", CELL)],
]
t2 = Table([[Paragraph(str(c), CELL) if not isinstance(c, Paragraph) else c for c in row]
            if i > 0 else row for i, row in enumerate(thru_summary)],
           colWidths=[2*cm, 3*cm, 3.5*cm])
t2.setStyle(tbl_style(1))
story += [t, Spacer(1, 3*mm), t2, Spacer(1, 3*mm)]

# ── QphH ──────────────────────────────────────────────────────────────────────
qphh_box = Table(
    [[Paragraph(
        f"QphH@SF10 = √({POWER_SCORE:,.0f} × {THRU_SCORE:,.0f}) = <b>{QPHH:,.0f}</b>",
        S("Normal", fontSize=13, textColor=C_GREEN, fontName="Helvetica-Bold",
          alignment=TA_CENTER, leading=18))]],
    colWidths=[16.5*cm],
    style=TableStyle([
        ("BACKGROUND", (0,0),(-1,-1), C_GREEN_LITE),
        ("BOX",        (0,0),(-1,-1), 1.5, C_GREEN),
        ("TOPPADDING",    (0,0),(-1,-1), 8),
        ("BOTTOMPADDING", (0,0),(-1,-1), 8),
    ])
)
story += [qphh_box, Spacer(1, 4*mm)]

# ── Power consumption section ──────────────────────────────────────────────────
story += section("Power Consumption (AMD RAPL — Package-0)")
story.append(Paragraph(
    "Power sampled every 5 seconds via AMD RAPL energy counter "
    "(<code>/sys/class/powercap/intel-rapl:0/energy_uj</code>). "
    "Measures total CPU package power including cores, uncore, and memory controller. "
    "Does not include DRAM or storage device power.", BODY))

# Time series chart
story.append(power_timeseries_chart())
story.append(Paragraph(
    "Package-0 power over time. Coloured bands: "
    "<font color='#7986CB'>■</font> Schema Build  "
    "<font color='#66BB6A'>■</font> Power Test  "
    "<font color='#FFA726'>■</font> Throughput Test", CAPTION))

# Per-phase stats table
phase_order = ["build", "power_test", "throughput_test"]
pwr_rows = [[Paragraph(h, CELL_H) for h in
             ["Phase", "Samples", "Duration", "Min W", "Avg W", "Max W", "Avg Energy (Wh)"]]]
for phase in phase_order:
    if phase not in phase_stats:
        continue
    s   = phase_stats[phase]
    avg = s["sum"] / s["n"]
    dur_s = s["n"] * 5
    wh  = avg * dur_s / 3600
    pwr_rows.append([
        Paragraph(PHASE_LABELS.get(phase, phase), CELL_L),
        str(s["n"]),
        f"{dur_s}s (~{dur_s//60}m {dur_s%60}s)",
        Paragraph(f"{s['min']:.0f}", CELL),
        Paragraph(f"<b>{avg:.0f}</b>", CELL),
        Paragraph(f"{s['max']:.0f}", CELL),
        Paragraph(f"{wh:.1f}", CELL),
    ])
t = Table([[Paragraph(str(c), CELL) if not isinstance(c, Paragraph) else c for c in row]
           if i > 0 else row for i, row in enumerate(pwr_rows)],
          colWidths=[3.2*cm, 1.6*cm, 2.8*cm, 1.6*cm, 1.6*cm, 1.6*cm, 2.5*cm])
t.setStyle(tbl_style(1))
t.setStyle(TableStyle([
    ("BACKGROUND", (0, 2), (-1, 2), C_GREEN_LITE),   # power_test row highlight
]))
story += [t, Spacer(1, 3*mm)]
story.append(Paragraph(
    "Energy (Wh) = avg_watts × duration_seconds / 3600. "
    "The power test phase represents the actual benchmark-under-test period. "
    "Higher parallelism during throughput test drives higher sustained power draw.", SMALL))

# ── Efficiency metrics ─────────────────────────────────────────────────────────
story += [Spacer(1, 3*mm), Paragraph("Performance per Watt", H2)]
ptest_avg_w  = phase_stats.get("power_test",  {}).get("sum", 0) / max(phase_stats.get("power_test",  {}).get("n", 1), 1)
ttest_avg_w  = phase_stats.get("throughput_test", {}).get("sum", 0) / max(phase_stats.get("throughput_test", {}).get("n", 1), 1)
qphh_per_w   = QPHH / ((ptest_avg_w + ttest_avg_w) / 2) if ptest_avg_w else 0

eff_rows = [
    [Paragraph(h, CELL_H) for h in ["Metric", "Value", "Notes"]],
    [Paragraph("QphH per Watt", CELL_L),
     Paragraph(f"<b>{qphh_per_w:.1f}</b>", CELL),
     "QphH@SF10 ÷ avg(power_test, throughput_test) watts"],
    [Paragraph("Power test avg power", CELL_L),
     Paragraph(f"{ptest_avg_w:.0f} W", CELL),
     f"Range: {phase_stats.get('power_test',{}).get('min',0):.0f}–{phase_stats.get('power_test',{}).get('max',0):.0f} W during single-stream queries"],
    [Paragraph("Throughput test avg power", CELL_L),
     Paragraph(f"{ttest_avg_w:.0f} W", CELL),
     f"Range: {phase_stats.get('throughput_test',{}).get('min',0):.0f}–{phase_stats.get('throughput_test',{}).get('max',0):.0f} W during {thru_vus} concurrent streams"],
    [Paragraph("Power headroom", CELL_L),
     Paragraph(f"{280 - max(ptest_avg_w, ttest_avg_w):.0f} W below TDP", CELL),
     "EPYC 9555P TDP = 280 W; peak measured power well below TDP"],
]
t = Table([[Paragraph(str(c), CELL) if not isinstance(c, Paragraph) else c for c in row]
           if i > 0 else row for i, row in enumerate(eff_rows)],
          colWidths=[4*cm, 3*cm, 9.5*cm])
t.setStyle(tbl_style(1))
story += [t, Spacer(1, 4*mm)]

# ── Footer ─────────────────────────────────────────────────────────────────────
story += [
    hr(),
    Paragraph(
        f"Informal benchmark — not TPC-audited. "
        f"Power measured via AMD RAPL (package-0 energy counter). "
        f"Source: <a href='https://github.com/skariapaul/postgresql-bench' color='#1565C0'>"
        f"github.com/skariapaul/postgresql-bench</a>. "
        f"Report generated {datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}.",
        SMALL),
]

doc.build(story)
print(f"Report written to: {OUT}")
