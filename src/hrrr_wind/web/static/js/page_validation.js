import { useState } from "preact/hooks";
import { html, Table, binColors } from "./components.js";
import { fmt, label, pct } from "./util.js";

const Mix = ({ r }) => { const c = binColors(); return html`<div class="bar" style="width:170px;margin:0"> ${[r.pct_lt5, r.pct_5_20, r.pct_ge20].map((v, i) =>
  html`<i title=${pct(v)} style=${{ width: v + "%", background: [c[0], c[2], c[4]][i] }}></i>`)}</div>`; };

export function ValidationPage({ meta, data }) {
  const { validation, adjusted } = data.results;
  const [all, setAll] = useState(false);
  const rows = validation.filter((r) => all || (r.height_adj.startsWith("log") && r.subset.startsWith("racing") && r.hrrr_sampling === "2 nm water box"));
  const buoy = (v) => meta.buoys.find((b) => b.venue === v);
  return html`<div class="grid">
    <div class="card"><h2>HRRR versus buoys</h2>
      <p class="small muted">Bias is HRRR minus buoy (negative: HRRR reads low). Buoy winds are scaled from the anemometer height to 10 m with a neutral log profile.
        ${meta.buoys.map((b) => html` Buoy ${b.id} serves ${b.venue.toUpperCase()}.`)}</p>
      <${Table} cols=${[
        { head: "Venue", cell: (r) => `${r.venue.toUpperCase()} (${r.buoy})` },
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
