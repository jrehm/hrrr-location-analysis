import { useEffect, useState } from "preact/hooks";
import { api, post } from "./api.js";
import { Confirm, html } from "./components.js";

const when = (iso) => new Date(iso).toLocaleString([], { dateStyle: "medium", timeStyle: "short" });

/** Danger zone on a study's Inputs page: move the whole study to the trash (its name must be typed). */
export function TrashStudyCard({ meta, onTrashed }) {
  const [open, setOpen] = useState(false), [typed, setTyped] = useState(""), [busy, setBusy] = useState(false), [err, setErr] = useState(null);
  if (meta.readonly || meta.locked) return null;
  const go = async () => {
    setBusy(true); setErr(null);
    try { await post(`studies/${meta.id}/trash`, { name: typed }); await onTrashed(); } catch (e) { setErr(e.message); setBusy(false); }
  };
  return html`<div class="card"><h2>Delete this study</h2>
    <p class="small muted">Moves the whole study (its settings, downloaded wind data, buoy files and results) to the trash. Nothing is erased until the trash is emptied, and a trashed study can be restored.</p>
    ${!open ? html`<button class="danger" onClick=${() => setOpen(true)}>Move study to trash…</button>` : html`<div class="confirm">
      <div class="small">Type the study's name, <b>${meta.name}</b>, to confirm.</div>
      <input type="text" value=${typed} onInput=${(e) => setTyped(e.target.value)} aria-label="Study name" autocomplete="off" />
      ${err && html`<div class="err small">${err}</div>`}
      <div class="row"><button class="danger" disabled=${busy || typed !== meta.name} onClick=${go}>Move to trash</button>
        <button onClick=${() => { setOpen(false); setTyped(""); setErr(null); }}>Cancel</button></div></div>`}</div>`;
}

/** The trash: restore a study, or empty it for good (two confirmations, the second typed). */
export function TrashCard({ readonly, onChanged }) {
  const [items, setItems] = useState(null), [err, setErr] = useState(null), [busy, setBusy] = useState(false);
  const [step, setStep] = useState(0), [typed, setTyped] = useState("");
  const load = () => api("trash").then(setItems).catch(() => setItems([]));
  useEffect(() => { if (!readonly) load(); }, [readonly]);
  if (readonly || !items || !items.length) return null;
  const mb = items.reduce((a, i) => a + i.mb, 0).toFixed(1);
  const run = async (fn) => { setBusy(true); setErr(null); try { await fn(); await load(); await onChanged(); } catch (e) { setErr(e.message); } setBusy(false); };
  return html`<div class="card"><h2>Trash</h2>
    <p class="small muted">Studies moved to the trash, ${mb} MB in all. They no longer appear in the app. Restore one, or empty the trash to free the space.</p>
    ${items.map((i) => html`<div key=${i.entry} class="row" style="padding:6px 0;border-top:1px solid var(--line)">
      <span class="grow"><b>${i.name}</b> <span class="muted small">(${i.id}), ${i.mb} MB, trashed ${when(i.trashed)}</span></span>
      <button disabled=${busy} onClick=${() => run(() => post(`trash/${i.entry}/restore`))}>Restore</button></div>`)}
    ${err && html`<p class="err small">${err}</p>`}
    ${step === 0 && html`<p><button class="danger" onClick=${() => { setStep(1); setErr(null); }}>Empty trash…</button></p>`}
    ${step === 1 && html`<${Confirm} busy=${busy} err=${null} label="Continue" onNo=${() => setStep(0)} onYes=${() => setStep(2)}
      text=${`This permanently deletes ${items.length} trashed stud${items.length === 1 ? "y" : "ies"} (${mb} MB): ${items.map((i) => i.name).join(", ")}. Their downloaded data cannot be recovered, only downloaded again.`} />`}
    ${step === 2 && html`<div class="confirm"><div class="small"><b>Last check.</b> Type <b>empty trash</b> to delete everything in the trash for good.</div>
      <input type="text" value=${typed} onInput=${(e) => setTyped(e.target.value)} aria-label="Type empty trash" autocomplete="off" />
      <div class="row"><button class="danger" disabled=${busy || typed !== "empty trash"}
        onClick=${() => run(async () => { await post("trash/empty", { confirm: "empty trash" }); setStep(0); setTyped(""); })}>Delete permanently</button>
        <button onClick=${() => { setStep(0); setTyped(""); }}>Cancel</button></div></div>`}</div>`;
}
