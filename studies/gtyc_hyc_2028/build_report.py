#!/usr/bin/env python
"""
Build the self-contained HTML report for the GTYC / HYC wind analysis.

Reads the CSV/PNG outputs in OUT_DIR (written by `python -m hrrr_wind.venue_analysis`),
embeds figures as base64, draws two native SVG charts (per-year means and
speed-bin mix, raw vs bias-adjusted), and writes Venue_Wind_Report_GTYC_HYC.html.
Tables are generated from the CSVs so they cannot drift from the analysis.
"""
import base64
import html
import json
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
from hrrr_wind.config import load_study
from hrrr_wind.stats import load_series

STUDY = load_study(Path(__file__).parent / "study.toml")
OUT = STUDY.out_dir
REPORT = OUT / "Venue_Wind_Report_GTYC_HYC.html"
ARTIFACT = OUT / "Venue_Wind_Report_artifact.html"

SUMMARY = pd.read_csv(OUT / "summary_stats.csv")
PERYEAR = pd.read_csv(OUT / "per_year_stats.csv")
PAIRED = pd.read_csv(OUT / "paired_sep_hyc_minus_gtyc.csv")
BAND = pd.read_csv(OUT / "sensitivity_band.csv")
VALID = pd.read_csv(OUT / "validation_metrics.csv")
ADJ = pd.read_csv(OUT / "bias_adjusted_summary.csv")
QUALITY = pd.read_csv(OUT / "data_quality.csv")
MISS_SEP = json.load(open(OUT / "missing_sep_2015_2025.json"))
MISS_JUN = json.load(open(OUT / "missing_jun_2015_2025.json"))

SERIES = [("gtyc", "sep", "GTYC Sept 8–14"), ("hyc", "sep", "HYC Sept 8–14"),
          ("hyc", "jun", "HYC June 14–21")]


def esc(s):
    return html.escape(str(s))


def img(name, alt):
    b64 = base64.b64encode((OUT / name).read_bytes()).decode()
    return f'<img src="data:image/png;base64,{b64}" alt="{esc(alt)}" loading="lazy">'


def row(venue, season, scope="core"):
    r = SUMMARY[(SUMMARY.venue == venue) & (SUMMARY.season == season) & (SUMMARY.scope == scope)]
    return r.iloc[0]


def ci(r, k, d=1):
    return f"{r[k + '_lo']:.{d}f}–{r[k + '_hi']:.{d}f}"


def rng(a, b, d=1, unit=""):
    """Format min-max of two values, collapsing to one number when they round equal."""
    lo, hi = sorted((a, b))
    sa, sb = f"{lo:.{d}f}", f"{hi:.{d}f}"
    return f"{sa}{unit}" if sa == sb else f"{sa}–{sb}{unit}"


def srng(a, b, d=1):
    """Signed range, ascending, 'a to b'; collapses when equal after rounding."""
    f = lambda v: f"{v:+.{d}f}".replace("-", "−")
    lo, hi = sorted((a, b))
    return f(lo) if f(lo) == f(hi) else f"{f(lo)} to {f(hi)}"


def table(headers, rows, cls="", first_left=True):
    th = "".join(f"<th scope='col'>{h}</th>" for h in headers)
    body = ""
    for r in rows:
        tds = "".join(f"<td>{c}</td>" for c in r)
        body += f"<tr>{tds}</tr>"
    return f"<div class='tablewrap'><table class='{cls}'><thead><tr>{th}</tr></thead><tbody>{body}</tbody></table></div>"


# ---------------------------------------------------------------- derived numbers
def ge20(r):
    return r["pct_ge20"]


core = {(v, s): row(v, s) for v, s, _ in SERIES}
buffer = {(v, s): row(v, s, "buffer") for v, s, _ in SERIES}
paired = {m.replace("HYC - GTYC ", ""): r for m, r in zip(PAIRED["metric"], PAIRED.itertuples())}

# local-hour means (EDT) for the core windows, all 24 h
diurnal = {}
for w in STUDY.windows:
    d = load_series(STUDY, w.venue, w.cache_tag)
    d = d[(d.md >= w.lo) & (d.md <= w.hi)]
    h = d.groupby("hour").spd_kt.mean()
    diurnal[(w.venue, w.season)] = pd.Series(h.values, index=(h.index + STUDY.utc_offset) % 24).sort_index()

# ---------------------------------------------------------------- chart 1: per-year means (SVG)
YEARS = list(range(2015, 2026))


def chart_per_year():
    W, H, L, R, T, B = 760, 330, 46, 18, 14, 40
    pw, ph = W - L - R, H - T - B
    ymax = 14.0
    xs = {y: L + pw * (i + 0.5) / len(YEARS) for i, y in enumerate(YEARS)}
    yv = lambda v: T + ph * (1 - v / ymax)
    s = [f'<svg viewBox="0 0 {W} {H}" class="chart" role="img" '
         f'aria-label="Mean racing-hour wind by year for three venue windows">']
    for t in (0, 4, 8, 12):
        s.append(f'<line class="grid" x1="{L}" x2="{W - R}" y1="{yv(t):.1f}" y2="{yv(t):.1f}"/>')
        s.append(f'<text class="tick" x="{L - 8}" y="{yv(t) + 4:.1f}" text-anchor="end">{t}</text>')
    s.append(f'<text class="axlabel" x="{L - 36}" y="{T + ph / 2:.0f}" text-anchor="middle" '
             f'transform="rotate(-90 {L - 36} {T + ph / 2:.0f})">Mean wind (kt)</text>')
    for y in YEARS:
        s.append(f'<text class="tick" x="{xs[y]:.1f}" y="{H - 14}" text-anchor="middle">{y}</text>')
    s.append(f'<line class="baseline" x1="{L}" x2="{W - R}" y1="{yv(0):.1f}" y2="{yv(0):.1f}"/>')
    s.append('<line id="xhair" class="xhair" x1="0" x2="0" y1="%d" y2="%d" style="display:none"/>'
             % (T, T + ph))
    for i, (v, sea, label) in enumerate(SERIES):
        data = PERYEAR[(PERYEAR.venue == v) & (PERYEAR.season == sea)].set_index("year")["mean"]
        pts = " ".join(f"{xs[y]:.1f},{yv(data[y]):.1f}" for y in YEARS if y in data.index)
        s.append(f'<polyline class="line s{i + 1}" points="{pts}"/>')
        for y in YEARS:
            if y in data.index:
                s.append(f'<circle class="dot s{i + 1}" cx="{xs[y]:.1f}" cy="{yv(data[y]):.1f}" r="4"/>')
    # hover columns
    colw = pw / len(YEARS)
    for y in YEARS:
        vals = []
        for v, sea, label in SERIES:
            d = PERYEAR[(PERYEAR.venue == v) & (PERYEAR.season == sea) & (PERYEAR.year == y)]
            vals.append(f"{label}: {d['mean'].iloc[0]:.1f} kt" if len(d) else f"{label}: n/a")
        tip = f"<b>{y}</b><br>" + "<br>".join(vals)
        s.append(f'<rect class="hit" data-x="{xs[y]:.1f}" data-tip="{esc(tip)}" '
                 f'x="{xs[y] - colw / 2:.1f}" y="{T}" width="{colw:.1f}" height="{ph}"/>')
    s.append("</svg>")
    legend = "".join(f'<span class="key"><i class="sw s{i + 1}"></i>{label}</span>'
                     for i, (_, _, label) in enumerate(SERIES))
    return f'<div class="legend">{legend}</div>' + "".join(s)


# ---------------------------------------------------------------- chart 2: speed mix raw vs adjusted
BIN_COLORS = ["var(--r1)", "var(--r2)", "var(--r3)"]
BIN_NAMES = ["< 5 kt (light)", "5–20 kt (sweet spot)", "≥ 20 kt (heavy)"]


def chart_mix():
    rows = []
    for v, sea, label in SERIES:
        raw = ADJ[(ADJ.venue == v) & (ADJ.season == sea) & (ADJ.version == "HRRR raw")].iloc[0]
        adj = ADJ[(ADJ.venue == v) & (ADJ.season == sea) & (ADJ.version != "HRRR raw")].iloc[0]
        rows.append((label, "HRRR as retrieved", raw))
        rows.append((label, "Bias-adjusted", adj))
    W, L, R, T = 760, 190, 20, 8
    rowh, barh = 40, 22
    H = T + rowh * len(rows) + 34
    bw = W - L - R
    s = [f'<svg viewBox="0 0 {W} {H}" class="chart" role="img" '
         f'aria-label="Share of racing hours by wind speed bin, raw versus bias-adjusted">']
    for t in (0, 25, 50, 75, 100):
        x = L + bw * t / 100
        s.append(f'<line class="grid" x1="{x:.1f}" x2="{x:.1f}" y1="{T}" y2="{T + rowh * len(rows) - 6}"/>')
        s.append(f'<text class="tick" x="{x:.1f}" y="{H - 10}" text-anchor="middle">{t}%</text>')
    for i, (label, ver, r) in enumerate(rows):
        y = T + i * rowh + (4 if i % 2 == 0 else 0)
        yc = y + barh / 2 + 4
        if ver == "HRRR as retrieved":
            s.append(f'<text class="rowlab" x="{L - 12}" y="{yc - 8:.1f}" text-anchor="end">{esc(label)}</text>')
            s.append(f'<text class="rowsub" x="{L - 12}" y="{yc + 6:.1f}" text-anchor="end">{ver}</text>')
        else:
            s.append(f'<text class="rowsub" x="{L - 12}" y="{yc:.1f}" text-anchor="end">{ver}</text>')
        vals = [r["pct_lt5"], r["pct_5_20"], r["pct_ge20"]]
        clip = f"clip{i}"
        s.append(f'<clipPath id="{clip}"><rect x="{L}" y="{y}" width="{bw}" height="{barh}" rx="4"/></clipPath>')
        s.append(f'<g clip-path="url(#{clip})">')
        x = L
        for k, p in enumerate(vals):
            w = bw * p / 100
            tip = (f"<b>{esc(label)} — {ver}</b><br>{BIN_NAMES[k]}: {p:.1f}%<br>"
                   f"mean {r['mean']:.1f} kt")
            gap = 2 if k < 2 else 0
            if w > 0.5:
                s.append(f'<rect class="seg hit2" x="{x:.1f}" y="{y}" width="{max(w - gap, 0.5):.1f}" '
                         f'height="{barh}" fill="{BIN_COLORS[k]}" data-tip="{esc(tip)}"/>')
                if w >= 40:
                    fill = "#0b0b0b"
                    s.append(f'<text class="seglab" x="{x + (w - gap) / 2:.1f}" y="{y + barh / 2 + 4:.1f}" '
                             f'text-anchor="middle" fill="{fill}">{p:.0f}%</text>')
            x += w
        s.append("</g>")
    s.append("</svg>")
    legend = "".join(f'<span class="key"><i class="sw" style="background:{BIN_COLORS[k]}"></i>{BIN_NAMES[k]}</span>'
                     for k in range(3))
    return f'<div class="legend">{legend}</div>' + "".join(s)


# ---------------------------------------------------------------- tables
def results_table():
    def cell(v, s, key, d=1, with_ci=True):
        r = core[(v, s)]
        txt = f"{r[key]:.{d}f}"
        return f"<b>{txt}</b> <small>({ci(r, key, d)})</small>" if with_ci else txt

    def ge(v, s):
        r = core[(v, s)]
        return f"<b>{ge20(r):.1f}%</b> <small>({r['pct_ge20_lo']:.1f}–{r['pct_ge20_hi']:.1f})</small>"

    keys = [(v, s) for v, s, _ in SERIES]
    rows = [
        ["Racing-hour samples"] + [str(int(core[k]["n"])) for k in keys],
        ["Mean (kt)"] + [cell(*k, "mean") for k in keys],
        ["Median / 90th pct (kt)"] + [f"{core[k]['median']:.1f} / {core[k]['p90']:.1f}" for k in keys],
        ["Maximum (kt)"] + [f"{core[k]['max']:.1f}" for k in keys],
        ["&lt; 5 kt"] + [f"<b>{core[k]['pct_lt5']:.0f}%</b> <small>({ci(core[k], 'pct_lt5', 0)})</small>" for k in keys],
        ["5–20 kt"] + [f"<b>{core[k]['pct_5_20']:.0f}%</b> <small>({ci(core[k], 'pct_5_20', 0)})</small>" for k in keys],
        ["≥ 20 kt"] + [ge(*k) for k in keys],
        ["Usable days (≥3 h in 5–20 kt)"] + [f"<b>{core[k]['usable_day_pct']:.0f}%</b> <small>({ci(core[k], 'usable_day', 0)})</small>" for k in keys],
        ["Direction steadiness R"] + [f"{core[k]['R']:.2f}" for k in keys],
    ]
    return table(["Racing hours, HRRR as retrieved"] + [l for _, _, l in SERIES], rows, "num")


def buffer_table():
    rows = []
    for v, s, label in SERIES:
        b = buffer[(v, s)]
        rows.append([label, f"{b['mean']:.1f} <small>({ci(b, 'mean')})</small>",
                     f"{b['pct_5_20']:.0f}%", f"{ge20(b):.1f}%", str(int(b["n"]))])
    return table(["Window ±3 days", "Mean kt (95% CI)", "5–20 kt", "≥ 20 kt", "Samples"], rows, "num")


def paired_table():
    nm = {"mean_kt": "Mean wind (kt)", "pct_5_20": "Share in 5–20 kt (points)",
          "pct_ge20": "Share ≥ 20 kt (points)"}
    rows = []
    for _, r in PAIRED.iterrows():
        k = r["metric"].replace("HYC - GTYC ", "")
        sig = "distinguishable" if (r["lo"] > 0 or r["hi"] < 0) else "not distinguishable"
        rows.append([nm[k], f"{r['diff']:+.1f}".replace("-", "−"),
                     f"{r['lo']:+.1f} to {r['hi']:+.1f}".replace("-", "−"), sig])
    return table(["HYC minus GTYC (September)", "Difference", "95% CI", "Verdict"], rows, "num")


def band_table():
    rows = []
    for v, s, label in SERIES:
        b = BAND[(BAND.venue == v) & (BAND.season == s)]
        rows.append([label, f"{b['mean'].min():.1f}–{b['mean'].max():.1f}",
                     f"{b.pct_lt5.min():.0f}–{b.pct_lt5.max():.0f}%",
                     f"{b.pct_5_20.min():.0f}–{b.pct_5_20.max():.0f}%",
                     f"{b.pct_ge20.min():.1f}–{b.pct_ge20.max():.1f}%"])
    return table(["Offshore 1–6 nm × radius 2–6 nm", "Mean (kt)", "&lt; 5 kt", "5–20 kt", "≥ 20 kt"], rows, "num")


def peryear_table():
    rows = []
    for y in YEARS:
        cells = [str(y)]
        for v, s, _ in SERIES:
            d = PERYEAR[(PERYEAR.venue == v) & (PERYEAR.season == s) & (PERYEAR.year == y)].iloc[0]
            cells.append(f"{d['mean']:.1f} <small>({d['pct_ge20']:.0f}% ≥20)</small>")
        rows.append(cells)
    return table(["Year"] + [l for _, _, l in SERIES], rows, "num")


def diurnal_table():
    hours = list(range(9, 19))
    lab = lambda h: f"{h if h <= 12 else h - 12}{'AM' if h < 12 else 'PM'}"
    rows = []
    for v, s, label in SERIES:
        ser = diurnal[(v, s)]
        rows.append([label] + [f"{ser.loc[h]:.1f}" for h in hours])
    return table(["Local hour (EDT)"] + [lab(h) for h in hours], rows, "num")


def validation_tables():
    def pick(venue, mode, adj, subset="racing hrs (14-20 UTC)"):
        m = VALID[(VALID.venue == venue) & (VALID.hrrr_sampling == mode) &
                  (VALID.height_adj.str.startswith(adj)) & (VALID.subset == subset)]
        return m.iloc[0]
    rows = []
    for venue, label in (("gtyc", "GTYC · buoy 45020"), ("hyc", "HYC · buoy 45163")):
        modes = ("nearest water cell", "2 nm water box")
        L = [pick(venue, m, "log") for m in modes]
        R = [pick(venue, m, "raw") for m in modes]
        P = [pick(venue, m, "power") for m in modes]
        rows.append([venue.upper(), f"{int(L[1]['n']):,}",
                     srng(L[0]['bias_kt'], L[1]['bias_kt']),
                     srng(R[0]['bias_kt'], R[1]['bias_kt']),
                     srng(P[0]['bias_kt'], P[1]['bias_kt']),
                     rng(L[0]['corr_r'], L[1]['corr_r'], 2),
                     rng(L[0]['rmse_kt'], L[1]['rmse_kt']),
                     rng(L[0]['same_category_pct'], L[1]['same_category_pct'], 0, "%"),
                     f"{L[1]['dir_bias_deg']:+.0f}° / {L[1]['dir_mae_deg']:.0f}°".replace("-", "−")])
    t1 = table(["Racing hrs", "Hours", "Bias, log adj.", "Bias, raw", "Bias, power law",
                "Corr.", "RMSE", "Same bin", "Dir. bias / MAE"],
               rows, "num dense")
    rows = []
    for venue, label in (("gtyc", "GTYC"), ("hyc", "HYC")):
        a = pick(venue, "nearest water cell", "log")
        b2 = pick(venue, "2 nm water box", "log")
        rows.append([label,
                     f"{a['obs_pct_lt5']:.1f} / {a['obs_pct_5_20']:.1f} / {a['obs_pct_ge20']:.1f}%",
                     f"{rng(a['hrrr_pct_lt5'], b2['hrrr_pct_lt5'], 0)} / "
                     f"{rng(a['hrrr_pct_5_20'], b2['hrrr_pct_5_20'], 0)} / "
                     f"{rng(a['hrrr_pct_ge20'], b2['hrrr_pct_ge20'], 1)}%"])
    t2 = table(["Share of racing hours: &lt;5 / 5–20 / ≥20 kt", "Buoy (10 m-adjusted)", "HRRR at the buoy"],
               rows, "num")
    return t1, t2


def adjusted_table():
    rows = []
    for v, s, label in SERIES:
        for ver in ("HRRR raw", "adj"):
            q = ADJ[(ADJ.venue == v) & (ADJ.season == s)]
            r = q[q.version == "HRRR raw"].iloc[0] if ver == "HRRR raw" else q[q.version != "HRRR raw"].iloc[0]
            name = "HRRR as retrieved" if ver == "HRRR raw" else "Bias-adjusted (quantile mapping)"
            rows.append([label if ver == "HRRR raw" else "", name, f"{r['mean']:.1f}",
                         f"{r['pct_lt5']:.0f}%", f"{r['pct_5_20']:.0f}%", f"{r['pct_ge20']:.1f}%",
                         "" if ver == "HRRR raw" else f"{int(r['n_fit_pairs'])}"])
    return table(["Window", "Version", "Mean kt", "&lt; 5 kt", "5–20 kt", "≥ 20 kt", "Fit pairs"], rows, "num l2")


def quality_tables():
    q = QUALITY.set_index(["venue", "season"])
    rows = []
    for v, s, label in SERIES:
        r = q.loc[(v, s)]
        rows.append([label, f"{int(r['race_hours_present'])} / {int(r['race_hours_expected'])}",
                     f"{int(r['hours_present_24h']):,} / {int(r['hours_expected_24h']):,}"])
    t1 = table(["Core window", "Racing hours present / expected", "All hours present / expected"], rows, "num")
    yrs = [str(y) for y in range(2015, 2026)]
    rows = [["Sept 5–17 (312 h/yr)"] + [str(len(MISS_SEP.get(y, []))) for y in yrs],
            ["June 11–24 (336 h/yr)"] + [str(len(MISS_JUN.get(y, []))) for y in yrs]]
    t2 = table(["Missing hours"] + yrs, rows, "num")
    return t1, t2


# ---------------------------------------------------------------- assemble
CSS = """
:root{
  --page:#f9f9f7; --surface:#fcfcfb; --ink:#0b0b0b; --ink2:#52514e; --muted:#6f6d68;
  --grid:#e1e0d9; --axis:#c3c2b7; --border:rgba(11,11,11,.10); --wash:#f1f0ec;
  --s1:#2a78d6; --s2:#eb6834; --s3:#1baf7a;
  --r1:#5b9bd8; --r2:#55b878; --r3:#d9822b;
  --callout:#eaf2fd; --callout-border:#9ec5f4; --warn:#fdf3e1; --warn-border:#eda100;
  color-scheme: light;
}
@media (prefers-color-scheme: dark){
  :root:where(:not([data-theme="light"])){
    --page:#0d0d0d; --surface:#1a1a19; --ink:#f0efec; --ink2:#c3c2b7; --muted:#a09e97;
    --grid:#2c2c2a; --axis:#383835; --border:rgba(255,255,255,.10); --wash:#242422;
    --s1:#3987e5; --s2:#d95926; --s3:#199e70;
    --callout:#16263a; --callout-border:#256abf; --warn:#33290f; --warn-border:#c98500;
    color-scheme: dark;
  }
}
:root[data-theme="dark"]{
  --page:#0d0d0d; --surface:#1a1a19; --ink:#f0efec; --ink2:#c3c2b7; --muted:#a09e97;
  --grid:#2c2c2a; --axis:#383835; --border:rgba(255,255,255,.10); --wash:#242422;
  --s1:#3987e5; --s2:#d95926; --s3:#199e70;
  --callout:#16263a; --callout-border:#256abf; --warn:#33290f; --warn-border:#c98500;
  color-scheme: dark;
}
*{box-sizing:border-box}
html{scroll-behavior:smooth}
body{margin:0;background:var(--page);color:var(--ink);
  font:16px/1.55 system-ui,-apple-system,"Segoe UI",sans-serif}
.wrap{max-width:920px;margin:0 auto;padding-block:32px 72px;padding-left:max(16px,env(safe-area-inset-left,0px));padding-right:max(16px,env(safe-area-inset-right,0px))}
.tile,.fig,.callout{min-width:0}
header.top{padding:8px 0 20px;border-bottom:1px solid var(--grid);margin-bottom:8px}
h1{font-size:30px;line-height:1.2;margin:0 0 6px;font-weight:650;letter-spacing:-.01em}
.sub{color:var(--ink2);margin:0}
.meta{display:flex;flex-wrap:wrap;gap:6px 18px;color:var(--ink2);font-size:14px;margin-top:12px}
nav.toc{display:flex;flex-wrap:wrap;gap:4px 14px;margin:16px 0 8px;font-size:14px}
nav.toc a{color:var(--ink2);text-decoration:none;border-bottom:1px solid var(--axis)}
nav.toc a:hover{color:var(--ink)}
h2{font-size:21px;margin:44px 0 8px;font-weight:650;letter-spacing:-.005em}
h3{font-size:16px;margin:26px 0 6px;font-weight:650}
p{margin:8px 0}
.lede{color:var(--ink2)}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:12px;margin:18px 0 6px}
.tile{background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:14px 16px}
.tile .v{font-size:28px;font-weight:650;line-height:1.15}
.tile .l{color:var(--ink2);font-size:14px;margin-top:4px}
.tile .n{color:var(--muted);font-size:12.5px;margin-top:6px}
ol.find{padding-left:22px;margin:10px 0}
ol.find li{margin:9px 0}
.fig{margin:16px 0 8px;background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:14px}
.fig img{display:block;width:100%;height:auto;background:#fff;border-radius:6px}
.fig .cap{font-size:13.5px;color:var(--ink2);margin:10px 2px 0}
.fig .cap b{color:var(--ink)}
.cols2{display:grid;grid-template-columns:1fr 1fr;gap:12px}
@media (max-width:760px){.cols2{grid-template-columns:1fr}}
.tablewrap{overflow-x:auto;margin:10px 0 4px;border:1px solid var(--border);border-radius:10px;background:var(--surface)}
table{border-collapse:collapse;width:100%;font-size:14px}
th,td{padding:8px 12px;text-align:left;vertical-align:top;border-bottom:1px solid var(--grid)}
table.num th:not(:first-child),table.num td:not(:first-child){text-align:right;white-space:nowrap}
table.l2 th:nth-child(2),table.l2 td:nth-child(2){text-align:left}
table.dense{font-size:13px}
table.dense th,table.dense td{padding:7px 8px}
table.dense th{white-space:normal;vertical-align:bottom}
thead th{font-weight:600;color:var(--ink2);background:var(--wash);font-size:13px}
tbody tr:last-child td{border-bottom:none}
table.num td,table.num th{font-variant-numeric:tabular-nums}
table.text td:first-child{font-weight:600;white-space:nowrap}
small{color:var(--muted);font-size:12px}
.callout{background:var(--callout);border:1px solid var(--callout-border);border-radius:10px;padding:12px 16px;margin:14px 0}
.callout.warn{background:var(--warn);border-color:var(--warn-border)}
.callout p{margin:4px 0}
details{margin:10px 0}
summary{cursor:pointer;color:var(--ink2);font-size:14px}
.legend{display:flex;flex-wrap:wrap;gap:6px 18px;margin:2px 0 6px;font-size:13.5px;color:var(--ink2)}
.key{display:inline-flex;align-items:center;gap:7px}
.sw{display:inline-block;width:12px;height:12px;border-radius:3px}
.sw.s1,.line.s1,.dot.s1{background:var(--s1);stroke:var(--s1);fill:var(--s1)}
.sw.s2,.line.s2,.dot.s2{background:var(--s2);stroke:var(--s2);fill:var(--s2)}
.sw.s3,.line.s3,.dot.s3{background:var(--s3);stroke:var(--s3);fill:var(--s3)}
svg.chart{width:100%;height:auto;display:block;overflow:visible}
svg .grid{stroke:var(--grid);stroke-width:1}
svg .baseline{stroke:var(--axis);stroke-width:1}
svg .xhair{stroke:var(--axis);stroke-width:1}
svg .tick{fill:var(--muted);font-size:12px}
svg .axlabel{fill:var(--muted);font-size:12px}
svg .rowlab{fill:var(--ink);font-size:13px;font-weight:600}
svg .rowsub{fill:var(--ink2);font-size:12px}
svg .seglab{font-size:12px;font-weight:600;pointer-events:none}
svg .line{fill:none !important;stroke-width:2;stroke-linejoin:round;stroke-linecap:round}
svg .dot{stroke:var(--surface) !important;stroke-width:2}
svg .hit{fill:transparent}
svg .hit2{cursor:default}
#tip{position:fixed;z-index:10;pointer-events:none;display:none;background:var(--surface);color:var(--ink);
  border:1px solid var(--axis);border-radius:8px;padding:8px 10px;font-size:13px;line-height:1.45;
  box-shadow:0 4px 14px rgba(0,0,0,.18);max-width:260px}
.files code,code{font:13px ui-monospace,SFMono-Regular,Menlo,monospace;background:var(--wash);padding:1px 5px;border-radius:4px}
p.small{font-size:13px;color:var(--muted)}
footer{margin-top:48px;padding-top:16px;border-top:1px solid var(--grid);color:var(--muted);font-size:13px}
@media print{
  body{background:#fff}.wrap{max-width:none;padding:0}nav.toc,#tip{display:none}
  .fig,.tile,.tablewrap{break-inside:avoid}h2{break-after:avoid}
}
"""

JS = """
(function(){
  var tip=document.getElementById('tip'), xh=document.getElementById('xhair');
  function show(e,html){tip.innerHTML=html;tip.style.display='block';
    var w=tip.offsetWidth,h=tip.offsetHeight,x=e.clientX+14,y=e.clientY+14;
    if(x+w>window.innerWidth-8)x=e.clientX-w-14; if(y+h>window.innerHeight-8)y=e.clientY-h-14;
    tip.style.left=x+'px';tip.style.top=y+'px';}
  function hide(){tip.style.display='none';if(xh)xh.style.display='none';}
  document.querySelectorAll('[data-tip]').forEach(function(el){
    el.addEventListener('pointermove',function(e){
      show(e,el.getAttribute('data-tip'));
      var x=el.getAttribute('data-x'); if(xh&&x){xh.setAttribute('x1',x);xh.setAttribute('x2',x);xh.style.display='block';}
    });
    el.addEventListener('pointerleave',hide);
  });
})();
"""


def build():
    g, hs, hj = core[("gtyc", "sep")], core[("hyc", "sep")], core[("hyc", "jun")]
    d_mean, d_sw = paired["mean_kt"], paired["pct_5_20"]
    assert d_sw.lo > 0, "sweet-spot finding in the Bottom line assumes the CI excludes 0"
    gd = diurnal[("gtyc", "sep")]
    val1, val2 = validation_tables()
    q1, q2 = quality_tables()
    figs_summary = (
        f'<div class="fig">{img("summary_gtyc_sep.png", "GTYC September wind rose, speed distribution and statistics")}'
        f'<p class="cap"><b>GTYC, Sept 8–14.</b> Wind rose (direction wind blows <i>from</i>), speed mix and statistics for racing hours, 2015–2025. Light air is the main shortfall, and HRRR shows essentially no hours at 20 kt or more.</p></div>'
        f'<div class="fig">{img("summary_hyc_sep.png", "HYC September wind rose, speed distribution and statistics")}'
        f'<p class="cap"><b>HYC, Sept 8–14.</b> Flow is mostly from the north through north-east and from the south-west to west; about three racing hours in four fall in the 5–20 kt sweet spot, and almost none reach 20 kt.</p></div>'
        f'<div class="fig">{img("summary_hyc_jun.png", "HYC June wind rose, speed distribution and statistics")}'
        f'<p class="cap"><b>HYC, June 14–21.</b> Similar to September in speed mix, with a slightly heavier tail (maximum 26.5 kt).</p></div>')

    html_doc = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Venue Wind Report</title>
<style>{CSS}</style></head>
<body><div class="wrap">

<header class="top">
  <h1>GTYC vs. HYC (Caseville): historical wind</h1>
  <p class="sub">What eleven seasons of HRRR model data, checked against on-water buoys, say about each venue's wind in mid-September and mid-June.</p>
  <div class="meta">
    <span><b>Venues</b> Grand Traverse YC · Huron YC, Caseville</span>
    <span><b>Windows</b> Sept 8–14 (both) · June 14–21 (HYC)</span>
    <span><b>Racing hours</b> 10 AM–4 PM EDT</span>
    <span><b>Years</b> 2015–2025</span>
    <span><b>Prepared</b> October 2026</span>
  </div>
  <nav class="toc" aria-label="Sections">
    <a href="#bottom-line">Bottom line</a><a href="#method">Method</a><a href="#results">Results</a>
    <a href="#years">Year by year</a><a href="#time">Time of day</a><a href="#validation">Validation</a>
    <a href="#adjusted">Bias-adjusted</a><a href="#quality">Data quality</a><a href="#caveats">Caveats</a>
  </nav>
</header>

<section id="bottom-line">
<h2>Bottom line</h2>
<div class="tiles">
  <div class="tile"><div class="v">+{d_mean.diff:.1f} kt</div><div class="l">HYC is windier than GTYC in September</div><div class="n">95% CI +{d_mean.lo:.1f} to +{d_mean.hi:.1f}</div></div>
  <div class="tile"><div class="v">{g["pct_5_20"]:.0f}% vs {hs["pct_5_20"]:.0f}%</div><div class="l">Racing hours in the 5–20 kt sweet spot, GTYC vs HYC (Sept)</div><div class="n">HRRR as retrieved, which reads low against the buoys</div></div>
  <div class="tile"><div class="v">{gd.loc[10]:.1f} → {gd.loc[17]:.1f} kt</div><div class="l">GTYC mean wind, 10 AM → 5 PM</div><div class="n">A strong afternoon thermal build</div></div>
  <div class="tile"><div class="v">1.3–1.7 kt</div><div class="l">How low HRRR runs against the buoys</div><div class="n">Racing hours, height-adjusted</div></div>
</div>
<ol class="find">
  <li><b>HYC is the windier venue in September, and that holds up.</b> After accounting for year-to-year variability, HYC averages {d_mean.diff:+.1f} kt more than GTYC (CI {d_mean.lo:+.1f} to {d_mean.hi:+.1f}) and has {d_sw.diff:.1f} points more of its racing hours in the 5–20 kt sweet spot (CI {d_sw.lo:+.1f} to {d_sw.hi:+.1f}).</li>
  <li><b>The gap comes from light air.</b> {g["pct_lt5"]:.0f}% of GTYC racing hours are below 5 kt against {hs["pct_lt5"]:.0f}% at HYC. Neither venue has meaningful time at 20 kt or more in HRRR.</li>
  <li><b>GTYC is an afternoon-thermal venue.</b> A 10 AM start catches the lightest part of the day, so later starts should help (see <a href="#time">time of day</a>).</li>
  <li><b>HYC’s mid-June window looks like September</b> ({hj['mean']:.1f} vs {hs['mean']:.1f} kt mean) but builds more through the afternoon.</li>
  <li><b>HRRR reads low against the buoys,</b> so treat the raw numbers as a lower bound on wind. The venue ranking is the same either way; the absolute levels are not (see <a href="#adjusted">bias-adjusted range</a>).</li>
  <li><b>Year-to-year variability dominates.</b> September yearly means range 4.6–9.2 kt at GTYC and 5.0–12.3 kt at HYC.</li>
</ol>
</section>

<section id="method">
<h2>Method</h2>
<p class="lede">Wind comes from NOAA’s HRRR model (3 km analysis, 10 m wind), averaged over the <b>water cells only</b> in a ±4 nm box around a sample point offshore of each club. Statistics use racing hours 14–20 UTC (10 AM–4 PM EDT) over 2015–2025.</p>
{table(["Earlier study had…", "This report…"], [
 ["Land cells in the averaging box", "Averages only HRRR water cells (for HYC, 6 of 25 cells in the old default box were land)"],
 ["One unvalidated sample point", "Sensitivity grid over offshore distance, box radius and bearing (see <a href='#results'>results</a>)"],
 ["No check against observations", "Validation against two NDBC buoys, plus a bias-adjusted range"],
 ["Sample counts that did not reconcile", "Expected vs retrieved hours tracked per year, missing hours listed"],
 ["Hourly samples treated as independent", "Confidence intervals resample whole <i>years</i> (2,000 draws); paired comparison uses per-day differences"],
 ["One 7-day window", "Core week and a ±3-day buffer window"],
 ["Code defects (longitude mask precedence)", "Fixed in v1.2, with unit tests"]], "text")}
{table(["Venue", "Club position (satellite-confirmed)", "Sample point (chosen from the map)", "Location", "Water cells in ±4 nm box"], [
 ["GTYC", "44.7803 N, 85.6385 W", "Bearing 20°, 3 nm offshore (racing circle roughly midway to Power Island)", "44.8273 N, 85.6144 W", "11"],
 ["HYC", "43.9448 N, 83.2786 W", "Bearing 330°, 2 nm offshore", "43.9737 N, 83.3018 W", "19"]], "text")}
<p class="small"><b>Correction, 20 Oct 2026:</b> the first run measured GTYC’s bearing and distance from a club position that was about 1.9 nm too far south. The sample point moved north by the same amount and every GTYC figure was recomputed from the same cached data. HYC’s position was already correct (within 10 m). Conclusions are unchanged; GTYC’s mean rose 0.1 kt (6.3 to 6.4).</p>
<p><b>Speed bins:</b> &lt; 5 kt light, 5–20 kt sweet spot, ≥ 20 kt heavy. <b>Usable day:</b> at least 3 consecutive racing hours in 5–20 kt.</p>
</section>

<section id="results">
<h2>Results: HRRR as retrieved</h2>
<p class="lede">Core windows, racing hours. Intervals in brackets are 95% year-resampling confidence intervals.</p>
{results_table()}
<p>Wind direction is highly variable at both venues (steadiness R about 0.1–0.2). North is the most common quadrant in every window (37–40% of racing hours); HYC in September shows more westerly flow (29%).</p>

{figs_summary}

<h3>How far apart are the venues? (September, paired by day)</h3>
{paired_table()}

<h3>Is the answer sensitive to the window or the sample point?</h3>
<p>Widening to ±3 days changes nothing material:</p>
{buffer_table()}
<p>Moving the sample point across a grid of offshore distances (1–6 nm) and box radii (2–6 nm) on the primary bearing moves the numbers far less than year-to-year variability does. The exception is HYC’s light-air share in September, which creeps up with larger boxes (about 23% below 5 kt at a 2 nm radius to 27% at 6 nm).</p>
{band_table()}
</section>

<section id="years">
<h2>Year by year</h2>
<p class="lede">Eleven seasons give useful but wide intervals. Hover the chart for each year’s values.</p>
<div class="fig">{chart_per_year()}
<p class="cap"><b>Mean racing-hour wind by year.</b> HYC is windier than GTYC in September in 9 of 11 years; GTYC edges ahead by 0.2–0.3 kt in 2016 and 2025. Yearly means span about 4.5 kt at GTYC and 7 kt at HYC.</p></div>
<details><summary>Table view (mean kt and share of hours at 20 kt or more)</summary>{peryear_table()}</details>
</section>

<section id="time">
<h2>Time of day</h2>
<div class="fig">{img("diurnal.png", "Diurnal mean wind for GTYC September, HYC September and HYC June")}
<p class="cap"><b>Mean wind by local hour</b> (all 24 hours; grey band is the 10 AM–4 PM racing window). GTYC runs about 5 kt overnight and peaks near 5 PM; HYC in September is nearly flat; HYC in June builds through the afternoon.</p></div>
{diurnal_table()}
<div class="callout"><p><b>Scheduling implication.</b> At GTYC the racing window straddles the ramp-up: the first hour averages {gd.loc[10]:.1f} kt and the last {gd.loc[16]:.1f} kt. Later first-gun times would likely improve GTYC’s light-air exposure. This report did not test other start times; the cached hourly data can.</p></div>
</section>

<section id="validation">
<h2>Validation against buoys</h2>
<p class="lede">HRRR was compared with the nearest on-water buoys for the same hours.</p>
{table(["", "GTYC", "HYC"], [
 ["Buoy", "NDBC 45020, Grand Traverse Bay South (44.789 N, 85.604 W)", "NDBC 45163, Saginaw Bay (43.983 N, 83.600 W)"],
 ["Distance from sample point", "about 2.3 nm (south of the racing area, same bay)", "about 14 nm (mid-bay, WSW)"],
 ["Data used", "2016–2018, Aug 1–Oct 9 (provided; buoy decommissioned after 2018)", "2015–2025 inside the Sept and June windows"],
 ["Anemometer height", "2.4 m", "2.3 m"]], "text")}
<p>Buoy winds are scaled to 10 m with a neutral log profile (about ×1.15). Raw and power-law (×1.23) versions are shown because this adjustment is the largest single uncertainty. Bias is HRRR minus buoy, in knots (negative = HRRR is lower); RMSE is in knots; “Same bin” is how often HRRR and the buoy fall in the same speed bin (&lt;5, 5–20, ≥20 kt).</p>
{val1}
{val2}
<div class="fig">{img("validation_scatter.png", "Scatter of HRRR wind against buoy wind for GTYC and HYC racing hours")}
<p class="cap"><b>HRRR vs buoy, racing hours.</b> Dashed line is 1:1. HYC clusters close to the line; GTYC sits below it, and HRRR rarely produces the strong-wind events the buoy records.</p></div>
<div class="callout"><p><b>Reading.</b> HRRR gets the <i>timing</i> of wind changes right (HYC especially) but runs low, over-represents light air, and almost never produces heavy air. Directions are rotated by 10–15° on average. GTYC’s weaker correlation is consistent with a narrow bay that a 3 km grid represents with only a few water cells.</p></div>
</section>

<section id="adjusted">
<h2>Bias-adjusted range</h2>
<p class="lede">HRRR was quantile-mapped to the height-adjusted buoy winds (fitted per season on matched racing-hour pairs) and applied to the venue series. This is an adjustment, not a measurement: the truth likely lies between the raw and adjusted versions.</p>
<div class="fig">{chart_mix()}
<p class="cap"><b>Share of racing hours by wind-speed bin.</b> The ranking of venues does not change, but the adjusted figures shift hours out of light air and into the 5–20 kt range.</p></div>
{adjusted_table()}
<h3>How much to trust the adjustment</h3>
<ul>
<li><b>GTYC (moderate confidence).</b> The buoy is about 2 nm south of the sample point, in the same bay. The adjusted mean stayed between 8.0 and 8.35 kt across five fitting choices (quantile mapping on Sept only, Aug–Oct, or Sept+Oct, and two linear scalings). A cross-check fitted on one year and tested on the others predicted 8.28 vs an observed 8.39 kt (fit 2016) and 9.29 vs 8.65 kt (fit 2018). The figures above use the Sept-only fit.</li>
<li><b>HYC (treat as an upper bound).</b> The buoy is 14 nm from the sample point in open bay, so the adjustment may overstate wind near the Caseville shore, particularly heavy air.</li>
<li>The adjusted HYC–GTYC gap is about 1.7–2.0 kt, so the ranking is unchanged.</li>
</ul>
</section>

<section id="quality">
<h2>Data quality</h2>
{q1}
<p>All missing hours fall in 2015–2018; 2019–2025 are complete. The gaps are archive gaps (checked against AWS, Google and Azure). 2016 is the weakest year, with 24% of September hours absent.</p>
{q2}
<div class="callout warn"><p><b>Corrections to the earlier nine-venue proposal.</b> Tawas Bay’s 17.3 kt maximum is <i>not</i> the lowest of the nine venues (Grand Traverse’s 16.4 kt is lower). The cause of the 476-observation HYC count was never identified; the stated explanation (six missing 2015 files) does not account for it. The same window now returns 523 racing hours for HYC, with all 16 missing hours in 2015–2018.</p></div>
</section>

<section id="caveats">
<h2>Caveats</h2>
<ul>
<li>HRRR is a 3 km model analysis, not an observation. It is low-biased against the buoys and handles narrow water poorly: GTYC’s West Arm is only 1–2 grid cells wide.</li>
<li>Buoy wind at 2.3–2.4 m must be scaled to 10 m. The result is sensitive to the method, and atmospheric stability is not modeled.</li>
<li>The GTYC buoy record is only 2016–2018, and the HYC buoy is 14 nm from the sample point.</li>
<li>Eleven seasons, one calendar week per year. Intervals are wide, and year-to-year differences are large (HYC’s September mean ranged from 5.0 to 12.3 kt).</li>
<li>Race-course layout, shoreline effects inside the bay, safety, logistics and fleet preferences are not captured.</li>
</ul>
</section>

<footer>
Generated from the analysis outputs in <code>studies/gtyc_hyc_2028/outputs/</code> by <code>studies/gtyc_hyc_2028/build_report.py</code>.
Code: <code>hrrr_wind</code> package. Data: NOAA HRRR via Herbie (AWS); NDBC stations 45020 and 45163.
</footer>
</div>
<div id="tip" role="tooltip"></div>
<script>{JS}</script>
</body></html>"""
    REPORT.write_text(html_doc, encoding="utf-8")
    print(f"wrote {REPORT} ({REPORT.stat().st_size / 1e6:.2f} MB)")

    # Artifact variant: the publish skeleton supplies doctype/html/head/body, so emit only
    # the meta + title + style + body content.
    import re
    style = re.search(r"<style>.*?</style>", html_doc, re.S).group(0)
    body = re.search(r"<body>(.*)</body>", html_doc, re.S).group(1)
    fragment = ('<meta name="claude:viewport-fit-sides" content="cover">\n'
                '<title>Venue Wind Report</title>\n' + style + "\n" + body)
    ARTIFACT.write_text(fragment, encoding="utf-8")
    print(f"wrote {ARTIFACT} ({ARTIFACT.stat().st_size / 1e6:.2f} MB)")


if __name__ == "__main__":
    build()
