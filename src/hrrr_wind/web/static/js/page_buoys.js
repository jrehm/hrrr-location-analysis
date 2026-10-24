import { useEffect, useRef, useState } from "preact/hooks";
import { api, post } from "./api.js";
import { html } from "./components.js";
import { fmtMinutes } from "./util.js";
import { yearsSummary } from "./years.js";

const TILE = ["https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}", "Imagery © Esri"];
const COMPASS = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE", "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"];
const spanOf = (ys) => (ys.length ? `${ys[0]}${ys.length > 1 ? `–${ys[ys.length - 1]}` : ""}${ys.length > ys[ys.length - 1] - ys[0] + 1 ? " (gaps)" : ""}` : "none");
const compass = (deg) => COMPASS[Math.round(deg / 22.5) % 16];

// Satellite map: the venue (white) and the stations around it; a click on a station selects it.
function StationMap({ venue, stations, sel, onSel }) {
  const el = useRef(), map = useRef(), layer = useRef(), pick = useRef(onSel);
  pick.current = onSel;
  useEffect(() => {
    map.current = L.map(el.current, { zoomSnap: 0.25 }).setView([venue.lat, venue.lon], 9);
    L.tileLayer(TILE[0], { attribution: TILE[1], maxZoom: 18 }).addTo(map.current);
    layer.current = L.layerGroup().addTo(map.current);
    return () => map.current.remove();
  }, []);
  useEffect(() => {
    const g = layer.current; g.clearLayers();
    L.circleMarker([venue.lat, venue.lon], { radius: 7, color: "#111", weight: 2, fillColor: "#fff", fillOpacity: 1 }).bindTooltip(venue.name).addTo(g);
    stations.forEach((s) => L.circleMarker([s.lat, s.lon], { radius: s.id === sel ? 9 : 6, weight: 2, color: "#fff",
      fillColor: s.id === sel ? "#e5484d" : "#2f7fd0", fillOpacity: 1 }).bindTooltip(`${s.id} ${s.name}`).on("click", () => pick.current(s.id)).addTo(g));
    if (stations.length) map.current.fitBounds(L.latLngBounds([[venue.lat, venue.lon], ...stations.map((s) => [s.lat, s.lon])]), { padding: [30, 30], maxZoom: 11 });
  }, [stations, sel]);
  return html`<div id="map" ref=${el}></div>`;
}

/** Pick a buoy for one venue and start the download + validation job. */
export function BuoySetup({ meta, venue, onStarted, onCancel }) {
  const [list, setList] = useState(null), [err, setErr] = useState(null), [sel, setSel] = useState(null);
  const [anem, setAnem] = useState(""), [busy, setBusy] = useState(false), [radius, setRadius] = useState(60);
  useEffect(() => {
    setErr(null);
    api(`studies/${meta.id}/venues/${venue}/buoys`, { radius_nm: radius }).then((l) => { setList(l); setSel((cur) => (l.stations.some((x) => x.id === cur && x.years.length) ? cur : null)); })
      .catch((e) => setErr(e.message));
  }, [meta.id, venue, radius]);
  const [anemSrc, setAnemSrc] = useState(null);   // where the height came from: page | known | default
  const pick = (id) => {
    const st = list.stations.find((x) => x.id === id);
    if (!st.years.length) return;
    setSel(id); setAnem(""); setAnemSrc(null);
    api(`ndbc/${id}/anemometer`).then((a) => { setAnem((cur) => cur || String(a.anem_m)); setAnemSrc(a.source); }).catch(() => { setAnem((cur) => cur || String(st.anem_m)); setAnemSrc("default"); });
  };
  const s = list && sel && list.stations.find((x) => x.id === sel);
  const start = async () => {
    setBusy(true); setErr(null);
    try { await post(`studies/${meta.id}/buoys`, { venue, id: sel, anem_m: Number(anem) }); onStarted(); }
    catch (e) { setErr(e.message); setBusy(false); }
  };
  if (err && !list) return html`<p class="err">${err}${/^404 /.test(err) ? " (the server may be running an older version: restart it)" : ""}</p>`;
  if (!list) return html`<p class="muted">Looking up NDBC stations…</p>`;
  const usable = list.stations.filter((x) => x.years.length).length;
  const widen = html`<label class="small">Search radius <select value=${radius} onChange=${(e) => { setRadius(Number(e.target.value)); }} style="width:auto">
    ${[30, 60, 100, 150].map((r) => html`<option value=${r}>${r} nm</option>`)}</select></label>`;
  return html`<div class="grid">
    <div class="row">${widen}${err && html`<span class="err small">${err}</span>`}</div>
    ${list.stations.length === 0 ? html`<p class="note">No NDBC station that reports wind lies within ${radius} nm of ${list.venue.name}.${radius < 150 ? " Try a wider search radius." : " Validation is not possible for this venue."}</p>` : html`
    <p class="small muted">${list.stations.length} NDBC station${list.stations.length === 1 ? "" : "s"} within ${radius} nm of ${list.venue.name} that report wind${usable < list.stations.length ? `; ${usable} archived observations in this study's years (the rest are greyed out)` : ""}. Click one on the map or in the list.</p>
    ${usable === 0 && radius < 150 && html`<p class="note">None of them has archived data for the study's years. Try a wider search radius.</p>`}
    <${StationMap} venue=${list.venue} stations=${list.stations} sel=${sel} onSel=${pick} />
    <div class="tablewrap"><table><thead><tr><th></th><th style="text-align:left">Station</th><th>Distance</th><th style="text-align:left">Type</th><th style="text-align:left">Observations in study years</th><th style="text-align:left">HRRR data</th></tr></thead>
      <tbody>${list.stations.map((x) => html`<tr key=${x.id} onClick=${() => pick(x.id)} style=${{ cursor: x.years.length ? "pointer" : "default", opacity: x.years.length ? 1 : 0.5, background: x.id === sel ? "var(--wash)" : "" }}>
        <td><input type="radio" name="buoy" disabled=${!x.years.length} checked=${x.id === sel} onChange=${() => pick(x.id)} aria-label=${"Choose " + x.id} /></td>
        <td style="text-align:left"><b>${x.id}</b> ${x.name}</td><td>${x.distance_nm} nm ${compass(x.bearing)}</td><td style="text-align:left">${x.type}</td><td style="text-align:left">${spanOf(x.years)}</td>
        <td style="text-align:left">${x.covered ? "already covered" : `extra download, ${x.extra_files.toLocaleString()} files (${fmtMinutes(x.extra_minutes)})`}</td></tr>`)}</tbody></table></div>`}
    ${s && html`<div class="card"><h3 style="margin-top:0">Buoy ${s.id}: ${s.name}</h3>
      <label class="f" style="max-width:260px">Anemometer height (m)
        <input type="number" min="0.5" max="100" step="0.1" value=${anem} placeholder=${anemSrc ? "" : "looking up…"} onInput=${(e) => { setAnem(e.target.value); setAnemSrc("edited"); }} /></label>
      <p class="small muted">${anemSrc === "page" ? html`Read from the station's NDBC page (<a href=${`https://www.ndbc.noaa.gov/station_page.php?station=${s.id}`} target="_blank" rel="noopener">${s.id}</a>).`
        : anemSrc === "known" ? "NDBC's page could not be read; this is the height recorded for this buoy earlier."
        : anemSrc === "default" ? html`NDBC's page lists no anemometer height; ${anem} m is a typical default, so please check the <a href=${`https://www.ndbc.noaa.gov/station_page.php?station=${s.id}`} target="_blank" rel="noopener">station page</a>.`
        : anemSrc === "edited" ? "Entered by hand." : ""} The height scales the buoy's winds to 10 m.</p>
      ${s.distance_nm > 25 && html`<p class="note">This buoy is ${s.distance_nm} nm from the venue, so its winds may differ from the shore. Treat the bias-adjusted range as an upper bound.</p>`}
      <p class="small">Downloads the buoy's observations for ${yearsSummary(meta)} (years NDBC has not archived are skipped)${s.covered ? "" : `, then HRRR winds around the buoy for the study's windows (about ${s.extra_files.toLocaleString()} hourly files, ${fmtMinutes(s.extra_minutes)})`}, then runs the validation. Safe to leave the page.</p>
      ${err && html`<p class="err small">${err}</p>`}
      <div class="row"><button class="primary" disabled=${busy || !(Number(anem) > 0)} onClick=${start}>Download and validate</button>
        ${onCancel && html`<button onClick=${onCancel}>Cancel</button>`}</div></div>`}
    ${!s && onCancel && html`<div><button onClick=${onCancel}>Cancel</button></div>`}</div>`;
}
