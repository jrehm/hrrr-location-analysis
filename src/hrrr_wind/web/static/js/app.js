import { render } from "preact";
import { useEffect, useState } from "preact/hooks";
import { api, patch } from "./api.js";
import { html } from "./components.js";
import { SetupPage } from "./page_setup.js";
import { ResultsPage, useStudyData } from "./page_results.js";
import { ValidationPage } from "./page_validation.js";
import { FilesPage } from "./page_files.js";
import { VenuesPage } from "./page_venues.js";
import { NewStudyPage } from "./page_new.js";
import { StatusStrip } from "./status.js";
import { yearsSummary } from "./years.js";

const theme = new URLSearchParams(location.search).get("theme");  // ?theme=dark|light forces a theme
if (theme) document.documentElement.dataset.theme = theme;

// Routes: #/ (opens the first study), #/new, #/s/<id>/<page>[/<arg>]
const parse = () => {
  const p = location.hash.replace(/^#\/?/, "").split("/");
  if (p[0] === "new") return { page: "new" };
  if (p[0] === "s" && p[1]) return { sid: p[1], page: MOVED[p[2]] || p[2] || "overview", arg: p[3] };
  return { page: "home" };
};
const go = (path) => { location.hash = path; };

const TABS = [["inputs", "Inputs"], ["overview", "Overview"], ["validation", "Validation"], ["files", "Files"]];
const PAGES = { overview: ResultsPage, validation: ValidationPage, files: FilesPage };
const MOVED = { venues: "inputs", compare: "overview" };    // old page names (bookmarks)

// A tab per study plus a "+" tab; extra studies wrap onto further rows. A dot flags studies that need attention.
const DOT = { running: ["running", ""], stale: ["results out of date", "warn"], no_data: ["no data yet", "warn"],
  partial: ["data incomplete", "warn"], no_results: ["not analyzed", "warn"] };
function StudyTabs({ studies, sid, readonly, isNew }) {
  return html`<nav class="studybar"><div class="wrap">${studies.map((s) => { const dot = DOT[s.state];
    return html`<a href=${`#/s/${s.id}/overview`} class=${s.id === sid ? "on" : ""} title=${s.name + (dot ? ` (${dot[0]})` : "")}>
      <span class="nm">${s.name}</span>${s.locked && html`<span class="lock" aria-label="locked reference study">🔒</span>`}
      ${dot && html`<span class=${"dot " + dot[1]} />`}</a>`; })}
    ${!readonly && html`<a href="#/new" class=${"plus" + (isNew ? " on" : "")} title="New study" aria-label="New study">+</a>`}</div></nav>`;
}

function App() {
  const [route, setRoute] = useState(parse());
  const [studies, setStudies] = useState(null), [readonly, setReadonly] = useState(false);
  const [meta, setMeta] = useState(null), [err, setErr] = useState(null), [notice, setNotice] = useState(null);
  const [version, setVersion] = useState(0);   // bumped when results or caches change
  const [renaming, setRenaming] = useState(null);
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
    setMeta(null); setNotice(null); setRenaming(null);
    if (sid) api(`studies/${sid}`).then(setMeta).catch(() => api("studies").then((l) => {   // unknown or broken study: open another
      const other = l.find((s) => s.id !== sid); go(other ? `#/s/${other.id}/overview` : "#/new");
    }));
  }, [sid]);
  useEffect(() => { api("studies").then(setStudies).catch(() => {}); }, [route.page]); // fresh tab states on each page change
  useEffect(() => { // the root opens the first study (or the new-study page when there are none)
    if (route.page === "home" && studies) go(studies.length ? `#/s/${studies[0].id}/overview` : "#/new");
  }, [route.page, studies]);

  const { d, err: derr } = useStudyData(meta, version);
  if (err) return html`<main class="wrap"><p class="err">Could not load: ${err}</p></main>`;
  if (!studies) return html`<main class="wrap"><p class="muted">Loading…</p></main>`;

  const edited = async (text) => { await refresh(); setNotice(text); };
  const rename = async () => {
    try { await patch(`studies/${sid}`, { name: renaming }); setRenaming(null); await edited("Renamed."); }
    catch (e) { setNotice(`Could not rename: ${e.message}`); }
  };
  const done = async (id, text) => { await refresh(id); setNotice(text); go(`#/s/${id}/${text.startsWith("Added") ? "inputs" : "overview"}`); };
  const bar = html`<${StudyTabs} studies=${studies} sid=${route.page === "new" ? null : sid} isNew=${route.page === "new"} readonly=${readonly} />`;
  const Shell = (title, body) => html`${bar}<header class="top"><div class="wrap"><h1>${title}</h1>
      ${readonly && html`<span class="badge">read-only demo</span>`}</div><div style="height:12px"></div></header>
    <main class="wrap">${body}</main>`;

  if (route.page === "home") return html`<main class="wrap"><p class="muted">Loading…</p></main>`;
  if (route.page === "new") return Shell("New study", html`<${NewStudyPage} studies=${studies} mode="new"
    onDone=${(id) => done(id, "Study created.")} />`);

  if (!meta) return html`${bar}<main class="wrap"><p class="muted">Loading…</p></main>`;
  const canEdit = !meta.readonly && !meta.locked;
  const tabs = TABS.filter(([k]) => !(k === "validation" && !meta.buoys.length));
  const tab = route.page === "venue" || route.page === "add" ? "inputs" : route.page;
  const Page = PAGES[route.page] || ResultsPage;
  let body;
  if (route.page === "add" && !meta.readonly && !meta.locked) body = html`<${NewStudyPage} meta=${meta} studies=${studies} mode="add"
    onDone=${(id) => done(id, "Added venue.")} />`;
  else if (route.page === "venue") body = html`<${SetupPage} meta=${meta} venueKey=${route.arg} onSaved=${edited} />`;
  else if (route.page === "inputs") body = html`<${VenuesPage} meta=${meta} onChanged=${() => refresh()} onEdited=${edited} />`;
  else if (derr) body = html`<p class="err">${derr}</p>`;
  else if (!d) body = html`<p class="muted">Loading results…</p>`;
  else body = html`<${Page} meta=${meta} data=${d} />`;

  return html`${bar}<header class="top"><div class="wrap">
      ${renaming === null ? html`<h1>${meta.name}</h1>${canEdit && html`<button class="icon" title="Rename this study" aria-label="Rename this study" onClick=${() => setRenaming(meta.name)}>✎</button>`}`
        : html`<div class="row" style="flex:1;min-width:260px"><input type="text" maxlength="80" value=${renaming} onInput=${(e) => setRenaming(e.target.value)}
            onKeyDown=${(e) => e.key === "Enter" && rename()} /><button class="primary" onClick=${rename}>Save</button><button onClick=${() => setRenaming(null)}>Cancel</button></div>`}
      <span class="sub">HRRR 10 m wind, years ${yearsSummary(meta)}, racing ${meta.race_label}</span>
      ${meta.readonly && html`<span class="badge">read-only demo</span>`}${meta.locked && html`<span class="badge">locked reference study</span>`}
      <nav class="tabs">${tabs.map(([k, t]) => html`<a href=${`#/s/${meta.id}/${k}`} class=${tab === k ? "on" : ""}>${t}</a>`)}</nav>
    </div></header>
    <main class="wrap">
      <${StatusStrip} meta=${meta} onChanged=${() => refresh()} />
      ${notice && html`<div class="notice"><span>${notice}</span><a href="#" onClick=${(e) => { e.preventDefault(); setNotice(null); }}>dismiss</a></div>`}
      ${body}</main>`;
}
render(html`<${App} />`, document.getElementById("app"));
