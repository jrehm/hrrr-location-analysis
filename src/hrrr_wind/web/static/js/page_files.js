import { useEffect, useState } from "preact/hooks";
import { api } from "./api.js";
import { html, Table } from "./components.js";
import { label, yearRanges } from "./util.js";

export function FilesPage({ meta, data }) {
  const [files, setFiles] = useState([]);
  useEffect(() => { api(`studies/${meta.id}/files`).then(setFiles); }, [meta.id]);
  return html`<div class="grid">
    <div class="card"><h2>Wind data on disk</h2>
      <p class="small muted">Hourly HRRR wind caches. Years in a file that are not in the study are kept but not used. A cache no window uses (for example after removing a venue) is kept too.</p>
      <${Table} cols=${[{ head: "Venue", left: true, cell: (c) => c.venue.toUpperCase() }, { head: "Cache", left: true, cell: (c) => c.tag },
        { head: "Years", left: true, cell: (c) => (c.years.length ? yearRanges(c.years) : "unreadable") },
        { head: "Size", cell: (c) => `${c.mb} MB` }, { head: "Used by", left: true, cell: (c) => (c.used ? "a window" : "nothing (kept)") }]} rows=${meta.caches} /></div>
    <div class="card"><h2>Downloads</h2><div class="files">
      ${files.map((f) => html`<a href=${`/api/studies/${meta.id}/files/${f}`} download>${f}</a>`)}</div></div>
    <div class="card"><h2>Data completeness</h2>
      <p class="small muted">Hours present against hours expected in the core windows. Gaps are archive gaps, concentrated in 2015–2018.</p>
      <${Table} cols=${[{ head: "Window", cell: (r) => label(r.venue, r.season) },
        { head: "Racing hours", cell: (r) => `${r.race_hours_present} / ${r.race_hours_expected}` },
        { head: "All 24 h", cell: (r) => `${r.hours_present_24h} / ${r.hours_expected_24h}` }]} rows=${data.results.quality} /></div>
  </div>`;
}
