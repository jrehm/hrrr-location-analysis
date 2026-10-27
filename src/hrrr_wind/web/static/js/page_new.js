import { useEffect, useRef, useState } from "preact/hooks";
import { post } from "./api.js";
import { html } from "./components.js";
import { debounce } from "./util.js";

const TILE = ["https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}", "Imagery © Esri"];
export const ZONES = [["EDT", -4], ["EST", -5], ["CDT", -5], ["CST", -6], ["MDT", -6], ["MST", -7], ["PDT", -7], ["PST", -8]];
const FILES_PER_SECOND = 1.9;     // observed download rate; for the estimate only
const MMDD = /^(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])$/;
const BUFFER_DAYS = 3;            // keep in step with config.BUFFER_DAYS
const MAX_WINDOWS = 6;
const MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const MDAYS = [31, 29, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
const pad = (n) => String(n).padStart(2, "0");
// Internal window id: the start month, numbered when two windows start in the same month. Never shown.
const seasonOf = (w, i, all) => {
  const m = MON[+w.start.slice(0, 2) - 1].toLowerCase(), n = all.slice(0, i + 1).filter((x) => x.start.slice(0, 2) === w.start.slice(0, 2)).length;
  return n > 1 ? m + n : m;
};

// Month + day pickers producing "MM-DD" (so nobody types dates or hits Feb 30).
export function DateSelect({ value, onChange }) {
  const m = +value.slice(0, 2), d = +value.slice(3);
  const set = (mm, dd) => onChange(`${pad(mm)}-${pad(Math.min(dd, MDAYS[mm - 1]))}`);
  return html`<div class="row" style="gap:6px"><select value=${m} onChange=${(e) => set(+e.target.value, d)}>${MON.map((n, i) => html`<option value=${i + 1}>${n}</option>`)}</select>
    <select value=${d} onChange=${(e) => set(m, +e.target.value)}>${Array.from({ length: MDAYS[m - 1] }, (_, i) => html`<option value=${i + 1}>${i + 1}</option>`)}</select></div>`;
}
const day = (s) => Date.parse(`2001-${s}`) / 864e5;
const slugify = (s, n) => s.toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "").slice(0, n);
const fmtTime = (s) => (s < 90 ? `${Math.round(s)} s` : s < 5400 ? `${Math.round(s / 60)} min` : `${(s / 3600).toFixed(1)} h`);

// Satellite map; a click places the club. Draws the club, sample point, averaging box and HRRR cells.
function PickMap({ club, geo, onPick, focus }) {
  const el = useRef(), map = useRef(), layer = useRef(), pick = useRef(onPick), fitted = useRef(false);
  pick.current = onPick;
  useEffect(() => {
    map.current = L.map(el.current, { zoomSnap: 0.25 }).setView(focus || [39, -96], focus ? 9 : 4);
    L.tileLayer(TILE[0], { attribution: TILE[1], maxZoom: 18 }).addTo(map.current);
    layer.current = L.layerGroup().addTo(map.current);
    map.current.on("click", (e) => pick.current(e.latlng.lat, e.latlng.lng));
    return () => map.current.remove();
  }, []);
  useEffect(() => {
    const g = layer.current; g.clearLayers();
    if (!club) return;
    const c = [club.lat, club.lon];
    if (geo) {
      geo.cells.forEach((x) => L.circleMarker([x.lat, x.lon], {
        radius: x.in_box ? 5 : 3, weight: x.in_box ? 1.5 : 0, color: "#fff", fillOpacity: x.in_box ? 0.9 : 0.35,
        fillColor: x.water ? "#2f7fd0" : "#a67c3d" }).addTo(g));
      L.rectangle(geo.box, { color: "#ffd24a", weight: 2, fill: false, dashArray: "6 4" }).addTo(g);
      L.polyline([c, [geo.sample.lat, geo.sample.lon]], { color: "#fff", weight: 2 }).addTo(g);
      L.circleMarker([geo.sample.lat, geo.sample.lon], { radius: 7, color: "#fff", weight: 2, fillColor: "#e5484d", fillOpacity: 1 })
        .bindTooltip("sample point").addTo(g);
    }
    L.circleMarker(c, { radius: 7, color: "#111", weight: 2, fillColor: "#fff", fillOpacity: 1 }).bindTooltip("club").addTo(g);
    if (!fitted.current) { map.current.setView(c, 11); fitted.current = true; }
  }, [club?.lat, club?.lon, geo]);
  return html`<div id="map" ref=${el}></div>`;
}

const preview = debounce(async (body, ok, fail) => {
  try { ok(await post("preview/geometry", body)); } catch (e) { fail(e.message); }
}, 300);

/**
 * mode "new": create a study (one venue; add more afterwards with "Add venue").
 * mode "add": add a venue and its windows to the open study.
 */
export function NewStudyPage({ meta, studies, mode, onDone }) {
  const adding = mode === "add";
  const thisYear = new Date().getFullYear();
  const [s, setS] = useState({ name: "", y0: 2015, y1: thisYear - 1, h0: 11, h1: 16, zone: 0 });
  const [v, setV] = useState({ name: "", key: "", keyTouched: false, bearing: 90, offshore_nm: 2, radius_nm: 4, zone: null });
  const [club, setClub] = useState(null);
  const [wins, setWins] = useState([{ start: "09-08", end: "09-14" }]);
  const [geo, setGeo] = useState(null), [pErr, setPErr] = useState(null), [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null), [startNow, setStartNow] = useState(true);
  const setSv = (k) => (e) => setS({ ...s, [k]: e.target.type === "number" ? Number(e.target.value) : e.target.value });
  const NUMERIC = ["bearing", "offshore_nm", "radius_nm"];   // a <select> reports text, so coerce by field
  const setVv = (k) => (e) => setV({ ...v, [k]: NUMERIC.includes(k) ? Number(e.target.value) : e.target.value });

  const years = adding ? meta.years : Array.from({ length: Math.max(0, s.y1 - s.y0 + 1) }, (_, i) => s.y0 + i);
  const [zoneName, offset] = adding ? [meta.tz_abbr, meta.utc_offset] : ZONES[s.zone];
  // A venue added to an existing study may be in another time zone; the racing hours stay the same local hours.
  const zones = adding && !ZONES.some(([n, o]) => n === meta.tz_abbr && o === meta.utc_offset) ? [[meta.tz_abbr, meta.utc_offset], ...ZONES] : ZONES;
  const vzone = v.zone ?? Math.max(0, zones.findIndex(([n, o]) => n === zoneName && o === offset));
  const key = v.keyTouched ? v.key : slugify(v.name, 12).replace(/_/g, "").replace(/^[0-9]+/, "");
  const slug = slugify(s.name, 40);
  const winOk = (w) => MMDD.test(w.start) && MMDD.test(w.end) && day(w.end) >= day(w.start)
    && day(w.start) - BUFFER_DAYS >= day("01-01") && day(w.end) + BUFFER_DAYS <= day("12-31")
    && day(w.end) - day(w.start) + 1 + 2 * BUFFER_DAYS <= 45;
  const dupDates = new Set(wins.map((w) => `${w.start}|${w.end}`)).size !== wins.length;
  const spans = [...new Set(wins.filter(winOk).map((w) => `${w.start}|${w.end}`))];
  const files = spans.reduce((a, k) => { const [x, y] = k.split("|"); return a + (day(y) - day(x) + 1 + 2 * BUFFER_DAYS) * 24 * years.length; }, 0);

  useEffect(() => { // live map preview of the sample point
    if (!club) return;
    setPErr(null);
    preview({ lat: club.lat, lon: club.lon, bearing: v.bearing, offshore_nm: v.offshore_nm, radius_nm: v.radius_nm },
      setGeo, (m) => { setGeo(null); setPErr(m); });
  }, [club?.lat, club?.lon, v.bearing, v.offshore_nm, v.radius_nm]);

  const ago = geo && geo.n_water === 0;
  const checks = [
    [adding || (s.name.trim() && slug.length >= 2), "Give the study a name"],
    [adding || !studies.some((x) => x.id === slug), "A study with that name already exists"],
    [adding || (years.length && s.y0 >= 2015 && s.y1 <= thisYear), `Years must run from 2015 to ${thisYear}`],
    [adding || (s.h0 <= s.h1 && s.h0 - offset >= 0 && s.h1 - offset <= 23), "Racing hours must be a forward range within one UTC day"],
    [v.name.trim(), "Name the club or venue"],
    [/^[a-z][a-z0-9]{0,11}$/.test(key), "Venue id: 1-12 lowercase letters/digits, starting with a letter"],
    [!adding || !meta.venues.some((x) => x.key === key), "That venue id is already in this study"],
    [club, "Click the club's position on the map"],
    [!ago, "The sample point's box has no water cells: increase the distance offshore, change the bearing, or widen the box"],
    [wins.length && wins.every(winOk) && !dupDates, "Each window needs valid dates (at least 3 days from the year's ends, at most 39 days long), and no two windows may repeat the same dates"],
  ];
  const problem = (checks.find(([ok]) => !ok) || [])[1];

  const submit = async () => {
    setBusy(true); setErr(null);
    const venue = { key, name: v.name.trim(), lat: Number(club.lat.toFixed(5)), lon: Number(club.lon.toFixed(5)),
      bearing: v.bearing, offshore_nm: v.offshore_nm, radius_nm: v.radius_nm,
      ...(adding ? { tz_abbr: zones[vzone][0], utc_offset: zones[vzone][1] } : {}) };
    // Adding to an existing study: the server picks each window's id, so new dates never clash with an old id.
    const windows = wins.map((w, i, all) => ({ ...(adding ? {} : { season: seasonOf(w, i, all) }), core: [w.start, w.end] }));
    try {
      let id = meta?.id;
      if (adding) await post(`studies/${id}/venues`, { venue, windows });
      else {
        id = slug;
        await post("studies", { slug, definition: { name: s.name.trim(), years, race_hours_utc: [s.h0 - offset, s.h1 - offset],
          utc_offset: offset, tz_abbr: zoneName, venues: [venue], windows: windows.map((w) => ({ ...w, venue: key })) } });
      }
      if (startNow) await post(`studies/${id}/jobs`, { kind: "run_study", params: {} });
      onDone(id);
    } catch (e) { setErr(e.message); setBusy(false); }
  };

  const setWin = (i, k) => (e) => setWins(wins.map((w, j) => (j === i ? { ...w, [k]: e.target.value.trim() } : w)));
  return html`<div class="grid g2" style="grid-template-columns:minmax(0,340px) minmax(0,1fr)">
    <div class="grid" style="align-content:start">
      ${!adding && html`<div class="card controls"><h2>New study</h2>
        <label class="f">Study name<input type="text" maxlength="80" value=${s.name} onInput=${setSv("name")} placeholder="Lake Erie regatta 2029" /></label>
        <div class="row"><label class="f" style="flex:1">First year<input type="number" min="2015" max=${thisYear} value=${s.y0} onInput=${setSv("y0")} /></label>
          <label class="f" style="flex:1">Last year<input type="number" min="2015" max=${thisYear} value=${s.y1} onInput=${setSv("y1")} /></label></div>
        <div class="row"><label class="f" style="flex:1">Racing from (local hour)<input type="number" min="0" max="23" value=${s.h0} onInput=${setSv("h0")} /></label>
          <label class="f" style="flex:1">to<input type="number" min="0" max="23" value=${s.h1} onInput=${setSv("h1")} /></label></div>
        <label class="f">Time zone<select value=${s.zone} onChange=${(e) => setS({ ...s, zone: Number(e.target.value) })}>
          ${ZONES.map(([n, o], i) => html`<option value=${i}>${n} (UTC${o})</option>`)}</select></label>
      </div>`}
      <div class="card controls"><h2>${adding ? `Add a venue to ${meta.name}` : "Venue"}</h2>
        <label class="f">Club or venue name<input type="text" maxlength="60" value=${v.name} onInput=${setVv("name")} placeholder="Port Clinton Yacht Club" /></label>
        ${adding && html`<label class="f">Time zone (racing hours are local: ${meta.race_label})<select value=${vzone} onChange=${(e) => setV({ ...v, zone: Number(e.target.value) })}>
          ${zones.map(([zn, o], i) => html`<option value=${i}>${zn} (UTC${o})</option>`)}</select></label>`}
        <label class="f">Short id (file names)<input type="text" maxlength="12" value=${key} onInput=${(e) => setV({ ...v, key: e.target.value, keyTouched: true })} /></label>
        <p class="small ${club ? "muted" : "err"}">${club ? `Club position ${club.lat.toFixed(5)}, ${club.lon.toFixed(5)}. Click the map again to move it.` : "Click the club on the satellite map (zoom in to the docks or flagpole)."}</p>
        <label class="f">Bearing from club to sample point: ${v.bearing}° true
          <input type="range" min="0" max="359" value=${v.bearing} onInput=${setVv("bearing")} /></label>
        <label class="f">Distance offshore: ${v.offshore_nm} nm
          <input type="range" min="0.5" max="10" step="0.5" value=${v.offshore_nm} onInput=${setVv("offshore_nm")} /></label>
        <label class="f">Averaging box half-width
          <select value=${v.radius_nm} onChange=${setVv("radius_nm")}>${[2, 4, 6].map((r) => html`<option value=${r}>${r} nm</option>`)}</select></label>
        ${ago && html`<p class="err">No water cells in this box. Move the bearing offshore or widen the box.</p>`}
        ${geo && !geo.has_grid && html`<p class="small muted">Land and water cells could not be loaded, so only the box is drawn. They appear after the first download.</p>`}
        ${pErr && html`<p class="small muted">Map preview unavailable: ${pErr}</p>`}
      </div>
      <div class="card controls"><h2>Windows</h2>
        <p class="small muted">The dates raced each year (the core window); the download adds ${BUFFER_DAYS} days either side for context. </p>
        ${wins.map((w, i) => html`<div class="row" style="align-items:end;flex-wrap:wrap">
          <label class="f">From<${DateSelect} value=${w.start} onChange=${(v) => setWins(wins.map((x, j) => (j === i ? { ...x, start: v } : x)))} /></label>
          <label class="f">To<${DateSelect} value=${w.end} onChange=${(v) => setWins(wins.map((x, j) => (j === i ? { ...x, end: v } : x)))} /></label>
          ${wins.length > 1 && html`<button onClick=${() => setWins(wins.filter((_, j) => j !== i))} title="Remove window">×</button>`}</div>`)}
        ${wins.length < MAX_WINDOWS && html`<button onClick=${() => setWins([...wins, { start: "06-14", end: "06-21" }])}>Add window</button>`}
      </div>
      <div class="card controls">
        <label class="small"><input type="checkbox" checked=${startNow} onChange=${(e) => setStartNow(e.target.checked)} /> Start the download and analysis now</label>
        <p class="small muted">${files ? `${years.length} years × ${spans.length} window span(s): about ${files.toLocaleString()} hourly files, roughly ${fmtTime(files / FILES_PER_SECOND)} to download. Runs in the background with a memory cap; you can leave the page, and cancel or resume from the status bar.` : "Enter valid windows to see the download size."}</p>
        ${problem && html`<p class="small err">${problem}</p>`}
        ${err && html`<p class="err">${err}</p>`}
        <button disabled=${busy || !!problem} onClick=${submit}>${busy ? "Working…" : adding ? "Add venue" : "Create study"}${startNow && !busy ? " and start" : ""}</button>
      </div>
    </div>
    <div>
      <${PickMap} club=${club} geo=${geo} focus=${adding && meta.venues[0] ? [meta.venues[0].lat, meta.venues[0].lon] : null}
        onPick=${(lat, lon) => setClub({ lat, lon })} />
      <p class="small muted">Blue dots are HRRR water cells, brown are land; cells inside the dashed box are averaged. The sample point is projected from the club position, so confirm the club on this satellite view before running anything.</p>
    </div>
  </div>`;
}
