import { useEffect, useState } from "preact/hooks";
import { api, del } from "./api.js";
import { Confirm, html, Table } from "./components.js";
import { label, short, yearRanges } from "./util.js";

const fileUrl = (meta, kind, name) => `studies/${meta.id}/${kind}/${encodeURIComponent(name)}`;

// Cleanup of data nothing uses: each row asks for confirmation and says how much space it frees.
function Cleanup({ meta, onChanged }) {
  const canEdit = !meta.readonly && !meta.locked;
  const [ask, setAsk] = useState(null), [err, setErr] = useState(null), [busy, setBusy] = useState(false);
  const caches = meta.caches.filter((c) => !c.used_by), buoys = (meta.buoy_data || []).filter((b) => !b.used);
  const total = caches.reduce((a, c) => a + c.mb, 0) + buoys.reduce((a, b) => a + b.mb, 0);
  if (!caches.length && !buoys.length) return null;
  const rows = [...caches.map((c) => ({ key: c.file, kind: "caches", name: c.file, what: `wind cache ${c.file}`, mb: c.mb,
      why: c.in_study ? "no window or buoy uses it" : `venue ${short(c.venue)} is no longer in the study` })),
    ...buoys.map((b) => ({ key: "b" + b.dir, kind: "buoy-data", name: b.dir, what: `buoy data folder ${b.dir} (${b.files} files)`, mb: b.mb, why: "no buoy of this study uses it" }))];
  const remove = async (r) => {
    setBusy(true); setErr(null);
    try { await del(fileUrl(meta, r.kind, r.name)); setAsk(null); await onChanged(); } catch (e) { setErr(e.message); }
    setBusy(false);
  };
  return html`<div class="card"><h2>Unused data</h2>
    <p class="small muted">Data on disk that nothing in this study uses, about ${total.toFixed(1)} MB. Removing a venue, window or buoy keeps its files so they can be reused; delete them here to free space. A deleted cache must be downloaded again if you need it.</p>
    ${rows.map((r) => html`<div key=${r.key} style="padding:6px 0;border-top:1px solid var(--line)"><div class="row">
      <span class="grow"><b>${r.what}</b>, ${r.mb} MB <span class="muted small">(${r.why})</span></span>
      ${canEdit && ask !== r.key && html`<button onClick=${() => { setAsk(r.key); setErr(null); }}>Delete</button>`}</div>
      ${ask === r.key && html`<${Confirm} busy=${busy} err=${err} label="Delete permanently" onNo=${() => setAsk(null)} onYes=${() => remove(r)}
        text=${`Permanently delete ${r.what}, freeing ${r.mb} MB? This cannot be undone.`} />`}</div>`)}
    <p class="small" style="margin:8px 0 0;padding-top:6px;border-top:2px solid var(--line)"><b>Total: ${rows.length} item${rows.length === 1 ? "" : "s"}, ${total.toFixed(1)} MB</b></p></div>`;
}

export function FilesPage({ meta, data, onChanged }) {
  const [files, setFiles] = useState([]);
  const sum = (xs, f) => xs.reduce((a, x) => a + f(x), 0);
  const q = data.results.quality, mbOf = (x) => `${x.toFixed(1)} MB`;
  const pctOf = (a, b) => (b ? ` (${Math.round((100 * a) / b)}%)` : "");
  const hrs = (k) => sum(q, (r) => r[k]);
  useEffect(() => { api(`studies/${meta.id}/files`).then(setFiles); }, [meta.id]);
  return html`<div class="grid">
    <div class="card"><h2>Wind data on disk</h2>
      <p class="small muted">Hourly HRRR wind caches. Years in a file that are not in the study are kept but not used. A cache nothing uses (for example after removing a venue) is kept too; see Unused data below.</p>
      <${Table} cols=${[{ head: "Venue", left: true, cell: (c) => short(c.venue) + (c.in_study ? "" : " (removed)") }, { head: "Years", left: true, cell: (c) => (c.years.length ? yearRanges(c.years) : "unreadable") },
        { head: "Size", cell: (c) => `${c.mb.toFixed(1)} MB` }, { head: "Used by", left: true, cell: (c) => c.used_by || "nothing (kept)" }]} rows=${meta.caches}
        foot=${[`Total: ${meta.caches.length} file${meta.caches.length === 1 ? "" : "s"}`, "", mbOf(sum(meta.caches, (c) => c.mb)), ""]} /></div>
    <div class="card"><h2>Buoy data on disk</h2>
      <p class="small muted">NDBC observation files used for validation, one per year. Set up or change buoys on the Validation tab.</p>
      ${meta.buoys.length ? html`<${Table} cols=${[{ head: "Venue", left: true, cell: (b) => meta.venues.find((v) => v.key === b.venue)?.name || b.venue },
        { head: "Buoy", left: true, cell: (b) => html`<a href=${`https://www.ndbc.noaa.gov/station_page.php?station=${encodeURIComponent(b.id)}`} target="_blank" rel="noopener">${b.id}</a>` },
        { head: "Years", left: true, cell: (b) => (b.years.length ? yearRanges(b.years) : "none downloaded") },
        { head: "Files", cell: (b) => b.files }, { head: "Size", cell: (b) => `${b.mb.toFixed(2)} MB` }]} rows=${meta.buoys}
        foot=${[`Total: ${meta.buoys.length} buoy${meta.buoys.length === 1 ? "" : "s"}`, "", "", sum(meta.buoys, (b) => b.files), mbOf(sum(meta.buoys, (b) => b.mb))]} />`
        : html`<p class="muted">No buoys are set up for this study.</p>`}</div>
    <${Cleanup} meta=${meta} onChanged=${onChanged} />
    <div class="card"><h2>Downloads</h2><div class="files">
      ${files.map((f) => html`<a href=${`/api/studies/${meta.id}/files/${f.name}`} download title=${`${f.kb} kB`}>${f.name}</a>`)}</div>
      <p class="small muted" style="margin-bottom:0"><b>Total: ${files.length} files, ${mbOf(sum(files, (f) => f.kb) / 1e3)}</b></p></div>
    <div class="card"><h2>Data completeness</h2>
      <p class="small muted">Hours present against hours expected in the core windows. Gaps are archive gaps, concentrated in 2015–2018.</p>
      <${Table} cols=${[{ head: "Window", cell: (r) => label(r.venue, r.season) },
        { head: "Racing hours", cell: (r) => `${r.race_hours_present} / ${r.race_hours_expected}` },
        { head: "All 24 h", cell: (r) => `${r.hours_present_24h} / ${r.hours_expected_24h}` }]} rows=${q}
        foot=${["Total", `${hrs("race_hours_present")} / ${hrs("race_hours_expected")}${pctOf(hrs("race_hours_present"), hrs("race_hours_expected"))}`,
          `${hrs("hours_present_24h")} / ${hrs("hours_expected_24h")}${pctOf(hrs("hours_present_24h"), hrs("hours_expected_24h"))}`]} /></div>
  </div>`;
}
