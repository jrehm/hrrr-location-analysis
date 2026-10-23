export const fmt = (x, d = 1) => (x == null || Number.isNaN(x) ? "–" : Number(x).toFixed(d));
export const pct = (x, d = 0) => (x == null ? "–" : `${Number(x).toFixed(d)}%`);
export const range = (lo, hi, d = 1) => `${fmt(lo, d)}–${fmt(hi, d)}`;
export const label = (venue, season) =>
  `${venue.toUpperCase()} ${({ sep: "Sept", jun: "June" })[season] || season}`;
// Nine distinct series colors (one per window; a study has at most 9) and marker shapes as a second cue.
export const SERIES_VARS = ["--s1", "--s2", "--s3", "--s4", "--s5", "--s6", "--s7", "--s8", "--s9"];
export const SERIES_POINTS = ["circle", "rect", "triangle", "rectRot", "star", "cross", "crossRot", "rectRounded", "circle"];
export const cssVar = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
export const seriesColor = (i) => cssVar(SERIES_VARS[i % SERIES_VARS.length]);
export const seriesPoint = (i) => SERIES_POINTS[i % SERIES_POINTS.length];
export const debounce = (fn, ms) => {
  let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); };
};
// [2015, 2016, 2018] -> "2015–2016, 2018"
export const yearRanges = (ys) => {
  const out = []; let i = 0; const a = [...ys].sort((x, y) => x - y);
  while (i < a.length) { let j = i; while (j + 1 < a.length && a[j + 1] === a[j] + 1) j++; out.push(j > i ? `${a[i]}–${a[j]}` : `${a[i]}`); i = j + 1; }
  return out.join(", ");
};
export const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
export const fmtMinutes = (m) => (m < 1.5 ? "about a minute" : m < 90 ? `about ${Math.round(m)} min` : `about ${(m / 60).toFixed(1)} h`);
