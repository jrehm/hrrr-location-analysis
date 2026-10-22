import { useEffect, useRef, useState } from "preact/hooks";
import { api, post } from "./api.js";
import { html, Table } from "./components.js";
import { label } from "./util.js";

const FILES_PER_SECOND = 1.9;     // observed download rate; for the estimate only
const MMDD = /^(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])$/;
const days = (a, b) => Math.round((Date.parse(`2001-${b}`) - Date.parse(`2001-${a}`)) / 864e5) + 1;
const plural = (n, w) => `${n} ${w}${n === 1 ? "" : "s"}`;
const fmtTime = (s) => (s < 90 ? `${Math.round(s)} s` : `${(s / 60).toFixed(1)} min`);

function JobRow({ job, onCancel }) {
  const [log, setLog] = useState(null);
  const active = job.status === "running" || job.status === "queued";
  const elapsed = (job.finished || Date.now() / 1000) - (job.started || job.created);
  const what = job.kind === "cache"
    ? `Download ${job.params.venues.join(", ")} ${job.params.start} to ${job.params.end}, ${plural(job.params.years.length, "year")} (${job.params.tag})`
    : job.kind === "analyze" ? "Recompute analysis" : "Recompute validation";
  const toggleLog = async () => setLog(log === null ? (await api(`jobs/${job.id}/log`, { lines: 80 })).log : null);
  return html`<div class="card" style="padding:12px">
    <div class="row" style="justify-content:space-between;flex-wrap:wrap">
      <b>${what}</b>
      <span class="badge">${job.status}${active ? ` · ${fmtTime(elapsed)}` : ""}</span></div>
    <div class="bar" style="height:10px"><i style=${{ width: (job.progress * 100) + "%", background: job.status === "failed" ? "var(--warn)" : "var(--accent)" }}></i></div>
    <div class="small muted" style="margin-top:6px">${Math.round(job.progress * 100)}% ${job.message}</div>
    <div class="row" style="margin-top:8px">
      ${active && html`<button onClick=${() => onCancel(job.id)}>Cancel</button>`}
      <button onClick=${toggleLog}>${log === null ? "Show log" : "Hide log"}</button></div>
    ${log !== null && html`<pre class="small" style="overflow:auto;max-height:240px;background:var(--wash);padding:8px;border-radius:6px">${log}</pre>`}
  </div>`;
}

export function JobsPage({ meta, onChanged }) {
  const thisYear = new Date().getFullYear();
  const [f, setF] = useState({ venues: meta.venues.map((v) => v.key), y0: 2015, y1: thisYear - 1, start: "09-08", end: "09-14",
    tag: "", start_hour: 0, end_hour: 23, max_rss_gb: 4 });
  const [jobs, setJobs] = useState([]), [err, setErr] = useState(null);
  const seen = useRef({});
  const set = (k) => (e) => setF({ ...f, [k]: e.target.type === "number" ? Number(e.target.value) : e.target.value });
  const toggleVenue = (k) => setF({ ...f, venues: f.venues.includes(k) ? f.venues.filter((x) => x !== k) : [...f.venues, k] });

  const refresh = async () => {
    const js = await api(`studies/${meta.id}/jobs`);
    js.forEach((j) => { // a job that just finished may have changed results or caches
      if (seen.current[j.id] && seen.current[j.id] !== j.status && j.status === "done") onChanged();
      seen.current[j.id] = j.status;
    });
    setJobs(js);
  };
  useEffect(() => { refresh(); }, []);
  const busy = jobs.some((j) => j.status === "running" || j.status === "queued");
  useEffect(() => { if (!busy) return; const t = setInterval(refresh, 1500); return () => clearInterval(t); }, [busy]);

  const years = Array.from({ length: Math.max(0, f.y1 - f.y0 + 1) }, (_, i) => f.y0 + i);
  const okDates = MMDD.test(f.start) && MMDD.test(f.end) && days(f.start, f.end) >= 1;
  const nDays = okDates ? days(f.start, f.end) : 0;
  const files = years.length * nDays * (f.end_hour - f.start_hour + 1);
  const start = async (kind, params) => {
    setErr(null);
    try { await post(`studies/${meta.id}/jobs`, { kind, params }); await refresh(); } catch (e) { setErr(e.message); }
  };
  const cancel = async (id) => { await post(`jobs/${id}/cancel`); await refresh(); };
  const tagOk = /^[A-Za-z0-9_]{1,40}$/.test(f.tag);

  return html`<div class="grid">
    <div class="grid g2">
      <div class="card controls"><h2>Download wind data</h2>
        <p class="small muted">Fetches hourly HRRR 10 m wind for a calendar window repeated over several years, in a separate process with a memory cap. A cancelled or interrupted download resumes from per-year checkpoints when you start it again with the same tag. Existing caches are never overwritten.</p>
        <div>${meta.venues.map((v) => html`<label class="small" style="margin-right:14px"><input type="checkbox" checked=${f.venues.includes(v.key)} onChange=${() => toggleVenue(v.key)} /> ${v.name}</label>`)}</div>
        <div class="row"><label class="f" style="flex:1">First year<input type="number" min="2015" max=${thisYear} value=${f.y0} onInput=${set("y0")} /></label>
          <label class="f" style="flex:1">Last year<input type="number" min="2015" max=${thisYear} value=${f.y1} onInput=${set("y1")} /></label></div>
        <div class="row"><label class="f" style="flex:1">Window start (MM-DD)<input type="text" value=${f.start} onInput=${set("start")} placeholder="09-05" /></label>
          <label class="f" style="flex:1">Window end (MM-DD)<input type="text" value=${f.end} onInput=${set("end")} placeholder="09-17" /></label></div>
        <div class="row"><label class="f" style="flex:1">First hour (UTC)<input type="number" min="0" max="23" value=${f.start_hour} onInput=${set("start_hour")} /></label>
          <label class="f" style="flex:1">Last hour (UTC)<input type="number" min="0" max="23" value=${f.end_hour} onInput=${set("end_hour")} /></label>
          <label class="f" style="flex:1">Memory cap<select value=${f.max_rss_gb} onChange=${(e) => setF({ ...f, max_rss_gb: Number(e.target.value) })}>
            ${[2, 4, 6, 8].map((g) => html`<option value=${g}>${g} GB</option>`)}</select></label></div>
        <label class="f">Tag for this download (letters, digits, underscore)<input type="text" value=${f.tag} onInput=${set("tag")} placeholder="sep_2015_2025" /></label>
        <p class="small ${okDates ? "muted" : "err"}">${okDates ? `${plural(years.length, "year")} × ${plural(nDays, "day")} × ${f.end_hour - f.start_hour + 1} h = ${files.toLocaleString()} hourly files, roughly ${fmtTime(files / FILES_PER_SECOND)}` : "Window must be valid MM-DD dates, start before end."}</p>
        <button disabled=${busy || !okDates || !tagOk || !f.venues.length || !years.length}
          onClick=${() => start("cache", { venues: f.venues, years, start: f.start, end: f.end, tag: f.tag, start_hour: f.start_hour, end_hour: f.end_hour, max_rss_gb: f.max_rss_gb })}>
          ${busy ? "A job is running…" : "Start download"}</button>
      </div>
      <div class="grid" style="align-content:start">
        <div class="card controls"><h2>Recompute results</h2>
          <p class="small muted">Rerun the statistics from the wind caches already on disk. Use after changing the study's sample points or windows. Results pages refresh when a job finishes.</p>
          <div class="row"><button disabled=${busy} onClick=${() => start("analyze")}>Recompute analysis (about 3 min)</button>
            <button disabled=${busy} onClick=${() => start("validate")}>Recompute validation (about 1 min)</button></div></div>
        <div class="card"><h2>Wind caches on disk</h2>
          <${Table} cols=${[{ head: "Venue", left: true, cell: (c) => c.venue.toUpperCase() }, { head: "Tag", left: true, cell: (c) => c.tag }, { head: "Size", cell: (c) => `${c.mb} MB` }]} rows=${meta.caches} /></div>
      </div>
    </div>
    ${err && html`<p class="err">${err}</p>`}
    <div class="grid"><h2 style="margin:0">Jobs</h2>${jobs.length ? jobs.map((j) => html`<${JobRow} job=${j} onCancel=${cancel} />`) : html`<p class="muted small">No jobs yet in this session.</p>`}</div>
  </div>`;
}
