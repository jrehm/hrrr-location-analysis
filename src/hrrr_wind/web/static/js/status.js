import { useEffect, useRef, useState } from "preact/hooks";
import { api, post } from "./api.js";
import { html } from "./components.js";
import { fmtMinutes as fmtTime } from "./util.js";


// What a study needs next, in words. Returns {tone, text, action} (action = button label or null).
export function describe(meta) {
  const st = meta.status, miss = `${st.missing_files.toLocaleString()} hourly files, ${fmtTime(st.missing_minutes)}`;
  switch (st.state) {
    case "no_data": return { tone: "warn", text: `No wind data yet. Download needed: ${miss}.`, action: "Download and analyze" };
    case "partial": return { tone: "warn", text: `Some data is missing: ${miss}.`, action: "Download the rest and analyze" };
    case "no_results": return { tone: "warn", text: "Wind data is on disk but not analyzed yet.", action: "Analyze" };
    case "stale": return { tone: "warn", text: "The study changed since the last analysis, so the results are out of date.", action: "Update results" };
    case "running": return { tone: "", text: "Working…", action: null };
    default: return { tone: "ok", text: "Up to date: data downloaded and results current.", action: null };
  }
}

function LogPanel({ log, onClose }) {
  return html`<div style="position:relative"><button title="Close log" aria-label="Close log" style="position:absolute;top:6px;right:14px;width:28px;height:28px;padding:0;line-height:1;font-size:20px;background:var(--fg);color:var(--panel);border-color:var(--fg)" onClick=${onClose}>×</button>
    <pre class="small" style="overflow:auto;max-height:240px;background:var(--wash);padding:8px;border-radius:6px">${log}</pre></div>`;
}

/** One line on every study page: the study's state, the single next action, and live progress. */
export function StatusStrip({ meta, onChanged }) {
  const [job, setJob] = useState(meta.status.job), [log, setLog] = useState(null), [err, setErr] = useState(null);
  const was = useRef(meta.status.state);
  useEffect(() => { setJob(meta.status.job); }, [meta.status.job?.id, meta.status.state]);
  const running = job && (job.status === "running" || job.status === "queued");
  useEffect(() => { // follow a running job, then refresh the study when it ends
    if (!running) return;
    const t = setInterval(async () => {
      try { const j = await api(`jobs/${job.id}`); setJob(j); if (j.status !== "running" && j.status !== "queued") { clearInterval(t); onChanged(); } }
      catch (e) { /* server restarting: keep trying */ }
    }, 1500);
    return () => clearInterval(t);
  }, [running, job?.id]);
  useEffect(() => { was.current = meta.status.state; }, [meta.status.state]);

  const d = describe(meta);
  const run = async () => {
    setErr(null);
    try { setJob(await post(`studies/${meta.id}/jobs`, { kind: "run_study", params: {} })); onChanged(); } catch (e) { setErr(e.message); }
  };
  const cancel = async () => { await post(`jobs/${job.id}/cancel`); onChanged(); };
  const showLog = async () => setLog(log === null ? (await api(`jobs/${job.id}/log`, { lines: 60 })).log : null);
  const failed = job && job.status === "failed" && !running;
  const canWrite = !meta.readonly;

  if (running) return html`<div class="strip"><div class="grow"><b>Working: ${job.message || "starting…"}</b>
      <div class="bar"><i style=${{ width: job.progress * 100 + "%", background: "var(--accent)" }}></i></div>
      <span class="small muted">${Math.round(job.progress * 100)}%. Safe to leave this page; an interrupted download resumes.</span></div>
    <button onClick=${cancel}>Cancel</button><button onClick=${showLog}>${log === null ? "Show log" : "Hide log"}</button></div>
    ${log !== null && html`<${LogPanel} log=${log} onClose=${() => setLog(null)} />`}`;
  return html`<div class=${"strip " + (failed ? "warn" : d.tone)}><div class="grow">
      ${failed ? html`<b>The last run failed:</b> <span class="small">${job.message}</span>` : d.text}
      ${err && html`<div class="err small">${err}</div>`}</div>
    ${canWrite && (d.action || failed) && html`<button class="primary" onClick=${run}>${failed ? "Try again (resumes)" : d.action}</button>`}
    ${job && html`<button onClick=${showLog}>${log === null ? "Show log" : "Hide log"}</button>`}</div>
    ${log !== null && html`<${LogPanel} log=${log} onClose=${() => setLog(null)} />`}`;
}
