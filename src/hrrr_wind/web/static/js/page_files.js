import { useEffect, useState } from "preact/hooks";
import { api, del } from "./api.js";
import { Confirm, html, Table } from "./components.js";
import { label, yearRanges } from "./util.js";

const fileUrl = (meta, kind, name) => `studies/${meta.id}/${kind}/${encodeURIComponent(name)}`;

// Cleanup of data nothing uses: each row asks for confirmation and says how much space it frees.
function Cleanup({ meta, onChanged }) {
  const canEdit = !meta.readonly && !meta.locked;
  const [ask, setAsk] = useState(null), [err, setErr] = useState(null), [busy, setBusy] = useState(false);
  const caches = meta.caches.filter((c) => !c.used_by), buoys = (meta.buoy_data || []).filter((b) => !b.used);
  const total = caches.reduce((a, c) => a + c.mb, 0) + buoys.reduce((a, b) => a + b.mb, 0);
  if (!caches.length && !buoys.length) return null;
  const rows = [...caches.map((c) => ({ key: c.file, kind: "caches", name: c.file, what: `wind cache ${c.file}`, mb: c.mb,
      why: c.in_study ? "no window or buoy uses it" : `venue ${c.venue.toUpperCase()} is no longer in the study` })),
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
        text=${`Permanently delete ${r.what}, freeing ${r.mb} MB? This cannot be undone.`} />`}</div>`)}</div>`;
}

export function FilesPage({ meta, data, onChanged }) {
  const [files, setFiles] = useState([]);
  useEffect(() => { api(`studies/${meta.id}/files`).then(setFiles); }, [meta.id]);
  return html`<div class="grid">
    <div class="card"><h2>Wind data on disk</h2>
      <p class="small muted">Hourly HRRR wind caches. Years in a file that are not in the study are kept but not used. A cache nothing uses (for example after removing a venue) is kept too; see Unused data below.</p>
      <${Table} cols=${[{ head: "Venue", left: true, cell: (c) => c.venue.toUpperCase() + (c.in_study ? "" : " (removed)") }, { head: "Years", left: true, cell: (c) => (c.years.length ? yearRanges(c.years) : "unreadable") },
        { head: "Size", cell: (c) => `${c.mb} MB` }, { head: "Used by", left: true, cell: (c) => c.used_by || "nothing (kept)" }]} rows=${meta.caches} /></div>
    <${Cleanup} meta=${meta} onChanged=${onChanged} />
    <div class="card"><h2>Downloads</h2><div class="files">
      ${files.map((f) => html`<a href=${`/api/studies/${meta.id}/files/${f}`} download>${f}</a>`)}</div></div>
    <div class="card"><h2>Data completeness</h2>
      <p class="small muted">Hours present against hours expected in the core windows. Gaps are archive gaps, concentrated in 2015–2018.</p>
      <${Table} cols=${[{ head: "Window", cell: (r) => label(r.venue, r.season) },
        { head: "Racing hours", cell: (r) => `${r.race_hours_present} / ${r.race_hours_expected}` },
        { head: "All 24 h", cell: (r) => `${r.hours_present_24h} / ${r.hours_expected_24h}` }]} rows=${data.results.quality} /></div>
  </div>`;
}
