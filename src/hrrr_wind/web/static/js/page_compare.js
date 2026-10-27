import { html, Table } from "./components.js";
import { fmt, label, range, short } from "./util.js";

const nice = { mean_kt: "Mean wind (kt)", pct_5_20: "Share in 5–20 kt (points)", pct_ge20: "Share at 20 kt or more (points)" };

export function ComparePage({ meta, data }) {
  const { paired, band } = data.results;
  const groups = [...new Set(band.map((b) => `${b.venue}|${b.season}`))].map((k) => {
    const [venue, season] = k.split("|"), rows = band.filter((b) => b.venue === venue && b.season === season);
    const mm = (f) => [Math.min(...rows.map(f)), Math.max(...rows.map(f))];
    return { venue, season, n: rows.length, mean: mm((r) => r.mean), lt5: mm((r) => r.pct_lt5), mid: mm((r) => r.pct_5_20), ge20: mm((r) => r.pct_ge20) };
  });
  const order = (g) => meta.windows.findIndex((w) => w.venue === g.venue && w.season === g.season);
  groups.sort((x, y) => order(x) - order(y));
  return html`<div class="grid">
    ${paired.map((p) => html`<div class="card"><h2>${short(p.a)} minus ${short(p.b)}, ${label("", p.season)}</h2>
      <p class="small muted">Paired by day; confidence intervals resample whole years.</p>
      <${Table} cols=${[
        { head: "Metric", cell: (r) => nice[r.metric.split(" ").slice(3).join(" ")] || r.metric },
        { head: "Difference", cell: (r) => (r.diff >= 0 ? "+" : "") + fmt(r.diff) },
        { head: "95% CI", cell: (r) => `${(r.lo >= 0 ? "+" : "")}${fmt(r.lo)} to ${(r.hi >= 0 ? "+" : "")}${fmt(r.hi)}` },
        { head: "Distinguishable?", cell: (r) => (r.lo > 0 || r.hi < 0 ? html`<span class="yes">yes</span>` : html`<span class="no">no</span>`) },
        { head: "Days", cell: (r) => r.n_days }]} rows=${p.rows} /></div>`)}
    <div class="card"><h2>Sensitivity to the sample point</h2>
      <p class="small muted">Range across offshore distance and box radius at the primary bearing (racing hours, core window). If these ranges are narrow, the answer doesn't depend on exactly where the point sits.</p>
      <${Table} cols=${[
        { head: "Window", cell: (g) => label(g.venue, g.season) },
        { head: "Mean (kt)", cell: (g) => range(...g.mean) },
        { head: "< 5 kt (%)", cell: (g) => range(...g.lt5, 0) },
        { head: "5–20 kt (%)", cell: (g) => range(...g.mid, 0) },
        { head: "≥ 20 kt (%)", cell: (g) => range(...g.ge20) },
        { head: "Combos", cell: (g) => g.n }]} rows=${groups} /></div>
  </div>`;
}
