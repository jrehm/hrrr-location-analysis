export const fmt = (x, d = 1) => (x == null || Number.isNaN(x) ? "–" : Number(x).toFixed(d));
export const pct = (x, d = 0) => (x == null ? "–" : `${Number(x).toFixed(d)}%`);
export const range = (lo, hi, d = 1) => `${fmt(lo, d)}–${fmt(hi, d)}`;
export const label = (venue, season) =>
  `${venue.toUpperCase()} ${({ sep: "Sept", jun: "June" })[season] || season}`;
export const SERIES_VARS = ["--s-gtyc", "--s-hyc", "--s-hyc-jun"];
export const cssVar = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
export const seriesColor = (i) => cssVar(SERIES_VARS[i % SERIES_VARS.length]);
export const debounce = (fn, ms) => {
  let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); };
};
