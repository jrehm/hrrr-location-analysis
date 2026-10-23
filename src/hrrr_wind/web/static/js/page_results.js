import { useEffect, useState } from "preact/hooks";
import { api } from "./api.js";
import { html, Rose, Table, ChartCanvas, chartDefaults, binColors } from "./components.js";
import { fmt, label, pct, range, seriesColor } from "./util.js";
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
  const lineCfg = {
    type: "line",
    data: { labels: years, datasets: meta.windows.map((w, i) => ({
      label: label(w.venue, w.season), borderColor: seriesColor(i), backgroundColor: seriesColor(i),
      tension: 0.15, pointRadius: 4, borderWidth: 2,
      data: years.map((y) => R.per_year.find((r) => r.venue === w.venue && r.season === w.season && r.year === y)?.mean ?? null) })) },
    options: { ...chartDefaults(), plugins: { ...chartDefaults().plugins, tooltip: { callbacks: { label: (c) => `${c.dataset.label}: ${fmt(c.parsed.y)} kt` } } },
      scales: { ...chartDefaults().scales, y: { ...chartDefaults().scales.y, title: { display: true, text: "Mean wind (kt)", color: chartDefaults().plugins.legend.labels.color } } } },
  };
  const hours = [...Array(24).keys()];
  const dCfg = {
    type: "line",
    data: { labels: hours, datasets: meta.windows.map((w, i) => {
      const s = diurnal.find((x) => x.venue === w.venue && x.season === w.season) || { hours: [], mean_kt: [] };
      return { label: label(w.venue, w.season), borderColor: seriesColor(i), backgroundColor: seriesColor(i), tension: 0.2, pointRadius: 3, borderWidth: 2,
        data: hours.map((h) => { const k = s.hours.indexOf(h); return k < 0 ? null : s.mean_kt[k]; }) }; }) },
    options: { ...chartDefaults(), scales: { ...chartDefaults().scales,
      x: { ...chartDefaults().scales.x, title: { display: true, text: `Local hour (${meta.tz_abbr}); racing ${meta.race_label}`, color: chartDefaults().plugins.legend.labels.color } } } },
  };
  const colors = binColors();
  const roseMax = Math.max(...roses.filter((r) => !r.no_data).flatMap((r) => r.sectors.map((_, k) => r.values.reduce((a, b) => a + b[k], 0))));
  return html`<div class="grid">
    <div class="grid g3">${meta.windows.map((w, i) => { const c = core(w); if (!c || roses[i].no_data) return html`<div class="card"><h2>${label(w.venue, w.season)}</h2><p class="muted small">No data for this window yet.</p></div>`; return html`<div class="card">
      <h2>${label(w.venue, w.season)} <span class="small muted">${w.core[0]} to ${w.core[1]}</span></h2>
      <div class="stat"><div><b>${fmt(c.mean)} kt</b><span class="small muted">mean (${range(c.mean_lo, c.mean_hi)})</span></div>
        <div><b>${pct(c.usable_day_pct)}</b><span class="small muted">usable days</span></div></div>
      <div class="bar">${[c.pct_lt5, c.pct_5_20, c.pct_ge20].map((v, k) => html`<i title=${pct(v)} style=${{ width: v + "%", background: [colors[0], colors[2], colors[4]][k] }}></i>`)}</div>
      <div class="legend"><span>${"<"} 5 kt ${pct(c.pct_lt5)}</span><span>5–20 kt ${pct(c.pct_5_20)}</span><span>≥ 20 kt ${pct(c.pct_ge20, 1)}</span></div>
      <${Rose} data=${roses[i]} maxPct=${roseMax} />
      <p class="small muted">${c.n} racing hours. Rose bars show % of hours by direction the wind blows from, on a common scale for all windows.</p>
    </div>`; })}</div>
    <div class="card"><h2>Year by year</h2><${ChartCanvas} config=${lineCfg} />
      <details><summary class="small muted">Table view</summary>
        <${Table} cols=${[{ head: "Year", cell: (r) => r.year }, ...meta.windows.map((w) => ({ head: label(w.venue, w.season),
          cell: (r) => { const x = R.per_year.find((p) => p.venue === w.venue && p.season === w.season && p.year === r.year);
            return x ? `${fmt(x.mean)} kt (${fmt(x.pct_ge20, 0)}% ≥20)` : "–"; } }))]}
          rows=${years.map((year) => ({ year }))} /></details></div>
    <div class="card"><h2>Time of day</h2><${ChartCanvas} config=${dCfg} /></div>
    <h2 class="sect">Comparison</h2>
    <${ComparePage} meta=${meta} data=${data} />
  </div>`;
}
