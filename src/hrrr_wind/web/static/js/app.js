import { render } from "preact";
import { useEffect, useState } from "preact/hooks";
import { api, patch } from "./api.js";
import { html } from "./components.js";
import { HomePage } from "./page_home.js";
import { SetupPage } from "./page_setup.js";
import { ResultsPage, useStudyData } from "./page_results.js";
import { ComparePage } from "./page_compare.js";
import { ValidationPage } from "./page_validation.js";
import { FilesPage } from "./page_files.js";
import { VenuesPage } from "./page_venues.js";
import { NewStudyPage } from "./page_new.js";
import { StatusStrip } from "./status.js";
import { YearsEditor, yearsSummary } from "./years.js";

const theme = new URLSearchParams(location.search).get("theme");  // ?theme=dark|light forces a theme
if (theme) document.documentElement.dataset.theme = theme;

// Routes: #/ (all studies), #/new, #/s/<id>/<page>[/<arg>]
const parse = () => {
  const p = location.hash.replace(/^#\/?/, "").split("/");
  if (p[0] === "new") return { page: "new" };
  if (p[0] === "s" && p[1]) return { sid: p[1], page: p[2] || "overview", arg: p[3] };
  return { page: "home" };
};
const go = (path) => { location.hash = path; };

const TABS = [["overview", "Overview"], ["venues", "Venues"], ["compare", "Compare"], ["validation", "Validation"], ["files", "Files"]];
const PAGES = { overview: ResultsPage, compare: ComparePage, validation: ValidationPage, files: FilesPage };

function App() {
  const [route, setRoute] = useState(parse());
  const [studies, setStudies] = useState(null), [readonly, setReadonly] = useState(false);
  const [meta, setMeta] = useState(null), [err, setErr] = useState(null), [notice, setNotice] = useState(null);
  const [version, setVersion] = useState(0);   // bumped when results or caches change
  const [renaming, setRenaming] = useState(null), [editYears, setEditYears] = useState(false);
  const sid = route.sid;

  useEffect(() => {
    const on = () => setRoute(parse()); addEventListener("hashchange", on);
    Promise.all([api("studies"), api("health")]).then(([l, h]) => { setStudies(l); setReadonly(!!h.readonly); const f = document.getElementById("ver"); if (f && h.version) f.textContent = `HRRR Wind Analysis v${h.version}`; }).catch((e) => setErr(e.message));
    return () => removeEventListener("hashchange", on);
  }, []);
  const refresh = async (id = sid) => { // reload the study (and the list) after something changed
    const [m, l] = await Promise.all([api(`studies/${id}`), api("studies")]);
    setMeta(m); setStudies(l); setVersion((v) => v + 1);
  };
  useEffect(() => { // load the study named in the URL
    setMeta(null); setNotice(null); setRenaming(null); setEditYears(false);
    if (sid) api(`studies/${sid}`).then(setMeta).catch(() => go("#/"));
  }, [sid]);
  useEffect(() => { if (!sid) api("studies").then(setStudies).catch(() => {}); }, [route.page]); // fresh states on the home page

  const { d, err: derr } = useStudyData(meta, version);
  if (err) return html`<main class="wrap"><p class="err">Could not load: ${err}</p></main>`;
  if (!studies) return html`<main class="wrap"><p class="muted">Loading…</p></main>`;

  const edited = async (text) => { await refresh(); setNotice(text); };
  const rename = async () => {
    try { await patch(`studies/${sid}`, { name: renaming }); setRenaming(null); await edited("Renamed."); }
    catch (e) { setNotice(`Could not rename: ${e.message}`); }
  };
  const done = async (id, text) => { await refresh(id); setNotice(text); go(`#/s/${id}/${text.startsWith("Added") ? "venues" : "overview"}`); };
  const Shell = (title, body, sub) => html`<header class="top"><div class="wrap"><div class="crumb"><a href="#/">All studies</a>${sub ? " › " + sub : ""}</div>
      <h1>${title}</h1>${readonly && html`<span class="badge">read-only demo</span>`}</div><div style="height:12px"></div></header>
    <main class="wrap">${body}</main>`;

  if (route.page === "home") return html`<header class="top"><div class="wrap"><h1>HRRR Wind Analysis</h1><span class="sub">Wind climatology for sailing venues</span>
      ${readonly && html`<span class="badge">read-only demo</span>`}</div><div style="height:12px"></div></header>
    <main class="wrap"><${HomePage} studies=${studies} readonly=${readonly} /></main>`;
  if (route.page === "new") return Shell("New study", html`<${NewStudyPage} studies=${studies} mode="new"
    onDone=${(id) => done(id, "Study created.")} />`);

  if (!meta) return html`<main class="wrap"><p class="muted">Loading…</p></main>`;
  const canEdit = !meta.readonly && !meta.locked;
  const tabs = TABS.filter(([k]) => !(k === "validation" && !meta.buoys.length));
  const tab = route.page === "venue" || route.page === "add" ? "venues" : route.page;
  const Page = PAGES[route.page] || ResultsPage;
  let body;
  if (route.page === "add" && !meta.readonly && !meta.locked) body = html`<${NewStudyPage} meta=${meta} studies=${studies} mode="add"
    onDone=${(id) => done(id, "Added venue.")} />`;
  else if (route.page === "venue") body = html`<${SetupPage} meta=${meta} venueKey=${route.arg} onSaved=${edited} />`;
  else if (route.page === "venues") body = html`<${VenuesPage} meta=${meta} onChanged=${() => refresh()} onEdited=${edited} />`;
  else if (derr) body = html`<p class="err">${derr}</p>`;
  else if (!d) body = html`<p class="muted">Loading results…</p>`;
  else body = html`<${Page} meta=${meta} data=${d} />`;

  return html`<header class="top"><div class="wrap">
      <div class="crumb"><a href="#/">All studies</a></div>
      ${renaming === null ? html`<h1>${meta.name}</h1>${canEdit && html`<a href="#" class="small" onClick=${(e) => { e.preventDefault(); setRenaming(meta.name); }}>Rename</a>`}`
        : html`<div class="row" style="flex:1;min-width:260px"><input type="text" maxlength="80" value=${renaming} onInput=${(e) => setRenaming(e.target.value)}
            onKeyDown=${(e) => e.key === "Enter" && rename()} /><button class="primary" onClick=${rename}>Save</button><button onClick=${() => setRenaming(null)}>Cancel</button></div>`}
      <span class="sub">HRRR 10 m wind, years ${yearsSummary(meta)}, racing ${meta.race_label}</span>
      ${canEdit && html`<a href="#" class="small" onClick=${(e) => { e.preventDefault(); setEditYears(!editYears); }}>Edit years</a>`}
      ${meta.readonly && html`<span class="badge">read-only demo</span>`}${meta.locked && html`<span class="badge">locked reference study</span>`}
      <nav class="tabs">${tabs.map(([k, t]) => html`<a href=${`#/s/${meta.id}/${k}`} class=${tab === k ? "on" : ""}>${t}</a>`)}</nav>
    </div></header>
    <main class="wrap">
      <${StatusStrip} meta=${meta} onChanged=${() => refresh()} />
      ${editYears && html`<${YearsEditor} meta=${meta} onClose=${() => setEditYears(false)}
        onSaved=${async () => { setEditYears(false); await edited("Years updated. See the bar above for what happens next."); }} />`}
      ${notice && html`<div class="notice"><span>${notice}</span><a href="#" onClick=${(e) => { e.preventDefault(); setNotice(null); }}>dismiss</a></div>`}
      ${body}</main>`;
}
render(html`<${App} />`, document.getElementById("app"));
