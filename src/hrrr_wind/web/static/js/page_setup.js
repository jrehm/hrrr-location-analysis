import { useEffect, useRef, useState } from "preact/hooks";
import { api, patch } from "./api.js";
import { html, binColors } from "./components.js";
import { debounce, fmt, label, pct, cssVar } from "./util.js";

const TILES = {
  "Satellite": ["https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}", "Imagery © Esri"],
  "Street": ["https://tile.openstreetmap.org/{z}/{x}/{y}.png", "© OpenStreetMap contributors"],
};

export function SetupPage({ meta, venueKey, onSaved }) {
  const [vkey, setVkey] = useState(meta.venues.some((v) => v.key === venueKey) ? venueKey : meta.venues[0].key);
  const venue = meta.venues.find((v) => v.key === vkey);
  const [p, setP] = useState({ bearing: venue.bearing, offshore_nm: venue.offshore_nm, radius_nm: venue.radius_nm });
  const seasons = meta.windows.filter((w) => w.venue === vkey);
  const [season, setSeason] = useState(seasons[0].season);
  const [geo, setGeo] = useState(null), [quick, setQuick] = useState(null), [err, setErr] = useState(null);
  const [name, setName] = useState(venue.name), [saving, setSaving] = useState(false), [saveErr, setSaveErr] = useState(null);
  const canSave = !meta.readonly && !meta.locked && !!onSaved;
  const mapEl = useRef(), map = useRef(), layer = useRef(), fitted = useRef(null);

  useEffect(() => { // switching venue resets the controls to the study's values
    setP({ bearing: venue.bearing, offshore_nm: venue.offshore_nm, radius_nm: venue.radius_nm });
    setName(venue.name);
    setSeason(meta.windows.find((w) => w.venue === vkey).season);
  }, [vkey]);

  const load = useRef(debounce(async (sid, v, s, q) => {
    try {
      const params = { venue: v, bearing: q.bearing, offshore_nm: q.offshore_nm, radius_nm: q.radius_nm };
      const [g, k] = await Promise.all([api(`studies/${sid}/geometry`, params), api(`studies/${sid}/quick`, { ...params, season: s })]);
      setGeo(g); setQuick(k); setErr(null);
    } catch (e) { setErr(e.message); }
  }, 150)).current;
  useEffect(() => { load(meta.id, vkey, season, p); }, [vkey, season, p.bearing, p.offshore_nm, p.radius_nm]);

  useEffect(() => { // create the map once
    map.current = L.map(mapEl.current, { zoomSnap: 0.25 });
    const base = Object.fromEntries(Object.entries(TILES).map(([k, [u, a]]) => [k, L.tileLayer(u, { attribution: a, maxZoom: 18 })]));
    base["Satellite"].addTo(map.current);
    L.control.layers(base).addTo(map.current);
    layer.current = L.layerGroup().addTo(map.current);
    return () => map.current.remove();
  }, []);

  useEffect(() => { // redraw overlays when geometry changes
    if (!geo) return;
    const g = layer.current; g.clearLayers();
    const club = [geo.club.lat, geo.club.lon], s = [geo.sample.lat, geo.sample.lon];
    geo.cells.forEach((c) => L.circleMarker([c.lat, c.lon], {
      radius: c.in_box ? 5 : 3, weight: c.in_box ? 1.5 : 0, color: "#fff", fillOpacity: c.in_box ? 0.9 : 0.35,
      fillColor: c.water ? "#2f7fd0" : "#a67c3d" }).bindTooltip(`${c.water ? "water" : "land"} cell${c.in_box ? " (averaged)" : ""}`).addTo(g));
    L.rectangle(geo.box, { color: "#ffd24a", weight: 2, fill: false, dashArray: "6 4" }).addTo(g);
    L.polyline([club, s], { color: "#fff", weight: 2 }).addTo(g);
    L.circleMarker(club, { radius: 7, color: "#111", weight: 2, fillColor: "#fff", fillOpacity: 1 }).bindTooltip(geo.club.name, { permanent: true, direction: "left" }).addTo(g);
    L.circleMarker(s, { radius: 7, color: "#fff", weight: 2, fillColor: "#e5484d", fillOpacity: 1 }).bindTooltip("sample point").addTo(g);
    if (fitted.current !== vkey) { map.current.fitBounds(L.latLngBounds([club, s]).extend(geo.box).pad(0.6)); fitted.current = vkey; }
  }, [geo]);

  const set = (k) => (e) => setP({ ...p, [k]: Number(e.target.value) });
  const q = quick, colors = binColors();
  const dirty = p.bearing !== venue.bearing || p.offshore_nm !== venue.offshore_nm || p.radius_nm !== venue.radius_nm;
  const save = async () => {
    setSaving(true); setSaveErr(null);
    try { await patch(`studies/${meta.id}/venues/${vkey}`, { name: name.trim(), ...p }); await onSaved(`Saved ${name.trim()}. The results need updating: see the bar above.`); }
    catch (e) { setSaveErr(e.message); }
    setSaving(false);
  };
  return html`<div class="grid g2" style="grid-template-columns:minmax(0,320px) minmax(0,1fr)">
    <div class="grid" style="align-content:start">
      <div class="card controls">
        <h2>Sample point</h2>
        <label class="f">Venue<select value=${vkey} onChange=${(e) => setVkey(e.target.value)}>
          ${meta.venues.map((v) => html`<option value=${v.key}>${v.name}</option>`)}</select></label>
        <label class="f">Bearing from club: ${p.bearing}° true
          <input type="range" min="0" max="359" value=${p.bearing} onInput=${set("bearing")} />
          <input type="number" min="0" max="359" value=${p.bearing} onInput=${set("bearing")} /></label>
        <label class="f">Distance offshore: ${p.offshore_nm} nm
          <input type="range" min="0.5" max="10" step="0.5" value=${p.offshore_nm} onInput=${set("offshore_nm")} /></label>
        <label class="f">Averaging box half-width
          <select value=${p.radius_nm} onChange=${set("radius_nm")}>${[2, 4, 6].map((r) => html`<option value=${r}>${r} nm</option>`)}</select></label>
        <label class="f">Window
          <select value=${season} onChange=${(e) => setSeason(e.target.value)}>
            ${seasons.map((w) => html`<option value=${w.season}>${label(vkey, w.season)} (${w.core[0]} to ${w.core[1]})</option>`)}</select></label>
        <button disabled=${!dirty} onClick=${() => setP({ bearing: venue.bearing, offshore_nm: venue.offshore_nm, radius_nm: venue.radius_nm })}>
          Reset to study values (${venue.bearing}°, ${venue.offshore_nm} nm)</button>
        ${canSave && html`<label class="f">Venue name<input type="text" maxlength="60" value=${name} onInput=${(e) => setName(e.target.value)} /></label>
          <button class="primary" disabled=${saving || (!dirty && name.trim() === venue.name) || !name.trim()} onClick=${save}>Save to study</button>
          <p class="small muted" style="margin:0">Saves the sample point and name. The club position is fixed: to move a club, add it as a new venue. No re-download is needed; the results are recomputed.</p>
          ${saveErr && html`<p class="err small">${saveErr}</p>`}`}
      </div>
      <div class="card">
        <h2>Racing-hour wind here</h2>
        ${err && html`<p class="err">${err}</p>`}
        ${q && q.no_data && html`<p class="muted">No wind data has been downloaded for this window yet (use the button at the top of the page).</p>`}
        ${q && q.n_cells === 0 && !q.no_data && html`<p class="err">No water cells in this box. Move the point offshore or widen the box.</p>`}
        ${q && q.n_cells > 0 && html`
          <div class="stat"><div><b>${fmt(q.mean)} kt</b><span class="small muted">mean</span></div>
            <div><b>${fmt(q.median)}</b><span class="small muted">median</span></div>
            <div><b>${fmt(q.p90)}</b><span class="small muted">90th pct</span></div>
            <div><b>${q.n_cells}</b><span class="small muted">water cells</span></div></div>
          <div class="bar">${[q.pct_lt5, q.pct_5_15, q.pct_15_20 + q.pct_ge20].map((v, i) => html`<i title=${pct(v)} style=${{ width: v + "%", background: [colors[1], colors[3], colors[4]][i] }}></i>`)}</div>
          <div class="legend"><span>${"<"} 5 kt ${pct(q.pct_lt5)}</span><span>5–15 kt ${pct(q.pct_5_15)}</span><span>≥ 15 kt ${pct(q.pct_15_20 + q.pct_ge20)}</span></div>
          <p class="small muted">${q.n} hours, ${meta.race_label}, no confidence intervals. Raw HRRR runs low against buoys (see Validation).</p>`}
      </div>
    </div>
    <div>
      <div id="map" ref=${mapEl}></div>
      <p class="small muted">Blue dots are HRRR water cells, brown are land. Cells inside the dashed box are averaged. Confirm the club position on this satellite view before trusting any result: the sample point is projected from it.</p>
    </div>
  </div>`;
}
