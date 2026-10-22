import { useEffect, useState } from "preact/hooks";
import { api } from "./api.js";
import { html, Table } from "./components.js";
import { label } from "./util.js";

export function FilesPage({ meta, data }) {
  const [files, setFiles] = useState([]);
  useEffect(() => { api(`studies/${meta.id}/files`).then(setFiles); }, [meta.id]);
  return html`<div class="grid">
    <div class="card"><h2>Downloads</h2><div class="files">
      ${files.map((f) => html`<a href=${`/api/studies/${meta.id}/files/${f}`} download>${f}</a>`)}</div></div>
    <div class="card"><h2>Data completeness</h2>
      <p class="small muted">Hours present against hours expected in the core windows. Gaps are archive gaps, concentrated in 2015–2018.</p>
      <${Table} cols=${[{ head: "Window", cell: (r) => label(r.venue, r.season) },
        { head: "Racing hours", cell: (r) => `${r.race_hours_present} / ${r.race_hours_expected}` },
        { head: "All 24 h", cell: (r) => `${r.hours_present_24h} / ${r.hours_expected_24h}` }]} rows=${data.results.quality} /></div>
  </div>`;
}
