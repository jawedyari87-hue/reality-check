// Small dependency-free SVG charts: line (with crosshair tooltip), sparkline,
// range dots and dumbbells. Labels always go in via textContent.

const SVG = "http://www.w3.org/2000/svg";
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

export function el(tag, attrs = {}, ...kids) {
  const svg = ["svg", "g", "path", "line", "rect", "circle", "text", "title", "polyline", "defs", "clipPath"].includes(tag);
  const node = svg ? document.createElementNS(SVG, tag) : document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "class") node.setAttribute("class", v);
    else if (k === "text") node.textContent = v;
    else if (k === "style" && typeof v === "object") Object.assign(node.style, v);
    else if (k.startsWith("on") && typeof v === "function") node.addEventListener(k.slice(2), v);
    else node.setAttribute(k, v === true ? "" : v);
  }
  for (const kid of kids.flat()) {
    if (kid === null || kid === undefined || kid === false) continue;
    node.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
  }
  return node;
}

export const toMs = (iso) => Date.UTC(+iso.slice(0, 4), +(iso.slice(5, 7) || 1) - 1, +(iso.slice(8, 10) || 1));

export function fmtDate(ms, step) {
  const d = new Date(ms);
  if (step === "year") return String(d.getUTCFullYear());
  if (step === "week") return `${d.getUTCDate()} ${MONTHS[d.getUTCMonth()]} ${d.getUTCFullYear()}`;
  return `${MONTHS[d.getUTCMonth()]} ${d.getUTCFullYear()}`;
}

export function niceTicks(min, max, count = 5) {
  if (!isFinite(min) || !isFinite(max)) return [0, 1];
  if (min === max) { const pad = Math.abs(min) * 0.1 || 1; min -= pad; max += pad; }
  const span = max - min;
  const raw = span / Math.max(1, count);
  const mag = Math.pow(10, Math.floor(Math.log10(raw)));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => span / s <= count) || 10 * mag;
  const lo = Math.floor(min / step) * step;
  const hi = Math.ceil(max / step) * step;
  const out = [];
  for (let v = lo; v <= hi + step / 2; v += step) out.push(+v.toFixed(10));
  return out;
}

function timeTicks(x0, x1, width) {
  const years = (x1 - x0) / (365.25 * 864e5);
  const maxTicks = Math.max(2, Math.floor(width / 72));
  if (years > 2.5) {
    const stepY = [1, 2, 5, 10, 20].find((s) => years / s <= maxTicks) || 25;
    const y0 = new Date(x0).getUTCFullYear(), y1 = new Date(x1).getUTCFullYear();
    const out = [];
    for (let y = Math.ceil(y0 / stepY) * stepY; y <= y1; y += stepY) {
      const t = Date.UTC(y, 0, 1);
      if (t >= x0 && t <= x1) out.push({ t, label: String(y) });
    }
    return out;
  }
  const months = years * 12;
  const stepM = [1, 2, 3, 6, 12].find((s) => months / s <= maxTicks) || 12;
  const d = new Date(x0);
  let y = d.getUTCFullYear(), m = d.getUTCMonth() + 1;
  const out = [];
  for (let i = 0; i < 200; i++) {
    if (m > 11) { y += Math.floor(m / 12); m %= 12; }
    const t = Date.UTC(y, m, 1);
    if (t > x1) break;
    if (m % stepM === 0 && t >= x0) out.push({ t, label: m === 0 ? String(y) : `${MONTHS[m]} ${String(y).slice(2)}` });
    m += 1;
  }
  return out;
}

function nearestIndex(pts, x) {
  let lo = 0, hi = pts.length - 1;
  if (hi < 0) return -1;
  while (hi - lo > 1) {
    const mid = (lo + hi) >> 1;
    if (pts[mid][0] < x) lo = mid; else hi = mid;
  }
  return Math.abs(pts[lo][0] - x) <= Math.abs(pts[hi][0] - x) ? lo : hi;
}

function stepKind(pts, isYear) {
  if (isYear) return "year";
  if (pts.length < 3) return "month";
  const gap = (pts[pts.length - 1][0] - pts[pts.length - 2][0]) / 864e5;
  return gap <= 8 ? "week" : gap >= 300 ? "year" : "month";
}

/**
 * lineChart(container, opts) - opts:
 *  series: [{id, name, color, points: [[x, y]], width, opacity, ghost, noTip, dash, dots}]
 *  x: "date" (ISO strings) | "year" (numbers)
 *  height, yFormat(v), yDomain [lo, hi], zero (include 0)
 *  bands [{from, to, label}], hlines [{value, label}], vlines [{x, label}]
 *  legend [{name, color, kind: line|dot|ghost}] (defaults to non-ghost series when >= 2)
 *  tip(xValue, rows) -> override rows; label: aria-label
 */
export function lineChart(container, opts) {
  container.replaceChildren();
  container.classList.add("chart");
  const isYear = opts.x === "year";
  const conv = (v) => (isYear ? +v : typeof v === "number" ? v : toMs(v));
  const series = opts.series.map((s) => ({
    ...s, pts: s.points.map((p) => [conv(p[0]), p[1]]).filter((p) => p[1] !== null && isFinite(p[1])).sort((a, b) => a[0] - b[0]),
  })).filter((s) => s.pts.length);
  const fmt = opts.yFormat || ((v) => (Math.abs(v) >= 1000 ? Math.round(v).toLocaleString("en-GB") : +v.toFixed(2) + ""));

  const legendItems = opts.legend || (series.filter((s) => !s.ghost).length >= 2
    ? series.filter((s) => !s.ghost).map((s) => ({ name: s.name, color: s.color, kind: s.dash ? "dash" : "line" }))
    : []);
  if (legendItems.length) {
    container.append(el("div", { class: "legend" }, legendItems.map((l) => el("span", {},
      el("i", { class: "key" + (l.kind === "dot" ? " dot" : ""), style: {
        background: l.kind === "dash" ? `repeating-linear-gradient(90deg, ${l.color} 0 4px, transparent 4px 7px)` : l.color,
        opacity: l.kind === "ghost" ? 0.5 : 1 } }), l.name))));
  }
  const holder = el("div", { style: { position: "relative" } });
  container.append(holder);
  if (!series.length) {
    holder.append(el("div", { class: "empty", text: opts.emptyText || "No data yet." }));
    return;
  }

  const draw = () => {
    holder.replaceChildren();
    const W = Math.max(280, holder.clientWidth || container.clientWidth || 640);
    const H = opts.height || 260;
    let x0 = Infinity, x1 = -Infinity, y0 = Infinity, y1 = -Infinity;
    for (const s of series) {
      for (const [x, y] of s.pts) {
        if (x < x0) x0 = x; if (x > x1) x1 = x; if (y < y0) y0 = y; if (y > y1) y1 = y;
      }
      for (const p of s.area || []) {  // shaded ranges must fit too
        if (p[1] !== null && p[1] < y0) y0 = p[1];
        if (p[2] !== null && p[2] > y1) y1 = p[2];
      }
    }
    if (opts.xDomain) { x0 = conv(opts.xDomain[0]); x1 = conv(opts.xDomain[1]); }
    for (const h of opts.hlines || []) { y0 = Math.min(y0, h.value); y1 = Math.max(y1, h.value); }
    for (const b of opts.bands || []) { if (b.to !== undefined) x1 = Math.max(x1, conv(b.to)); }
    if (opts.zero) { y0 = Math.min(0, y0); y1 = Math.max(0, y1); }
    if (opts.yDomain) { [y0, y1] = opts.yDomain; }
    if (x0 === x1) { x0 -= isYear ? 1 : 864e5 * 30; x1 += isYear ? 1 : 864e5 * 30; }
    const yt = niceTicks(y0, y1, H < 200 ? 4 : 5);
    const labelW = Math.max(...yt.map((t) => fmt(t).length)) * 6.6 + 12;
    const m = { l: Math.max(34, labelW), r: 14, t: 10, b: 26 };
    const iw = W - m.l - m.r, ih = H - m.t - m.b;
    const yLo = yt[0], yHi = yt[yt.length - 1];
    const sx = (x) => m.l + ((x - x0) / (x1 - x0)) * iw;
    const sy = (y) => m.t + ih - ((y - yLo) / (yHi - yLo || 1)) * ih;

    const svg = el("svg", { viewBox: `0 0 ${W} ${H}`, height: H, role: "img", tabindex: 0,
      "aria-label": opts.label || series.map((s) => s.name).join(", ") });
    const axis = el("g", { class: "axis" });
    for (const t of yt) {
      axis.append(el("line", { class: "grid-line", x1: m.l, x2: W - m.r, y1: sy(t), y2: sy(t) }));
      axis.append(el("text", { x: m.l - 8, y: sy(t) + 4, "text-anchor": "end", text: fmt(t) }));
    }
    const xt = isYear
      ? niceTicks(x0, x1, Math.max(2, Math.floor(iw / 60))).filter((t) => t >= x0 && t <= x1 && Number.isInteger(t)).map((t) => ({ t, label: String(t) }))
      : timeTicks(x0, x1, iw);
    for (const t of xt) axis.append(el("text", { x: sx(t.t), y: H - 6, "text-anchor": "middle", text: t.label }));
    axis.append(el("line", { class: "base-line", x1: m.l, x2: W - m.r, y1: m.t + ih, y2: m.t + ih }));
    svg.append(axis);

    for (const b of opts.bands || []) {
      const a = sx(Math.max(x0, conv(b.from))), z = sx(Math.min(x1, b.to === undefined ? x1 : conv(b.to)));
      if (z > a) {
        svg.append(el("rect", { class: "band", x: a, y: m.t, width: z - a, height: ih }));
        if (b.label) svg.append(el("text", { class: "band-label", x: a + 6, y: m.t + 13, text: b.label }));
      }
    }
    for (const v of opts.vlines || []) {
      const x = sx(conv(v.x));
      if (x < m.l || x > W - m.r) continue;
      svg.append(el("line", { class: "ref-line", x1: x, x2: x, y1: m.t, y2: m.t + ih }));
      if (v.label) svg.append(el("text", { class: "ref-label", x: x + 5, y: m.t + ih - 6, text: v.label }));
    }
    for (const h of opts.hlines || []) {
      const y = sy(h.value);
      svg.append(el("line", { class: "ref-line", x1: m.l, x2: W - m.r, y1: y, y2: y }));
      // Label above the line, or below it when the line hugs the top edge.
      if (h.label) svg.append(el("text", { class: "ref-label", x: W - m.r - 4, y: y - m.t < 16 ? y + 14 : y - 5, "text-anchor": "end", text: h.label }));
    }

    const clip = `clip${Math.random().toString(36).slice(2)}`;
    svg.append(el("defs", {}, el("clipPath", { id: clip }, el("rect", { x: m.l, y: m.t - 6, width: iw, height: ih + 12 }))));
    const lines = el("g", { "clip-path": `url(#${clip})` });
    const ordered = [...series].sort((a, b) => (b.ghost ? 1 : 0) - (a.ghost ? 1 : 0));
    for (const s of ordered) {
      if (s.area) {
        const up = s.area.map((p) => [conv(p[0]), p[1], p[2]]).sort((a, b) => a[0] - b[0]);
        const d = up.map((p, i) => `${i ? "L" : "M"}${sx(p[0]).toFixed(1)},${sy(p[2]).toFixed(1)}`).join("")
          + [...up].reverse().map((p) => `L${sx(p[0]).toFixed(1)},${sy(p[1]).toFixed(1)}`).join("") + "Z";
        lines.append(el("path", { d, fill: s.color, opacity: 0.1 }));
      }
      const d = s.pts.map((p, i) => `${i ? "L" : "M"}${sx(p[0]).toFixed(1)},${sy(p[1]).toFixed(1)}`).join("");
      lines.append(el("path", { d, fill: "none", stroke: s.ghost ? "var(--ghost)" : s.color,
        "stroke-width": s.width || 2, "stroke-linejoin": "round", "stroke-linecap": "round",
        opacity: s.ghost ? (s.opacity ?? 0.35) : (s.opacity ?? 1), "stroke-dasharray": s.dash || null }));
      if (s.dots) for (const p of s.pts) lines.append(el("circle", { cx: sx(p[0]), cy: sy(p[1]), r: 3.5, fill: s.color, stroke: "var(--surface)", "stroke-width": 2 }));
    }
    svg.append(lines);
    for (const s of series) {
      if (s.ghost || s.noEnd) continue;
      const p = s.pts[s.pts.length - 1];
      if (p[0] < x0 || p[0] > x1) continue;
      svg.append(el("circle", { cx: sx(p[0]), cy: sy(p[1]), r: 4, fill: s.color, stroke: "var(--surface)", "stroke-width": 2 }));
    }

    // Hover layer: crosshair snaps to the nearest date; the tooltip lists every series there.
    const cross = el("line", { class: "crosshair", y1: m.t, y2: m.t + ih, visibility: "hidden" });
    const hoverDots = el("g", {});
    svg.append(cross, hoverDots);
    const tip = el("div", { class: "tooltip hidden" });
    holder.append(svg, tip);

    const tipSeries = series.filter((s) => !s.noTip);
    const base = [...tipSeries].sort((a, b) => b.pts.length - a.pts.length)[0] || series[0];
    const kind = stepKind(base.pts, isYear);
    const tol = base.pts.length > 1 ? ((base.pts[base.pts.length - 1][0] - base.pts[0][0]) / (base.pts.length - 1)) * 1.5 : Infinity;
    let cursor = base.pts.length - 1;

    const show = (xVal) => {
      let snap = null, best = Infinity;
      for (const s of tipSeries) {
        const i = nearestIndex(s.pts, xVal);
        if (i < 0) continue;
        const dist = Math.abs(s.pts[i][0] - xVal);
        if (dist < best) { best = dist; snap = s.pts[i][0]; }
      }
      if (snap === null) return;
      let rows = [];
      hoverDots.replaceChildren();
      for (const s of tipSeries) {
        const i = nearestIndex(s.pts, snap);
        if (i < 0 || Math.abs(s.pts[i][0] - snap) > tol) continue;
        const p = s.pts[i];
        rows.push({ color: s.ghost ? "var(--ghost)" : s.color, value: fmt(p[1]), name: s.name, raw: p[1] });
        if (!s.ghost) hoverDots.append(el("circle", { cx: sx(p[0]), cy: sy(p[1]), r: 4, fill: s.color, stroke: "var(--surface)", "stroke-width": 2 }));
      }
      if (opts.tip) rows = opts.tip(snap, rows) || rows;
      cross.setAttribute("x1", sx(snap)); cross.setAttribute("x2", sx(snap)); cross.setAttribute("visibility", "visible");
      tip.replaceChildren(el("div", { class: "t-date", text: opts.tipTitle ? opts.tipTitle(snap) : fmtDate(isYear ? Date.UTC(snap, 0, 1) : snap, kind) }),
        ...rows.slice(0, 12).map((r) => el("div", { class: "t-row" },
          el("i", { class: "key", style: { background: r.color } }), el("b", { text: r.value }), el("span", { text: r.name || "" }))));
      tip.classList.remove("hidden");
      const px = sx(snap), tw = tip.offsetWidth || 170;
      tip.style.left = `${px + 14 + tw > W ? Math.max(0, px - tw - 14) : px + 14}px`;
      tip.style.top = `${m.t + 4}px`;
    };
    const hide = () => { cross.setAttribute("visibility", "hidden"); tip.classList.add("hidden"); hoverDots.replaceChildren(); };
    svg.addEventListener("pointermove", (ev) => {
      const r = svg.getBoundingClientRect();
      const px = ((ev.clientX - r.left) / r.width) * W;
      show(x0 + ((px - m.l) / iw) * (x1 - x0));
    });
    svg.addEventListener("pointerleave", hide);
    svg.addEventListener("blur", hide);
    svg.addEventListener("keydown", (ev) => {
      if (ev.key !== "ArrowLeft" && ev.key !== "ArrowRight") return;
      ev.preventDefault();
      cursor = Math.max(0, Math.min(base.pts.length - 1, cursor + (ev.key === "ArrowRight" ? 1 : -1)));
      show(base.pts[cursor][0]);
    });
    svg.addEventListener("focus", () => show(base.pts[cursor][0]));
  };
  draw();
  redrawOnResize(holder, draw);
}

// Redraw when the width really changes. A chart inside a hidden tab reports
// zero width; skip that, and the chart redraws once the tab is shown.
function redrawOnResize(holder, draw) {
  let lastW = holder.clientWidth;
  new ResizeObserver(() => {
    const w = holder.clientWidth;
    if (w === 0 || Math.abs(w - lastW) <= 4) return;
    lastW = w;
    draw();
  }).observe(holder);
}

/** The table twin of a line chart: every value, newest first. */
export function tableView(container, series, { x = "date", fmt = (v) => v, limit = 400, kind } = {}) {
  container.replaceChildren();
  const isYear = x === "year";
  const keys = new Map();
  for (const s of series) for (const [d, v] of s.points) {
    const k = isYear ? +d : d;
    if (!keys.has(k)) keys.set(k, {});
    keys.get(k)[s.name] = v;
  }
  const rows = [...keys.entries()].sort((a, b) => (a[0] < b[0] ? 1 : -1)).slice(0, limit);
  const k0 = kind || (isYear ? "year" : "month");
  const table = el("table", { class: "data" },
    el("thead", {}, el("tr", {}, el("th", { text: isYear ? "Year" : "Date" }), series.map((s) => el("th", { text: s.name })))),
    el("tbody", {}, rows.map(([k, vals]) => el("tr", {},
      el("td", { text: isYear ? String(k) : fmtDate(toMs(k), k0) }),
      series.map((s) => el("td", { text: vals[s.name] === undefined || vals[s.name] === null ? "–" : fmt(vals[s.name]) }))))));
  container.append(el("div", { class: "table-wrap" }, table));
}

export function sparkline(container, points, { color = "var(--s1)" } = {}) {
  container.replaceChildren();
  if (!points || points.length < 2) return;
  const W = 240, H = 34;
  const xs = points.map((p) => toMs(p[0])), ys = points.map((p) => p[1]);
  const x0 = Math.min(...xs), x1 = Math.max(...xs), y0 = Math.min(...ys), y1 = Math.max(...ys);
  const sx = (x) => 2 + ((x - x0) / (x1 - x0 || 1)) * (W - 8);
  const sy = (y) => 4 + (H - 8) - ((y - y0) / (y1 - y0 || 1)) * (H - 8);
  const d = points.map((p, i) => `${i ? "L" : "M"}${sx(xs[i]).toFixed(1)},${sy(p[1]).toFixed(1)}`).join("");
  const last = points.length - 1;
  container.append(el("svg", { viewBox: `0 0 ${W} ${H}`, preserveAspectRatio: "none", height: H, width: "100%", "aria-hidden": "true" },
    el("path", { d, fill: "none", stroke: "var(--ghost)", "stroke-width": 1.5, opacity: 0.8, "vector-effect": "non-scaling-stroke" }),
    el("circle", { cx: sx(xs[last]), cy: sy(ys[last]), r: 3.5, fill: color, stroke: "var(--surface)", "stroke-width": 1.5 })));
}

/**
 * Horizontal dot chart. rows: [{label, marks: [{name, color, value, lo, hi, lo2, hi2}]}]
 * lo/hi draw a thin range (e.g. p10-p90), lo2/hi2 a thicker one (p25-p75).
 * connect: draw a line between the first two marks (dumbbell).
 */
export function dotChart(container, rows, { fmt = (v) => v, connect = false, legend = [], label = "" } = {}) {
  container.replaceChildren();
  container.classList.add("chart");
  if (legend.length) container.append(el("div", { class: "legend" }, legend.map((l) => el("span", {},
    el("i", { class: "key dot", style: { background: l.color } }), l.name))));
  const holder = el("div", { style: { position: "relative" } });
  container.append(holder);
  const draw = () => {
    holder.replaceChildren();
    const W = Math.max(300, holder.clientWidth || 640);
    const narrow = W < 560;
    const labelW = narrow ? 0 : Math.min(260, Math.max(...rows.map((r) => r.label.length)) * 6.8 + 12);
    const perMark = connect ? 0 : 16;
    const rowH = (r) => (narrow ? 18 : 0) + Math.max(26, (connect ? 1 : r.marks.length) * perMark + 12);
    const H = rows.reduce((a, r) => a + rowH(r), 0) + 30;
    let vals = [];
    for (const r of rows) for (const mk of r.marks) vals.push(mk.value, mk.lo, mk.hi);
    vals = vals.filter((v) => v !== null && v !== undefined && isFinite(v));
    const ticks = niceTicks(Math.min(0, ...vals), Math.max(...vals), Math.max(3, Math.floor((W - labelW) / 110)));
    const m = { l: labelW + 8, r: 16, t: 6 };
    const iw = W - m.l - m.r;
    const sx = (v) => m.l + ((v - ticks[0]) / (ticks[ticks.length - 1] - ticks[0])) * iw;
    const svg = el("svg", { viewBox: `0 0 ${W} ${H}`, height: H, role: "img", "aria-label": label });
    const axis = el("g", { class: "axis" });
    for (const t of ticks) {
      axis.append(el("line", { class: "grid-line", x1: sx(t), x2: sx(t), y1: m.t, y2: H - 22 }));
      axis.append(el("text", { x: sx(t), y: H - 6, "text-anchor": "middle", text: fmt(t) }));
    }
    svg.append(axis);
    const tip = el("div", { class: "tooltip hidden" });
    let y = m.t;
    for (const r of rows) {
      const h = rowH(r);
      const g = el("g", { tabindex: 0, role: "listitem" });
      const top = y + (narrow ? 16 : 0);
      if (narrow) g.append(el("text", { x: m.l, y: y + 12, class: "ref-label", text: r.label }));
      else g.append(el("text", { x: labelW, y: top + (h - (narrow ? 18 : 0)) / 2 + 4, "text-anchor": "end", class: "ref-label", text: r.label }));
      const cy0 = top + (h - (narrow ? 18 : 0)) / 2;
      const present = r.marks.filter((mk) => mk.value !== null && mk.value !== undefined);
      if (connect && present.length === 2) {
        g.append(el("line", { x1: sx(present[0].value), x2: sx(present[1].value), y1: cy0, y2: cy0, stroke: "var(--axis)", "stroke-width": 2 }));
      }
      r.marks.forEach((mk, i) => {
        if (mk.value === null || mk.value === undefined) return;
        const cy = connect ? cy0 : cy0 + (i - (r.marks.length - 1) / 2) * perMark;
        if (mk.lo !== undefined && mk.hi !== undefined && mk.lo !== null && mk.hi !== null) {
          g.append(el("line", { x1: sx(mk.lo), x2: sx(mk.hi), y1: cy, y2: cy, stroke: mk.color, "stroke-width": 2, opacity: 0.45, "stroke-linecap": "round" }));
        }
        if (mk.lo2 !== undefined && mk.hi2 !== undefined && mk.lo2 !== null && mk.hi2 !== null) {
          g.append(el("line", { x1: sx(mk.lo2), x2: sx(mk.hi2), y1: cy, y2: cy, stroke: mk.color, "stroke-width": 6, opacity: 0.35, "stroke-linecap": "round" }));
        }
        g.append(el("circle", { cx: sx(mk.value), cy, r: 5, fill: mk.color, stroke: "var(--surface)", "stroke-width": 2 }));
      });
      g.append(el("rect", { x: 0, y, width: W, height: h, fill: "transparent" }));
      const showTip = () => {
        tip.replaceChildren(el("div", { class: "t-date", text: r.label }),
          ...r.marks.filter((mk) => mk.value !== null && mk.value !== undefined).map((mk) => el("div", { class: "t-row" },
            el("i", { class: "key dot", style: { background: mk.color } }), el("b", { text: fmt(mk.value) }),
            el("span", { text: mk.name + (mk.lo !== undefined && mk.lo !== null ? ` · ${fmt(mk.lo)}–${fmt(mk.hi)}` : "") }))));
        tip.classList.remove("hidden");
        const tw = tip.offsetWidth || 200;
        tip.style.left = `${Math.min(W - tw, Math.max(0, sx(present[0] ? present[0].value : 0) + 12))}px`;
        tip.style.top = `${top + h}px`;
      };
      g.addEventListener("pointerenter", showTip);
      g.addEventListener("focus", showTip);
      g.addEventListener("pointerleave", () => tip.classList.add("hidden"));
      g.addEventListener("blur", () => tip.classList.add("hidden"));
      svg.append(g);
      y += h;
    }
    holder.append(svg, tip);
  };
  draw();
  redrawOnResize(holder, draw);
}
