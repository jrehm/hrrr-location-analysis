import { useState } from "preact/hooks";
import { post } from "./api.js";
import { html } from "./components.js";
import { fmtMinutes, yearRanges } from "./util.js";

// "Years 2015–2025 (left out: 2020)" for the header
export function yearsSummary(meta) {
  const disk = new Set(meta.year_chips.filter((c) => c.on_disk > 0).map((c) => c.year));
  const left = [...disk].filter((y) => !meta.years.includes(y));
  return `${yearRanges(meta.years)}${left.length ? ` (left out: ${yearRanges(left)})` : ""}`;
}

const days = (w) => Math.round((Date.parse(`2001-${w.core[1]}`) - Date.parse(`2001-${w.core[0]}`)) / 864e5) + 1 + 6;   // core + 3-day buffers

/** Pick which years are in the study. Years already on disk are never re-downloaded or deleted. */
export function YearsEditor({ meta, onSaved, onClose }) {
  const [sel, setSel] = useState(new Set(meta.years)), [busy, setBusy] = useState(false), [err, setErr] = useState(null);
  const toggle = (y) => { const n = new Set(sel); n.has(y) ? n.delete(y) : n.add(y); setSel(n); };
  const chips = meta.year_chips, nWin = meta.windows.length;
  // hourly files each window would still need for the selected years
  const files = meta.windows.reduce((a, w) => a + [...sel].filter((y) => !(w.cache?.years || []).includes(y)).length * days(w) * 24, 0);
  const added = [...sel].filter((y) => chips.find((c) => c.year === y).on_disk < nWin).sort();
  const left = meta.years.filter((y) => !sel.has(y));
  const changed = [...sel].sort().join() !== [...meta.years].sort().join();
  const save = async () => {
    setBusy(true); setErr(null);
    try { const m = await post(`studies/${meta.id}/years`, { years: [...sel].sort() }); await onSaved(m); } catch (e) { setErr(e.message); setBusy(false); }
  };
  return html`<div class="card controls" style="margin-bottom:16px"><h2>Years in this study</h2>
    <p class="small muted">Click a year to add it or leave it out. Years already downloaded are kept on disk either way, so leaving one out is reversible and adding it back needs no download.</p>
    <div class="ychips">${chips.map((c) => { const inSel = sel.has(c.year), full = c.on_disk >= nWin, some = c.on_disk > 0;
      const cls = inSel ? (full ? "in full" : "in need") : some ? "out disk" : "out";
      const tip = inSel ? (full ? "in the study, downloaded" : some ? "in the study, partly downloaded" : "in the study, will be downloaded") : some ? "downloaded but left out" : "not in the study";
      return html`<button class=${"ychip " + cls} title=${tip} onClick=${() => toggle(c.year)}>${c.year}</button>`; })}</div>
    <div class="legend"><span><i style="background:var(--accent)"></i>in study, downloaded</span><span><i style="background:var(--warn)"></i>in study, to download</span>
      <span><i style="background:var(--line)"></i>downloaded, left out</span></div>
    ${added.length > 0 && html`<p class="small">To download: ${yearRanges(added)} (${files.toLocaleString()} hourly files, ${fmtMinutes(files / 1.9 / 60)}).</p>`}
    ${left.length > 0 && html`<p class="small">Leaving out ${yearRanges(left)}: kept on disk, not used in the results.</p>`}
    ${err && html`<p class="err">${err}</p>`}
    <div class="row"><button class="primary" disabled=${busy || !changed || !sel.size} onClick=${save}>Save years</button><button onClick=${onClose}>Cancel</button></div></div>`;
}
