import { render } from "preact";
import { useEffect, useState } from "preact/hooks";
import { api } from "./api.js";
import { html } from "./components.js";
import { SetupPage } from "./page_setup.js";
import { ResultsPage, useStudyData } from "./page_results.js";
import { ComparePage } from "./page_compare.js";
import { ValidationPage } from "./page_validation.js";
import { FilesPage } from "./page_files.js";

const TABS = [["setup", "Sample point"], ["results", "Results"], ["compare", "Compare"], ["validation", "Validation"], ["files", "Files"]];
const theme = new URLSearchParams(location.search).get("theme");  // ?theme=dark|light forces a theme
if (theme) document.documentElement.dataset.theme = theme;
const route = () => (location.hash.replace("#/", "") || "results");

function App() {
  const [meta, setMeta] = useState(null), [tab, setTab] = useState(route()), [err, setErr] = useState(null);
  useEffect(() => {
    const on = () => setTab(route()); addEventListener("hashchange", on);
    api("studies").then((s) => api(`studies/${s[0].id}`)).then(setMeta).catch((e) => setErr(e.message));
    return () => removeEventListener("hashchange", on);
  }, []);
  const { d, err: derr } = useStudyData(meta);
  if (err) return html`<main class="wrap"><p class="err">Could not load the study: ${err}</p></main>`;
  if (!meta) return html`<main class="wrap"><p class="muted">Loading…</p></main>`;
  const page = { setup: SetupPage, results: ResultsPage, compare: ComparePage, validation: ValidationPage, files: FilesPage }[tab] || ResultsPage;
  return html`<header class="top"><div class="wrap">
      <h1>${meta.name}</h1>
      <span class="sub">HRRR 10 m wind, ${meta.years[0]}–${meta.years.at(-1)}, racing ${meta.race_label}</span>
      ${meta.readonly && html`<span class="badge">read-only demo</span>`}
      <nav class="tabs">${TABS.map(([k, t]) => html`<a href=${"#/" + k} class=${tab === k ? "on" : ""}>${t}</a>`)}</nav>
    </div></header>
    <main class="wrap">${derr ? html`<p class="err">${derr}</p>` : tab === "setup" ? html`<${SetupPage} meta=${meta} />`
      : !d ? html`<p class="muted">Loading results…</p>` : html`<${page} meta=${meta} data=${d} />`}</main>`;
}
render(html`<${App} />`, document.getElementById("app"));
