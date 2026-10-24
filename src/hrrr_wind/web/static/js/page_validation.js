import { useRef, useState } from "preact/hooks";
import { html, Table, binColors } from "./components.js";
import { fmt, label, pct } from "./util.js";
import { del } from "./api.js";
import { BuoySetup } from "./page_buoys.js";

const Mix = ({ r }) => { const c = binColors(); return html`<div class="bar" style="width:170px;margin:0"> ${[r.pct_lt5, r.pct_5_20, r.pct_ge20].map((v, i) =>
  html`<i title=${pct(v)} style=${{ width: v + "%", background: [c[0], c[2], c[4]][i] }}></i>`)}</div>`; };

const StationLink = ({ id }) => html`<a href=${`https://www.ndbc.noaa.gov/station_page.php?station=${encodeURIComponent(id)}`} target="_blank" rel="noopener" title="NDBC station page">${id}</a>`;

// (i) button plus a native <dialog>: Esc, the close button or a click outside dismisses it.
function Info({ title, children }) {
  const ref = useRef(null);
  return html`<button class="info" title=${title} aria-label=${title} onClick=${() => ref.current.showModal()}>i</button>
    <dialog ref=${ref} class="infobox" onClick=${(e) => e.target === ref.current && ref.current.close()}>
      <h2>${title}</h2>${children}
      <form method="dialog"><button class="primary">Close</button></form>
    </dialog>`;
}

const HowInfo = () => html`<${Info} title="How validation works">
  <p>HRRR is compared with each buoy at the <b>buoy's own location</b>, not at the venue. The club and sample-point coordinates are not used here.</p>
  <ul>
    <li>HRRR is sampled two ways, shown in the <i>HRRR sampling</i> column: the nearest water cell, and a 2 nm water box around the buoy.</li>
    <li>Buoy speeds are adjusted to 10 m height. Each observation is matched to the top of the hour within 10 minutes.</li>
    <li>HRRR comes from each buoy's own caches, which may cover more days than the climatology windows.</li>
  </ul>
  <p>The <b>bias-adjusted range</b> applies a quantile-map correction, fitted against the buoy, to HRRR at the venue sample points. This assumes the HRRR bias at the venue is similar to the bias at the buoy, which is weaker when the buoy is far from the venue.</p><//>`;

const SetupInfo = () => html`<${Info} title="Setting up validation">
  <ol>
    <li><b>Choose buoy</b> for a venue. The map and list show NDBC stations within 60 nm that report wind, with the years each one archived in this study's range. Stations with no archived years are greyed out.</li>
    <li><b>Check the anemometer height.</b> It is read from the station's NDBC page when you select the buoy (with a link to the page). If the page lists none, the field starts at a typical value for you to check. The height scales the buoy's winds to 10 m.</li>
    <li><b>Download and validate</b> starts a background job, safe to leave. It downloads the buoy's yearly observation files, skipping files already on disk and years NDBC has not archived (the current year is archived only after it ends).</li>
    <li>If the buoy lies <b>outside the venue's downloaded HRRR area</b>, the job also downloads HRRR centered on the buoy for the study's windows. The list shows the size and time before you commit. Otherwise the existing HRRR data is reused.</li>
    <li>The job then compares HRRR with the buoy and fills in the results below.</li>
  </ol>
  <p><b>Change buoy</b> replaces a venue's buoy and <b>Remove</b> stops validating it. Downloaded files stay on disk, so nothing is lost. A buoy far from the venue gives a weaker check, so treat the bias-adjusted range as an upper bound.</p><//>`;

// One row per venue: its buoy (change or remove it) or a way to choose one.
function BuoyList({ meta, onChanged }) {
  const [setup, setSetup] = useState(null), [err, setErr] = useState(null);
  const canEdit = !meta.readonly && !meta.locked;
  const remove = async (v) => { setErr(null); try { await del(`studies/${meta.id}/buoys/${v}`); onChanged(); } catch (e) { setErr(e.message); } };
  const yrs = (b) => b.years.length ? `data for ${b.years[0]}${b.years.length > 1 ? `–${b.years[b.years.length - 1]}` : ""}` : "no observations downloaded yet";
  return html`<div class="card"><h2>Buoys <${SetupInfo} /></h2>
    ${meta.buoys.length === 0 && html`<p class="small muted">Validation checks HRRR's winds against a nearby NDBC buoy's measurements. Choose a buoy for each venue you want checked; the search starts at 60 nm and can be widened.</p>`}
    ${err && html`<p class="err small">${err}</p>`}
    ${meta.venues.map((v) => { const b = meta.buoys.find((x) => x.venue === v.key);
      return html`<div key=${v.key} style="padding:6px 0;border-top:1px solid var(--line)"><div class="row">
        <span class="grow"><b>${v.name}</b>: ${b ? html`buoy <${StationLink} id=${b.id} />, ${yrs(b)}, anemometer ${b.anem_m} m` : html`<span class="muted">no validation buoy chosen, so HRRR has not been checked against observations for this venue</span>`}</span>
        ${canEdit && setup !== v.key && html`<button onClick=${() => setSetup(v.key)}>${b ? "Change buoy" : "Choose buoy"}</button>`}
        ${canEdit && b && html`<button onClick=${() => remove(v.key)}>Remove</button>`}</div>
        ${setup === v.key && html`<${BuoySetup} meta=${meta} venue=${v.key} onCancel=${() => setSetup(null)} onStarted=${() => { setSetup(null); onChanged(); }} />`}</div>`; })}</div>`;
}

export function ValidationPage({ meta, data, onChanged }) {
  const { validation, adjusted } = data.results;
  const [all, setAll] = useState(false);
  const rows = validation.filter((r) => all || (r.height_adj.startsWith("log") && r.subset.startsWith("racing") && r.hrrr_sampling === "2 nm water box"));
  const buoy = (v) => meta.buoys.find((b) => b.venue === v);
  if (!validation.length) return html`<div class="grid"><${BuoyList} meta=${meta} onChanged=${onChanged} />
    ${meta.buoys.length > 0 && html`<p class="muted">Validation results appear here once the buoy data has been downloaded and compared.</p>`}</div>`;
  return html`<div class="grid">
    <${BuoyList} meta=${meta} onChanged=${onChanged} />
    <div class="card"><h2>HRRR versus buoys <${HowInfo} /></h2>
      <p class="small muted">Bias is HRRR minus buoy (negative: HRRR reads low). Buoy winds are scaled from the anemometer height to 10 m with a neutral log profile.
        ${meta.buoys.map((b) => html` Buoy <${StationLink} id=${b.id} /> serves ${b.venue.toUpperCase()}.`)}</p>
      <${Table} cols=${[
        { head: "Venue", left: true, cell: (r) => html`${r.venue.toUpperCase()} (<${StationLink} id=${r.buoy} />)` },
        { head: "Buoy to sample point (nm)", cell: (r) => { const b = buoy(r.venue); return b ? fmt(b.sample_distance_nm) : "–"; } },
        ...(all ? [{ head: "HRRR sampling", left: true, cell: (r) => r.hrrr_sampling }, { head: "Height adj.", left: true, cell: (r) => r.height_adj }, { head: "Subset", left: true, cell: (r) => r.subset }] : []),
        { head: "Pairs", cell: (r) => r.n }, { head: "Bias (kt)", cell: (r) => fmt(r.bias_kt) },
        { head: "RMSE (kt)", cell: (r) => fmt(r.rmse_kt) }, { head: "Correlation", cell: (r) => fmt(r.corr_r, 2) },
        { head: "Same bin", cell: (r) => pct(r.same_category_pct) }, { head: "Dir. bias", cell: (r) => `${fmt(r.dir_bias_deg, 0)}°` }]} rows=${rows} />
      <p><button onClick=${() => setAll(!all)}>${all ? "Show headline rows only" : "Show all sampling and height-adjustment variants"}</button></p></div>
    <div class="card"><h2>Bias-adjusted range</h2>
      <p class="small muted">HRRR quantile-mapped to the height-adjusted buoy winds. An adjustment, not a measurement: the truth likely lies between raw and adjusted. Bars show ${"<"} 5 / 5–20 / ≥ 20 kt.</p>
      <${Table} cols=${[
        { head: "Window", cell: (r) => label(r.venue, r.season) }, { head: "Version", left: true, cell: (r) => r.version },
        { head: "Mean (kt)", cell: (r) => fmt(r.mean) }, { head: "< 5", cell: (r) => pct(r.pct_lt5) },
        { head: "5–20", cell: (r) => pct(r.pct_5_20) }, { head: "≥ 20", cell: (r) => pct(r.pct_ge20, 1) },
        { head: "Mix", left: true, cell: (r) => html`<${Mix} r=${r} />` }, { head: "Fit pairs", cell: (r) => r.n_fit_pairs }]} rows=${adjusted} />
      <p class="note">Treat a buoy far from the sample point as an upper bound: its winds may not represent the shore.</p></div>
  </div>`;
}
