// All data access goes through here: the UI only ever sees JSON from /api.
export async function api(path, params) {
  const qs = params ? "?" + new URLSearchParams(params) : "";
  const r = await fetch(`/api/${path}${qs}`);
  if (!r.ok) throw new Error(`${r.status} ${path}: ${(await r.text()).slice(0, 120)}`);
  return r.json();
}

// POST JSON; on an error response throws the server's "detail" message so the UI can show it.
export async function post(path, body) {
  const r = await fetch(`/api/${path}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body || {}) });
  if (!r.ok) {
    let detail = r.statusText;
    try { const j = await r.json(); detail = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail); } catch (e) { /* keep statusText */ }
    throw new Error(detail);
  }
  return r.json();
}
