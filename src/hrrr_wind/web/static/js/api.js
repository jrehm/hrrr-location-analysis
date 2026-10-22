// All data access goes through here: the UI only ever sees JSON from /api.
export async function api(path, params) {
  const qs = params ? "?" + new URLSearchParams(params) : "";
  const r = await fetch(`/api/${path}${qs}`);
  if (!r.ok) throw new Error(`${r.status} ${path}: ${(await r.text()).slice(0, 120)}`);
  return r.json();
}
