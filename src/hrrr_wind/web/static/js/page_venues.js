import { useState } from "preact/hooks";
import { del, patch, post } from "./api.js";
import { Confirm, html } from "./components.js";
import { DateSelect, ZONES } from "./page_new.js";
import { MONTHS, dates, yearRanges } from "./util.js";
import { JobsPage } from "./page_jobs.js";
import { YearsEditor } from "./years.js";
import { TrashCard, TrashStudyCard } from "./page_trash.js";


// Which (venue, cache tag) pairs the running job is downloading right now.
function downloading(meta) {
  const job = meta.status.job;
  if (!job || meta.status.state !== "running") return new Set();
  const groups = job.kind === "run_study" ? job.params.downloads : job.kind === "cache" ? [{ tag: job.params.tag, venues: job.params.venues }] : [];
  return new Set(groups.flatMap((g) => g.venues.map((v) => `${v}|${g.tag}`)));
}

// What is on disk for one window: years, size, gaps and left-out years.
function DataCell({ w, busy }) {
  const c = w.cache;
  if (!c) return busy ? html`<span class="chip warn">downloading…</span>` : html`<span class="chip bad">not downloaded</span>`;
  return html`<span class="chip ok">${yearRanges(c.years)} · ${c.years.length} ${c.years.length === 1 ? "year" : "years"} · ${c.mb} MB</span>
    ${c.missing_years.length > 0 && html` <span class=${"chip " + (busy ? "warn" : "bad")}>${busy ? "downloading" : "missing"} ${yearRanges(c.missing_years)}</span>`}
    ${c.excluded_years.length > 0 && html` <span class="chip" title="On disk but not in the study">left out ${yearRanges(c.excluded_years)}</span>`}`;
}

function AddWindow({ meta, venue, onDone, onCancel }) {
  const [f, setF] = useState({ start: "06-14", end: "06-21" }), [err, setErr] = useState(null), [busy, setBusy] = useState(false);
  const submit = async () => {
    setBusy(true); setErr(null);
    try { await post(`studies/${meta.id}/windows`, { venue: venue.key, core: [f.start, f.end] }); await onDone(`Added the ${dates([f.start, f.end])} window to ${venue.name}.`); }
    catch (e) { setErr(e.message); setBusy(false); }
  };
  return html`<div class="card controls" style="margin-top:12px;background:var(--wash)"><b>Add a window to ${venue.name}</b>
    <div class="row" style="align-items:end;flex-wrap:wrap">
      <label class="f">From<${DateSelect} value=${f.start} onChange=${(v) => setF({ ...f, start: v })} /></label>
      <label class="f">To<${DateSelect} value=${f.end} onChange=${(v) => setF({ ...f, end: v })} /></label></div>
    <p class="small muted">The dates raced each year; 3 days either side are downloaded for context. Years follow the study (${yearRanges(meta.years)}).</p>
    ${err && html`<p class="err small">${err}</p>`}
    <div class="row"><button class="primary" disabled=${busy} onClick=${submit}>Add window</button><button onClick=${onCancel}>Cancel</button></div></div>`;
}

// Rename a venue: the long name (titles) and the short label (tables, charts). The id used in file names never changes.
function RenameVenue({ meta, venue, onDone, onCancel }) {
  const [f, setF] = useState({ name: venue.name, short: venue.short, zone: venue.tz_abbr }), [err, setErr] = useState(null), [busy, setBusy] = useState(false);
  const zones = ZONES.some(([n]) => n === venue.tz_abbr) ? ZONES : [[venue.tz_abbr, venue.utc_offset], ...ZONES];
  const ok = f.name.trim() && f.short.trim() && (f.name.trim() !== venue.name || f.short.trim() !== venue.short || f.zone !== venue.tz_abbr);
  const submit = async () => {
    setBusy(true); setErr(null);
    try { await patch(`studies/${meta.id}/venues/${venue.key}`, { name: f.name.trim(), short: f.short.trim(), ...(f.zone !== venue.tz_abbr ? { tz_abbr: f.zone, utc_offset: zones.find(([n]) => n === f.zone)[1] } : {}) }); await onDone(`Renamed ${f.name.trim()}. Update the results to see it in the figures.`); }
    catch (e) { setErr(e.message); setBusy(false); }
  };
  return html`<div class="controls" style="margin:0 0 10px">
    <label class="f">Name<input type="text" maxlength="60" value=${f.name} onInput=${(e) => setF({ ...f, name: e.target.value })} /></label>
    <label class="f">Short label (up to 12 characters)<input type="text" maxlength="12" value=${f.short} onInput=${(e) => setF({ ...f, short: e.target.value })} /></label>
    <label class="f">Time zone (racing hours are local time)<select value=${f.zone} onChange=${(e) => setF({ ...f, zone: e.target.value })}>
      ${zones.map(([n, o]) => html`<option value=${n}>${n} (UTC${o})</option>`)}</select></label>
    <p class="small muted" style="margin:0">The short label appears in tables and charts. File names keep the id "${venue.key}".</p>
    ${err && html`<p class="err small">${err}</p>`}
    <div class="row"><button class="primary" disabled=${busy || !ok} onClick=${submit}>Save</button><button onClick=${onCancel}>Cancel</button></div></div>`;
}

export function VenuesPage({ meta, onChanged, onEdited, onStudies }) {
  const canEdit = !meta.readonly && !meta.locked;
  const busy = downloading(meta);
  const [renaming, setRenaming] = useState(null), [adding, setAdding] = useState(null), [ask, setAsk] = useState(null), [working, setWorking] = useState(false), [err, setErr] = useState(null);
  const run = async (fn, text) => {
    setWorking(true); setErr(null);
    try { await fn(); setAsk(null); await onEdited(text); } catch (e) { setErr(e.message); }
    setWorking(false);
  };
  return html`<div class="grid">
    <h2 class="sect">Years</h2>
    <${YearsEditor} meta=${meta} readOnly=${!canEdit}
      onSaved=${async () => { await onEdited("Years updated. See the bar above for what happens next."); }} />
    <h2 class="sect">Venues</h2>
    <div class="row" style="justify-content:space-between;flex-wrap:wrap">
      <p class="muted small" style="margin:0">${meta.locked ? "This is the locked reference study: it can be explored but not changed. Copy it to a new study to extend it." : "Venues are the places being compared. Each has one or more windows (the dates analysed every year). Nothing you remove here is deleted from disk."}</p>
      ${canEdit && html`<a href=${`#/s/${meta.id}/add`}><button>+ Add venue</button></a>`}</div>
    <div class="grid g2">${meta.venues.map((v) => html`<div class="card">
      ${renaming === v.key ? html`<${RenameVenue} meta=${meta} venue=${v} onCancel=${() => setRenaming(null)} onDone=${async (t) => { setRenaming(null); await onEdited(t); }} />`
        : html`<div class="row" style="justify-content:space-between;align-items:baseline"><h2>${v.name} <span class="small muted">(${v.short})</span></h2>
          ${canEdit && html`<button title="Change the name and short label" onClick=${() => setRenaming(v.key)}>Rename</button>`}</div>`}
      <p class="small muted" style="margin:0 0 10px">Club ${v.lat.toFixed(4)}, ${v.lon.toFixed(4)}<br />
        Sample point ${v.bearing}° from the club, ${v.offshore_nm} nm out, averaged over a ${v.radius_nm} nm half-width box</p>
      <div class="tablewrap"><table><thead><tr><th class="l">Race dates</th><th class="l">Wind data</th><th></th></tr></thead><tbody>
        ${meta.windows.filter((w) => w.venue === v.key).map((w) => html`<tr><td class="l">${dates(w.core)}</td>
          <td class="l" style="white-space:normal"><${DataCell} w=${w} busy=${busy.has(`${v.key}|${w.cache_tag}`) || (meta.status.state === "running" && !!w.cache?.missing_years.length)} /></td>
          <td>${canEdit && html`<button title="Remove this window from the study" onClick=${() => setAsk({ kind: "window", v, w })}>Remove</button>`}</td></tr>`)}
      </tbody></table></div>
      ${ask && ask.v.key === v.key && ask.kind === "window" && html`<${Confirm} busy=${working} err=${err} label="Remove window"
        text=${`Remove the ${dates(ask.w.core)} window from ${v.name}? Its comparison pairs go too. The downloaded data stays on disk and is reused if you add the window back.`}
        onNo=${() => setAsk(null)} onYes=${() => run(() => del(`studies/${meta.id}/windows/${v.key}/${ask.w.season}`), `Removed the ${dates(ask.w.core)} window.`)} />`}
      ${ask && ask.v.key === v.key && ask.kind === "venue" && html`<${Confirm} busy=${working} err=${err} label="Remove venue"
        text=${`Remove ${v.name} from the study? Its windows, any comparison with it and its buoy validation are removed from the study. The downloaded data stays on disk.`}
        onNo=${() => setAsk(null)} onYes=${() => run(() => del(`studies/${meta.id}/venues/${v.key}`), `Removed ${v.name}.`)} />`}
      ${adding === v.key && html`<${AddWindow} meta=${meta} venue=${v} onCancel=${() => setAdding(null)} onDone=${async (t) => { setAdding(null); await onEdited(t); }} />`}
      <div class="row" style="margin-top:12px;flex-wrap:wrap">
        <a href=${`#/s/${meta.id}/venue/${v.key}`}><button>${canEdit ? "Edit sample point" : "Explore sample point"}</button></a>
        ${canEdit && html`<button onClick=${() => setAdding(adding === v.key ? null : v.key)}>+ Add window</button>
          <button class="danger" onClick=${() => setAsk({ kind: "venue", v })}>Remove venue</button>`}</div>
    </div>`)}</div>
    ${!meta.readonly && html`<details class="adv"><summary>Advanced: manual download, recompute, wind caches on disk</summary>
      <${JobsPage} meta=${meta} onChanged=${onChanged} /></details>`}
    <${TrashStudyCard} meta=${meta} onTrashed=${() => onStudies(true)} />
    <${TrashCard} readonly=${meta.readonly} onChanged=${() => onStudies(false)} />
  </div>`;
}
