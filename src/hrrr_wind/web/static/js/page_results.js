import { useEffect, useState } from "preact/hooks";
import { api } from "./api.js";
import { html, InfoPopup, Rose, Table, ChartCanvas, chartDefaults, binColors } from "./components.js";
import { cssVar, dates, fmt, label, pct, range, seriesColor, seriesPoint, short } from "./util.js";
import { ComparePage } from "./page_compare.js";

export function useStudyData(meta, version = 0) {
  const [d, setD] = useState(null), [err, setErr] = useState(null);
  useEffect(() => {
    if (!meta) return;
    const id = meta.id;
    Promise.all([
      api(`studies/${id}/results`), api(`studies/${id}/diurnal`),
      ...meta.windows.map((w) => api(`studies/${id}/windrose`, { venue: w.venue, season: w.season })),
    ]).then(([results, diurnal, ...roses]) => setD({ results, diurnal, roses })).catch((e) => setErr(e.message));
  }, [meta?.id, version]);
  return { d, err };
}

export function ResultsPage({ meta, data }) {
  const { results: R, diurnal, roses } = data;
  if (!R.summary.length) {
    const st = meta.status.state, haveData = st !== "no_data";
    return html`<div class="card"><h2>No results yet</h2>
      <ol class="steps"><li class="done">Study created</li>
        <li class=${haveData ? "done" : ""}>Download the wind data${haveData ? "" : " (use the button above)"}</li>
        <li class=${st === "no_results" || haveData ? "" : ""}>Analyze it, then results appear here</li></ol>
      ${meta.readonly && html`<p class="muted small">This server is read-only, so it cannot download data.</p>`}</div>`;
  }
  const core = (w) => R.summary.find((r) => r.venue === w.venue && r.season === w.season && r.scope === "core");
  const years = meta.years;
  // Spread of the yearly race-week means (sample SD, kt): how much the average wind changes from one year to the next.
  const yearSpread = (w) => {
    const m = R.per_year.filter((r) => r.venue === w.venue && r.season === w.season && r.mean != null).map((r) => r.mean);
    if (m.length < 3) return null;
    const avg = m.reduce((a, b) => a + b, 0) / m.length;
    return { sd: Math.sqrt(m.reduce((a, b) => a + (b - avg) ** 2, 0) / (m.length - 1)), lo: Math.min(...m), hi: Math.max(...m), n: m.length };
  };
  const lineCfg = {
    type: "line",
    data: { labels: years, datasets: meta.windows.map((w, i) => ({
      label: label(w.venue, w.season), borderColor: seriesColor(i), backgroundColor: seriesColor(i), pointStyle: seriesPoint(i),
      tension: 0.15, pointRadius: 4, borderWidth: 2,
      data: years.map((y) => R.per_year.find((r) => r.venue === w.venue && r.season === w.season && r.year === y)?.mean ?? null) })) },
    options: { ...chartDefaults(), plugins: { ...chartDefaults().plugins, tooltip: { callbacks: { label: (c) => `${c.dataset.label}: ${fmt(c.parsed.y)} kt` } } },
      scales: { ...chartDefaults().scales, y: { ...chartDefaults().scales.y, title: { display: true, text: "Mean wind (kt)", color: chartDefaults().plugins.legend.labels.color } } } },
  };
  const hours = [...Array(24).keys()];
  // Grays out the hours outside the racing window (the same local hours at every venue).
  const [raceA, raceB] = [meta.race_utc[0] + meta.utc_offset, meta.race_utc[1] + meta.utc_offset];
  const shade = { id: "offHours", beforeDatasetsDraw(chart) {
    const { ctx, chartArea: a, scales: { x } } = chart, xa = x.getPixelForValue(raceA), xb = x.getPixelForValue(raceB);
    ctx.save(); ctx.globalAlpha = 0.16; ctx.fillStyle = cssVar("--muted");
    if (xa > a.left) ctx.fillRect(a.left, a.top, xa - a.left, a.bottom - a.top);
    if (xb < a.right) ctx.fillRect(xb, a.top, a.right - xb, a.bottom - a.top);
    ctx.restore();
  } };
  const dCfg = {
    type: "line", plugins: [shade],
    data: { labels: hours, datasets: meta.windows.map((w, i) => {
      const s = diurnal.find((x) => x.venue === w.venue && x.season === w.season) || { hours: [], mean_kt: [] };
      return { label: label(w.venue, w.season), borderColor: seriesColor(i), backgroundColor: seriesColor(i), pointStyle: seriesPoint(i), tension: 0.2, pointRadius: 3, borderWidth: 2,
        data: hours.map((h) => { const k = s.hours.indexOf(h); return k < 0 ? null : s.mean_kt[k]; }) }; }) },
    options: { ...chartDefaults(), scales: { ...chartDefaults().scales,
      x: { ...chartDefaults().scales.x, title: { display: true, text: "Venue Local Time", color: chartDefaults().plugins.legend.labels.color } } } },
  };
  const colors = binColors();
  // Share of racing hours below 5, 5-10, 10-20 and 20+ kt, from the rose's speed bins (0-5, 5-10, 10-15, 15-20, 20+).
  const speeds = (r) => [r.distribution[0], r.distribution[1], r.distribution[2] + r.distribution[3], r.distribution[4]];
  return html`<div class="grid">
    <div class="row small muted" style="gap:8px;align-items:center">Racing-hour wind for each window <${InfoPopup} title="What these numbers mean">
      <dl>
        <dt>Mean (range)</dt><dd>Average wind speed over the racing hours of the race dates, all years pooled. The range in brackets is a 95% confidence interval, found by resampling whole years, so it reflects how much the answer depends on which years happened.</dd>
        <dt>Year to year</dt><dd>How much the yearly average moves: the standard deviation of the yearly race-week means. A small value means most years look alike; a large one means the week can be much windier or lighter than typical. Hover for the range of the yearly means. It needs at least three years.</dd>
        <dt>Usable days</dt><dd>Share of race days with at least 3 consecutive racing hours at 5 to 20 knots. Days with a missing hour are left out.</dd>
        <dt>Speed bar</dt><dd>Share of racing hours ${"<"} 5 kt (blue), 5 to 10 kt (light green), 10 to 20 kt (dark green) and 20 kt or more (orange).</dd>
        <dt>Wind rose</dt><dd>Share of hours by the direction the wind blows from, split by speed (colours as in the legend). Each rose is scaled to its own largest direction, so compare shapes between venues and use the numbers above for strength. The rings are labelled in percent.</dd>
      </dl>
      <p>Winds are HRRR model values at the sample point, which tend to run lower than buoys (see the Validation tab).</p><//></div>
    <div class="grid g3">${meta.windows.map((w, i) => { const c = core(w); if (!c || roses[i].no_data) return html`<div class="card"><h2>${short(w.venue)} <span class="small muted">${dates(w.core)}</span></h2><p class="muted small">No data for this window yet.</p></div>`; const ys = yearSpread(w); return html`<div class="card">
      <h2>${short(w.venue)} <span class="small muted">${dates(w.core)}</span></h2>
      <div class="stat"><div><b>${fmt(c.mean)} kt</b><span class="small muted">mean (${range(c.mean_lo, c.mean_hi)})</span></div>
        ${ys && html`<div title=${`Standard deviation of the ${ys.n} yearly means, which range from ${fmt(ys.lo)} to ${fmt(ys.hi)} kt`}><b>± ${fmt(ys.sd)} kt</b><span class="small muted">year to year</span></div>`}
        <div><b>${pct(c.usable_day_pct)}</b><span class="small muted">usable days</span></div></div>
      <div class="bar">${speeds(roses[i]).map((v, k) => html`<i title=${pct(v)} style=${{ width: v + "%", background: [colors[0], colors[1], colors[3], colors[4]][k] }}></i>`)}</div>
      <div class="legend"><span>${"<"} 5 kt ${pct(speeds(roses[i])[0])}</span><span>5–10 ${pct(speeds(roses[i])[1])}</span><span>10–20 ${pct(speeds(roses[i])[2])}</span><span>≥ 20 kt ${pct(speeds(roses[i])[3], 1)}</span></div>
      <${Rose} data=${roses[i]} />
      <p class="small muted">${c.n} racing hours.</p>
    </div>`; })}</div>
    <div class="card"><h2>Year by year</h2><${ChartCanvas} config=${lineCfg} />
      <details><summary class="small muted">Table view</summary>
        <${Table} cols=${[{ head: "Year", cell: (r) => r.year }, ...meta.windows.map((w) => ({ head: label(w.venue, w.season),
          cell: (r) => { const x = R.per_year.find((p) => p.venue === w.venue && p.season === w.season && p.year === r.year);
            return x ? `${fmt(x.mean)} kt (${fmt(x.pct_ge20, 0)}% ≥20)` : "–"; } }))]}
          rows=${years.map((year) => ({ year }))} /></details></div>
    <div class="card"><h2>Time of day</h2><${ChartCanvas} config=${dCfg} />
      <p class="small muted" style="margin:6px 0 0">Gray: outside the racing hours (${meta.race_label}).</p></div>
    <h2 class="sect">Comparison</h2>
    <${ComparePage} meta=${meta} data=${data} />
  </div>`;
}
