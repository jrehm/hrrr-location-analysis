import { h } from "preact";
import { useEffect, useRef, useState } from "preact/hooks";
import htm from "htm";
import { cssVar } from "./util.js";

export const html = htm.bind(h);

// ``foot``: optional totals row, one cell per column.
// An (i) button that opens a small panel of explanatory text; closes on Esc, outside click or the button.
export function InfoPopup({ title, children }) {
  const [open, setOpen] = useState(false), box = useRef();
  useEffect(() => {
    if (!open) return;
    const key = (e) => e.key === "Escape" && setOpen(false);
    const away = (e) => box.current && !box.current.contains(e.target) && setOpen(false);
    addEventListener("keydown", key); addEventListener("mousedown", away);
    return () => { removeEventListener("keydown", key); removeEventListener("mousedown", away); };
  }, [open]);
  return html`<span class="info" ref=${box}>
    <button class="info-btn" aria-label=${title} aria-expanded=${open} title=${title} onClick=${() => setOpen(!open)}>i</button>
    ${open && html`<div class="info-panel" role="dialog" aria-label=${title}><b>${title}</b>${children}</div>`}</span>`;
}

export function Table({ cols, rows, caption, foot }) {
  return html`<div class="tablewrap"><table>
    ${caption && html`<caption class="small muted" style="text-align:left;padding-bottom:6px">${caption}</caption>`}
    <thead><tr>${cols.map((c) => html`<th class=${c.left ? "l" : ""}>${c.head}</th>`)}</tr></thead>
    <tbody>${rows.map((r) => html`<tr>${cols.map((c) => html`<td class=${c.left ? "l" : ""}>${c.cell(r)}</td>`)}</tr>`)}</tbody>
    ${foot && html`<tfoot><tr class="total">${cols.map((c, i) => html`<td class=${c.left ? "l" : ""}>${foot[i]}</td>`)}</tr></tfoot>`}
  </table></div>`;
}

export function Legend({ items }) {
  return html`<div class="legend">${items.map((it) =>
    html`<span><i style=${{ background: it.color }}></i>${it.label}</span>`)}</div>`;
}

// Stacked 16-sector wind rose (SVG). data = {sectors, bins, values[bin][sector] in % of hours}
const BIN_VARS = ["--r1", "--r2", "--r3", "--r4", "--r5"];
export const binColors = () => BIN_VARS.map(cssVar);

export function Rose({ data, maxPct }) {
  const C = 150, R = 118, gap = 2.5, half = 11.25 - gap;
  const totals = data.sectors.map((_, s) => data.values.reduce((a, b) => a + b[s], 0));
  const max = maxPct ?? Math.max(...totals);
  const step = max > 12 ? 4 : max > 6 ? 2 : 1;
  const top = Math.ceil(max / step) * step;
  const r = (v) => (v / top) * R;
  const pt = (rad, deg) => { const a = ((deg - 90) * Math.PI) / 180; return [C + rad * Math.cos(a), C + rad * Math.sin(a)]; };
  const wedge = (r0, r1, c) => {
    const [x0, y0] = pt(r1, c - half), [x1, y1] = pt(r1, c + half);
    const [x2, y2] = pt(r0, c + half), [x3, y3] = pt(r0, c - half);
    return `M${x0},${y0} A${r1},${r1} 0 0 1 ${x1},${y1} L${x2},${y2} A${r0},${r0} 0 0 0 ${x3},${y3} Z`;
  };
  const colors = binColors();
  const paths = [];
  data.sectors.forEach((name, s) => {
    let acc = 0;
    data.values.forEach((row, b) => {
      const v = row[s]; if (v <= 0) return;
      paths.push(html`<path d=${wedge(r(acc), r(acc + v), s * 22.5)} fill=${colors[b]}>
        <title>${name}, ${data.bins[b]} kt: ${v.toFixed(1)}% of hours</title></path>`);
      acc += v;
    });
  });
  const rings = [];
  for (let v = step; v <= top; v += step) rings.push(v);
  return html`<div>
    <svg class="rose" viewBox="0 0 300 300" role="img" aria-label="Wind rose" style="width:100%;max-width:340px;display:block;margin:auto">
      ${rings.map((v) => html`<circle cx=${C} cy=${C} r=${r(v)} fill="none" stroke=${cssVar("--line")} stroke-width="1"/>`)}
      ${paths}
      ${rings.map((v) => html`<text x=${C + 3} y=${C - r(v) + 10} style=${{ paintOrder: "stroke", stroke: cssVar("--panel"), strokeWidth: "3px" }}>${v}%</text>`)}
      ${[["N", 0], ["E", 90], ["S", 180], ["W", 270]].map(([t, d]) => {
        const [x, y] = pt(R + 14, d); return html`<text x=${x} y=${y + 4} text-anchor="middle" style="font-size:13px;font-weight:600">${t}</text>`; })}
    </svg>
    <${Legend} items=${data.bins.map((b, i) => ({ color: colors[i], label: `${b} kt` }))} />
  </div>`;
}

// Thin Chart.js wrapper: rebuilds the chart when `config` changes.
export function ChartCanvas({ config, height = 300 }) {
  const ref = useRef(), chart = useRef();
  useEffect(() => {
    chart.current?.destroy();
    chart.current = new Chart(ref.current, config);
    return () => chart.current?.destroy();
  }, [config]);
  return html`<div class="chartbox" style=${{ height: height + "px" }}><canvas ref=${ref}></canvas></div>`;
}

export function chartDefaults() {
  const fg = cssVar("--muted"), line = cssVar("--line");
  return {
    maintainAspectRatio: false,
    plugins: { legend: { labels: { color: fg, boxWidth: 12, usePointStyle: true } } },
    scales: { x: { ticks: { color: fg }, grid: { color: line } }, y: { ticks: { color: fg }, grid: { color: line } } },
  };
}

// A red-button confirmation box shown in place; text says exactly what will happen.
export function Confirm({ text, label: go, onYes, onNo, busy, err }) {
  return html`<div class="confirm"><div class="small">${text}</div>${err && html`<div class="err small">${err}</div>`}
    <div class="row"><button class="danger" disabled=${busy} onClick=${onYes}>${go}</button><button onClick=${onNo}>Cancel</button></div></div>`;
}
