import { html } from "./components.js";

const CHIP = { ready: ["ready", "ok"], running: ["running", ""], stale: ["results out of date", "warn"], no_data: ["no data yet", "warn"],
  partial: ["data incomplete", "warn"], no_results: ["not analyzed", "warn"] };

export function HomePage({ studies, readonly }) {
  return html`<div class="grid">
    <div class="row" style="justify-content:space-between"><h2 style="margin:0">Studies</h2>
      ${!readonly && html`<a href="#/new"><button class="primary">+ New study</button></a>`}</div>
    ${!studies.length && html`<p class="muted">No studies yet.</p>`}
    <div class="grid g3">${studies.map((s) => { const [t, tone] = CHIP[s.state] || [s.state, ""]; return html`
      <a class="card link" href=${`#/s/${s.id}/overview`}>
        <h2>${s.name}</h2>
        <p class="small muted" style="margin:0 0 8px">${s.venues.join(" · ")}<br />${s.years[0] === s.years[1] ? s.years[0] : `${s.years[0]}–${s.years[1]}`}${s.locked ? " · reference study (locked)" : ""}</p>
        <span class=${"chip " + tone}>${t}</span></a>`; })}</div>
  </div>`;
}
