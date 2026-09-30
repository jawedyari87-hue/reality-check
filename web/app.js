import { el, lineChart, tableView, sparkline, dotChart, toMs, fmtDate } from "./charts.js";

// ======================================================================
// Basics
// ======================================================================

const $ = (sel, root = document) => root.querySelector(sel);
const COUNTRY_COLOR = { UK: "var(--s1)", US: "var(--s2)", Global: "var(--s3)" };
const SLOTS = ["var(--s1)", "var(--s2)", "var(--s3)", "var(--s4)", "var(--s5)", "var(--s6)", "var(--s7)", "var(--s8)"];
const TODAY = new Date().toISOString().slice(0, 10);

const S = {
  catalog: null, byId: {}, series: new Map(), rendered: {}, famous: null,
  famousFilter: { status: "all", region: "all" }, fset: "obr-unemployment",
  ex: { ids: null, range: "5y", index: false, view: "chart", colors: new Map() },
  sal: { occ: "software", money: "market", prices: "nominal" },
};

async function api(path, body) {
  const init = body === undefined ? {} : {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  };
  const res = await fetch(path, init);
  let data = {};
  try { data = await res.json(); } catch (e) { /* not JSON */ }
  if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
  return data;
}

async function catalog() {
  if (!S.catalog) {
    S.catalog = await api("/api/catalog");
    for (const s of S.catalog.series) S.byId[s.id] = s;
  }
  return S.catalog;
}

async function loadSeries(ids) {
  const need = [...new Set(ids)].filter((id) => !S.series.has(id));
  for (let i = 0; i < need.length; i += 12) {
    const res = await api("/api/series?ids=" + encodeURIComponent(need.slice(i, i + 12).join(",")));
    for (const item of res.items) S.series.set(item.id, item);
  }
  return ids.map((id) => S.series.get(id));
}

// ---------- formatting ----------
function fmtUnit(v, unit = "") {
  if (v === null || v === undefined || !isFinite(v)) return "–";
  if (unit === "%") return `${v.toFixed(1)}%`;
  if (unit === "thousands") return v >= 1000 ? `${(v / 1000).toFixed(2)}m` : `${Math.round(v)}k`;
  if (unit === "million") return `${v.toFixed(2)}m`;
  if (unit.startsWith("index")) return v.toFixed(1);
  if (unit.startsWith("£")) return `£${Math.round(v).toLocaleString("en-GB")}`;
  if (unit.startsWith("$")) return `$${Math.round(v).toLocaleString("en-GB")}`;
  return Math.abs(v) >= 1000 ? Math.round(v).toLocaleString("en-GB") : `${+v.toFixed(2)}`;
}
function axisFmt(unit = "") {
  if (unit === "%") return (v) => `${+v.toFixed(1)}%`;
  if (unit === "thousands") return (v) => (Math.abs(v) >= 1000 ? `${+(v / 1000).toFixed(1)}m` : `${+v.toFixed(0)}k`);
  if (unit === "million") return (v) => `${+v.toFixed(1)}m`;
  if (unit.startsWith("£")) return (v) => `£${Math.round(v).toLocaleString("en-GB")}`;
  if (unit.startsWith("$")) return (v) => `$${Math.round(v).toLocaleString("en-GB")}`;
  return (v) => (Math.abs(v) >= 1000 ? Math.round(v).toLocaleString("en-GB") : `${+v.toFixed(1)}`);
}
const gbp = (v) => (v === null || v === undefined || !isFinite(v) ? "–" : `£${Math.round(v).toLocaleString("en-GB")}`);
const gbpK = (v) => `£${+(v / 1000).toFixed(v >= 100000 ? 0 : 1)}k`;
const monthLabel = (iso) => (iso ? fmtDate(toMs(iso), "month") : "");
const dayLabel = (iso) => (iso ? fmtDate(toMs(iso), "week") : "");
const pct = (v, d = 0) => `${(v * 100).toFixed(d)}%`;
const signed = (v, d = 1) => `${v > 0 ? "+" : v < 0 ? "−" : "±"}${Math.abs(v).toFixed(d)}`;
// Lower-case a leading word for mid-sentence use, but leave acronyms (UK, CPI) alone.
const lower = (s) => (/^[A-Z]{2}/.test(s) ? s : s.charAt(0).toLowerCase() + s.slice(1));
const seriesLabel = (id) => { const s = S.byId[id]; return s ? `${s.country} · ${s.name}` : id; };

function head(title, lede, ...extra) {
  return el("div", { class: "section-head" },
    el("div", {}, el("h2", { text: title }), lede ? el("p", { class: "lede", text: lede }) : null), ...extra);
}

function seg(options, current, onPick, label) {
  return el("div", { class: "seg", role: "group", "aria-label": label || "" }, options.map(([value, text]) =>
    el("button", { type: "button", "aria-pressed": String(value === current), onclick: () => onPick(value), text })));
}

function sourceLine(items) {
  const uniq = new Map();
  for (const it of items) if (it && it.url) uniq.set(it.url, it);
  return el("p", { class: "source-line" }, "Source: ", [...uniq.values()].flatMap((s, i) => [
    i ? " · " : "", el("a", { href: s.url, target: "_blank", rel: "noopener", text: s.name + (s.code ? ` (${s.code})` : "") })]));
}

function notice(text, kind) {
  const n = $("#notice");
  if (!text) { n.classList.add("hidden"); return; }
  n.textContent = text;
  n.classList.remove("hidden");
  n.style.borderColor = kind === "error" ? "var(--critical)" : "";
}

// ---------- status chips ----------
const STATUS = {
  true: { label: "Came true", color: "var(--good)", glyph: "check" },
  false: { label: "Didn't happen", color: "var(--critical)", glyph: "cross" },
  pending: { label: "Too early", color: "var(--ghost)", glyph: "clock" },
  open: { label: "No deadline", color: "var(--ghost)", glyph: "dash" },
  awaiting: { label: "Waiting for data", color: "var(--warning)", glyph: "dots" },
  untestable: { label: "Can't be scored", color: "var(--ghost)", glyph: "q" },
  nodata: { label: "No data", color: "var(--ghost)", glyph: "q" },
};
function statusIcon(status) {
  const st = STATUS[status] || STATUS.nodata;
  const glyphs = {
    check: el("path", { d: "M4.2 7.3l1.9 1.9 3.8-4.2", fill: "none", stroke: "#fff", "stroke-width": 1.8, "stroke-linecap": "round", "stroke-linejoin": "round" }),
    cross: el("path", { d: "M4.7 4.7l4.6 4.6M9.3 4.7l-4.6 4.6", stroke: "#fff", "stroke-width": 1.8, "stroke-linecap": "round" }),
    clock: el("path", { d: "M7 3.8V7l2.1 1.4", fill: "none", stroke: "#fff", "stroke-width": 1.6, "stroke-linecap": "round" }),
    dash: el("path", { d: "M4.3 7h5.4", stroke: "#fff", "stroke-width": 1.8, "stroke-linecap": "round" }),
    dots: el("path", { d: "M4.3 7h.01M7 7h.01M9.7 7h.01", stroke: "#0b0b0b", "stroke-width": 2, "stroke-linecap": "round" }),
    q: el("text", { x: 7, y: 10.2, "text-anchor": "middle", "font-size": 9, "font-weight": 700, fill: "#fff", text: "?" }),
  };
  return el("svg", { width: 14, height: 14, viewBox: "0 0 14 14", "aria-hidden": "true" },
    el("circle", { cx: 7, cy: 7, r: 7, fill: st.color }), glyphs[st.glyph]);
}
const chip = (status) => el("span", { class: "chip" }, statusIcon(status), (STATUS[status] || STATUS.nodata).label);

function describeCheck(c) {
  const s = S.byId[c.series] || { country: "", name: c.series, unit: "" };
  const name = `${s.country} ${lower(s.name)}`;
  if (c.test === "reach") {
    return `${name} ${c.op === ">=" ? "reaches" : "falls to"} ${fmtUnit(c.value, s.unit)} or ${c.op === ">=" ? "higher" : "lower"} at any point ${c.start ? `between ${monthLabel(c.start)} and` : "before"} ${monthLabel(c.end)}`;
  }
  if (c.test === "level") {
    return `${name} is ${c.op === ">=" ? "at least" : "at most"} ${fmtUnit(c.value, s.unit)} in ${monthLabel(c.end)}`;
  }
  let move;
  if (c.op === "<=" && c.pct <= 0) move = c.pct === 0 ? "is lower (any fall)" : `falls by at least ${-c.pct}%`;
  else if (c.op === ">=" && c.pct >= 0) move = c.pct === 0 ? "is higher (any rise)" : `rises by at least ${c.pct}%`;
  else move = `changes by ${c.op === ">=" ? "at least" : "at most"} ${c.pct > 0 ? "+" : ""}${c.pct}%`;
  return `${name} ${move} ${c.end ? `between ${monthLabel(c.start)} and ${monthLabel(c.end)}` : `since ${monthLabel(c.start)}`}`;
}

// Plain-English progress for one check result (the server sends numbers).
function needText(c) {
  if (c.test === "change") {
    if (c.op === "<=") return c.pct === 0 ? "any fall" : c.pct < 0 ? `a fall of ${-c.pct}% or more` : `a rise of no more than ${c.pct}%`;
    return c.pct === 0 ? "any rise" : c.pct > 0 ? `a rise of ${c.pct}% or more` : `a fall of no more than ${-c.pct}%`;
  }
  const s = S.byId[c.series] || { unit: "" };
  return `${c.op === ">=" ? "at least" : "at most"} ${fmtUnit(c.value, s.unit)}`;
}

function resultText(r, c) {
  const u = r.unit || "";
  const when = (iso) => ((S.byId[c.series] || {}).unit || "").startsWith("index") ? dayLabel(iso) : monthLabel(iso);
  if (r.status === "nodata") return r.detail || "No data yet.";
  if (r.status === "awaiting") return `The deadline has passed; waiting for the official figure for ${monthLabel(c.end)}.`;
  if (c.test === "change") {
    const move = `${signed(r.changePct, 1)}%`;
    if (r.final) return `${when(r.baseline.date)} to ${when(r.final.date)}: ${move}. It needed ${needText(c)}.`;
    return `${move} since ${when(r.baseline.date)} (latest: ${when(r.latest.date)}). Needs ${needText(c)}${c.end ? ` by ${monthLabel(c.end)}` : ""}.`;
  }
  if (c.test === "reach") {
    if (r.hit) return `Reached ${fmtUnit(r.hit.value, u)} in ${when(r.hit.date)}, meeting the ${fmtUnit(r.target, u)} threshold.`;
    if (r.status === "false") return `Never ${c.op === ">=" ? "reached" : "fell to"} ${fmtUnit(r.target, u)}; the ${c.op === ">=" ? "highest" : "lowest"} was ${fmtUnit(r.extreme, u)}.`;
    return `Latest: ${fmtUnit(r.latest.value, u)} (${when(r.latest.date)}). Needs to ${c.op === ">=" ? "reach" : "fall to"} ${fmtUnit(r.target, u)}${c.end ? ` by ${monthLabel(c.end)}` : ""}.`;
  }
  if (r.final) return `${fmtUnit(r.final.value, u)} in ${when(r.final.date)}. It needed ${needText(c)}.`;
  return `Latest: ${fmtUnit(r.latest.value, u)} (${when(r.latest.date)}). Needs ${needText(c)} in ${monthLabel(c.end)}.`;
}

function resultRow(r, c) {
  const live = r.status === "pending" || r.status === "open";
  return el("div", { class: "result" },
    el("span", { class: "flag", text: r.country || "" }), " ", el("b", { text: `${r.seriesName}: ` }), resultText(r, c),
    live && r.onTrack !== undefined ? el("span", { class: "trend", text: r.onTrack ? "Condition met today" : "Not happening so far" }) : null);
}

// A prediction's chart(s): one small chart per checked series, with the
// window shaded and the threshold drawn; context series share one more.
async function predictionCharts(item, box) {
  const groups = (item.checks || []).map((c, i) => ({ ids: [c.series], check: c, result: (item.results || [])[i] }));
  if (item.context && item.context.length) groups.push({ ids: item.context });
  if (!groups.length) return;
  box.replaceChildren(el("div", { class: "empty small", text: "Loading chart…" }));
  await loadSeries(groups.flatMap((g) => g.ids));
  box.replaceChildren();
  box.className = groups.length > 1 ? "grid two" : "";
  const said = item.date || item.madeOn;
  for (const g of groups) {
    const metas = g.ids.map((id) => S.byId[id]).filter(Boolean);
    const unit = metas[0] ? metas[0].unit : "";
    const c = g.check;
    const from = new Date(toMs(c ? (c.start || said) : said));
    from.setUTCFullYear(from.getUTCFullYear() - 3);
    const fromIso = from.toISOString().slice(0, 10);
    const endIso = c && c.end && c.end > TODAY ? c.end : TODAY;
    const series = g.ids.map((id) => {
      const d = S.series.get(id) || { points: [] };
      return { name: seriesLabel(id), color: COUNTRY_COLOR[(S.byId[id] || {}).country] || "var(--s1)",
               points: d.points.filter((p) => p[0] >= fromIso) };
    });
    const hlines = [], bands = [], vlines = [];
    if (c) {
      bands.push({ from: c.start || said, to: c.end || TODAY, label: c.end ? "Prediction window" : "Since the prediction" });
      if (c.test === "change" && g.result && g.result.baseline) {
        hlines.push({ value: g.result.baseline.value * (1 + c.pct / 100),
                      label: c.pct === 0 ? `Level in ${monthLabel(g.result.baseline.date)}`
                        : `Target: ${c.pct > 0 ? "+" : "−"}${Math.abs(c.pct)}% on ${monthLabel(g.result.baseline.date)}` });
      } else if (c.value !== undefined) {
        hlines.push({ value: c.value, label: `Threshold ${c.op === ">=" ? "≥" : "≤"} ${fmtUnit(c.value, unit)}` });
      }
      // Mark when it was said only if the window starts noticeably later.
      if (c.start && said && Math.abs(toMs(c.start) - toMs(said)) > 60 * 864e5) vlines.push({ x: said, label: "Said" });
    } else {
      vlines.push({ x: said, label: "Said" });
      if (unit.startsWith("index")) hlines.push({ value: 100, label: "Feb 2020 level" });
    }
    const chartBox = el("div");
    const title = c ? metas.map((m) => `${m.country} · ${m.name}`).join(", ")
      : `For context: ${metas.map((m) => `${m.country} ${lower(m.name)}`).join(" and ")}`;
    box.append(el("div", { class: "chart-card" }, el("div", { class: "chart-sub", text: title }), chartBox,
      sourceLine(metas.map((m) => m.source))));
    lineChart(chartBox, { series, x: "date", height: 200, yFormat: axisFmt(unit), bands, hlines, vlines,
                          xDomain: [fromIso, endIso], label: title });
  }
}

// Draw a chart when it scrolls near view. A hidden tab never reports
// intersections, so there it draws straight away instead.
function lazy(node, fn) {
  const run = () => fn().catch((e) => node.replaceChildren(el("p", { class: "small muted", text: `Chart unavailable: ${e.message}` })));
  if (document.visibilityState !== "visible" || !("IntersectionObserver" in window)) { setTimeout(run, 0); return; }
  const io = new IntersectionObserver((entries) => {
    if (entries.some((e) => e.isIntersecting)) { io.disconnect(); run(); }
  }, { rootMargin: "300px" });
  io.observe(node);
}

// ======================================================================
// Overview
// ======================================================================

function tileCard(t) {
  if (!t.latest) {
    return el("div", { class: "card tile" }, el("span", { class: "label", text: seriesLabel(t.id) }),
      el("span", { class: "small muted", text: t.error ? `Unavailable: ${t.error}` : "No data yet" }));
  }
  const d = t.delta;
  let deltaNode = null;
  if (d !== undefined && d !== null) {
    const good = t.better === "up" ? d > 0 : t.better === "down" ? d < 0 : null;
    const cls = Math.abs(d) < 0.05 || good === null ? "" : good ? "up-good" : "up-bad";
    const txt = t.deltaMode === "pp" ? `${signed(d)} pts` : `${signed(d)}%`;
    deltaNode = el("span", { class: "delta" }, el("b", { class: cls, text: `${d > 0 ? "▲" : d < 0 ? "▼" : ""} ${txt}` }), " vs a year ago");
  }
  const indexNote = t.vsBaseline !== undefined
    ? el("span", { class: "delta", text: `${Math.abs(t.vsBaseline).toFixed(0)}% ${t.vsBaseline < 0 ? "below" : "above"} Feb 2020` }) : null;
  const spark = el("div", { class: "spark" });
  sparkline(spark, t.spark, { color: COUNTRY_COLOR[t.country] });
  return el("a", { class: "card tile", href: `#data?ids=${t.id}`, style: { color: "inherit", textDecoration: "none" } },
    el("span", { class: "label" }, el("span", { class: "flag", text: t.country }), t.name),
    el("span", { class: "value", text: fmtUnit(t.latest.value, t.unit) }),
    indexNote, deltaNode, spark,
    el("span", { class: "when", text: `${t.unit.startsWith("index") ? dayLabel(t.latest.date) : monthLabel(t.latest.date)} · ${t.source.name} ${t.source.code}` }));
}

async function renderOverview(root) {
  root.replaceChildren(el("div", { class: "empty", text: "Loading the latest figures…" }));
  const [ov] = await Promise.all([api("/api/overview"), catalog()]);
  if (!S.famous) S.famous = await api("/api/famous");

  const tiles = el("div", { class: "grid tiles" }, ov.tiles.map(tileCard));

  // Software postings vs all postings, UK and US, one index axis.
  const ids = ["uk.postings.software-development", "us.postings.software-development", "uk.postings", "us.postings"];
  await loadSeries(ids);
  const swChart = el("div");
  const swTable = el("div", { class: "hidden" });
  const pts = (id) => (S.series.get(id) || { points: [] }).points;
  const last = (id) => { const p = pts(id); return p.length ? p[p.length - 1][1] : null; };
  const swSeries = [
    { name: "UK software development", color: "var(--s1)", points: pts(ids[0]) },
    { name: "US software development", color: "var(--s2)", points: pts(ids[1]) },
    { name: "UK all jobs", color: "var(--s1)", points: pts(ids[2]), dash: "5 4", width: 1.5 },
    { name: "US all jobs", color: "var(--s2)", points: pts(ids[3]), dash: "5 4", width: 1.5 },
  ];
  const ukSw = last(ids[0]), usSw = last(ids[1]), ukAll = last(ids[2]);
  const swCard = el("div", { class: "card chart-card" },
    el("div", { class: "chart-head" },
      el("div", {}, el("h3", { text: "Software developer job postings since 2020" }),
        el("p", { class: "chart-sub", text: ukSw ? `UK software postings are ${Math.round(100 - ukSw)}% below Feb 2020 (all UK jobs: ${Math.round(100 - ukAll)}% below). US software: ${Math.round(100 - usSw)}% below. Index, 1 Feb 2020 = 100.` : "" })),
      seg([["chart", "Chart"], ["table", "Table"]], "chart", (v) => {
        swChart.classList.toggle("hidden", v !== "chart"); swTable.classList.toggle("hidden", v !== "table");
        for (const b of swCard.querySelectorAll(".seg button")) b.setAttribute("aria-pressed", String(b.textContent.toLowerCase() === v));
      }, "View")),
    swChart, swTable, sourceLine([{ name: "Indeed Hiring Lab job postings tracker", url: "https://github.com/hiring-lab/job_postings_tracker" }]));

  // Scorecard summary.
  const counts = ov.famousCounts || {};
  const upcoming = S.famous.items.filter((i) => i.status === "pending" && i.checks)
    .map((i) => ({ i, end: i.checks.map((c) => c.end).filter(Boolean).sort()[0] }))
    .sort((a, b) => (a.end < b.end ? -1 : 1)).slice(0, 4);
  const scoreCard = el("div", { class: "card", style: { display: "grid", gap: "12px", alignContent: "start" } },
    el("h3", { text: "Famous predictions: the scorecard" }),
    el("p", { class: "small muted", text: `${S.famous.items.length} predictions about jobs and AI, each checked against official data.` }),
    el("div", { class: "counts" }, ["true", "false", "pending", "open", "untestable"].filter((k) => counts[k]).map((k) =>
      el("a", { href: `#famous?status=${k}`, style: { textDecoration: "none" } }, el("span", { class: "chip" }, statusIcon(k), STATUS[k].label, el("b", { text: counts[k] }))))),
    el("div", { class: "small" }, el("b", { text: "Next deadlines" }),
      el("ul", { style: { margin: "6px 0 0", paddingLeft: "18px" } }, upcoming.map(({ i, end }) =>
        el("li", {}, `${i.who}: `, el("span", { class: "muted", text: `by ${monthLabel(end)}` }))))),
    el("a", { href: "#famous", class: "small", text: "See every prediction →" }));

  // Forecasters' record in one line each.
  const fcBox = el("div", { class: "card", style: { display: "grid", gap: "10px" } },
    el("h3", { text: "How often the professionals miss" }), el("p", { class: "small muted", text: "Loading…" }));
  root.replaceChildren(
    head("Where the job market is now", "The latest official figures, compared with a year earlier. Click any tile to see its full history."),
    tiles,
    el("div", { class: "grid two", style: { marginTop: "16px" } }, swCard, el("div", { class: "grid", style: { alignContent: "start" } }, scoreCard, fcBox)));
  lineChart(swChart, { series: swSeries, x: "date", height: 280, yFormat: axisFmt("index"),
                       hlines: [{ value: 100, label: "Feb 2020 level" }], label: "Software development job postings, UK and US" });
  tableView(swTable, swSeries, { fmt: (v) => v.toFixed(1), kind: "week" });

  Promise.all(["obr-unemployment", "spf-unemployment"].map((s) => api(`/api/forecasts?set=${s}`).catch(() => null))).then((sets) => {
    const lines = sets.filter((f) => f && f.byHorizon).map((f) => {
      const h1 = f.byHorizon.find((h) => h.horizon === 1);
      return el("p", { class: "small" }, el("b", { text: `${f.who.split(" (")[0]}, ${lower(f.name)}: ` }),
        `forecasts made a year ahead missed by ${h1.mae.toFixed(2)} points on average and were too gloomy ${pct(h1.tooGloomy)} of the time (${h1.n} forecasts).`);
    });
    fcBox.replaceChildren(el("h3", { text: "How often the professionals miss" }), ...lines,
      el("a", { href: "#forecasts", class: "small", text: "Every official forecast, graded →" }));
  });
}

// ======================================================================
// Famous predictions
// ======================================================================

function famousCard(item) {
  const results = (item.results || []).map((r, i) => resultRow(r, item.checks[i]));
  const charts = el("div");
  const hasChart = (item.checks && item.checks.length) || (item.context && item.context.length);
  if (hasChart) lazy(charts, () => predictionCharts(item, charts));
  const dl = el("dl", { style: { margin: 0 } });
  if (item.checks) dl.append(el("dt", { text: "The rule" }), ...item.checks.map((c) => el("dd", { text: `Came true if ${describeCheck(c)}.` })));
  if (item.howWeCheck) dl.append(el("dt", { text: "Why this rule" }), el("dd", { text: item.howWeCheck }));
  if (item.caveat) dl.append(el("dt", { text: "Caveat" }), el("dd", { text: item.caveat }));
  return el("article", { class: "card pred" },
    el("div", { class: "pred-head" },
      el("div", { class: "who" }, el("b", { text: item.who }), el("span", { class: "muted", text: ` · ${item.role} · ${item.dateLabel}` })),
      el("span", { class: "flag", text: item.region }), chip(item.status)),
    el("p", { class: "claim", text: item.claim }),
    item.quote ? el("p", { class: "quote small", text: `“${item.quote}”` }) : null,
    el("p", { class: "small muted", text: item.deadline ? `Deadline: ${item.deadline}` : "No deadline given" }),
    item.manual ? el("p", { class: "result", text: item.manual.summary }) : null,
    results.length ? el("div", { class: "results" }, results) : null,
    charts,
    item.lesson ? el("p", { class: "lesson", text: item.lesson }) : null,
    el("details", { class: "more" }, el("summary", { text: "How it's checked, caveats and sources" }),
      el("div", { class: "body" }, dl,
        el("div", { class: "sources" }, el("b", { class: "small", text: "Sources:" }),
          (item.sources || []).map((s) => el("a", { href: s.url, target: "_blank", rel: "noopener", text: s.name }))))));
}

async function renderFamous(root, params) {
  root.replaceChildren(el("div", { class: "empty", text: "Checking every prediction against the latest data…" }));
  await catalog();
  if (!S.famous) S.famous = await api("/api/famous");
  const f = S.famousFilter;
  if (params && params.get("status")) f.status = params.get("status");
  const items = S.famous.items;
  const counts = {};
  for (const i of items) counts[i.status] = (counts[i.status] || 0) + 1;
  const list = el("div", { class: "grid" });
  const draw = () => {
    const shown = items.filter((i) => (f.status === "all" || i.status === f.status) && (f.region === "all" || i.region === f.region));
    list.replaceChildren(...(shown.length ? shown.map(famousCard) : [el("div", { class: "empty", text: "Nothing matches these filters." })]));
    filters.replaceChildren(
      seg([["all", `All ${items.length}`], ...["true", "false", "pending", "open", "untestable"].filter((k) => counts[k]).map((k) => [k, `${STATUS[k].label} ${counts[k]}`])],
        f.status, (v) => { f.status = v; draw(); }, "Verdict"),
      seg([["all", "All regions"], ["UK", "UK"], ["US", "US"], ["Global", "Global"]], f.region, (v) => { f.region = v; draw(); }, "Region"));
  };
  const filters = el("div", { class: "filters" });
  root.replaceChildren(
    head("Famous predictions, checked", "Each prediction is turned into a rule that data can settle, and the rule is shown, so you can argue with the rule rather than the data. Verdicts update automatically as new figures come out."),
    el("p", { class: "small muted", style: { marginBottom: "8px" }, text: S.famous.note || "" }),
    filters, list);
  draw();
}

// ======================================================================
// Official forecasts
// ======================================================================

async function renderForecasts(root, params) {
  await catalog();
  if (params && params.get("set")) S.fset = params.get("set");
  const body = el("div", { class: "grid" }, el("div", { class: "empty", text: "Loading forecasts…" }));
  const pick = el("div", { class: "filters" });
  const drawPick = () => pick.replaceChildren(seg(S.catalog.forecastSets.map((s) => [s.id, `${s.country} · ${s.name.replace(/^(UK|US) /, "")}`]),
    S.fset, (v) => { S.fset = v; drawPick(); load(); }, "Forecast set"));
  drawPick();
  root.replaceChildren(
    head("How good are official forecasts?", "Every forecast published by the UK's Office for Budget Responsibility since 2010, and the US Survey of Professional Forecasters since 1968, scored against what actually happened. If the professionals miss this often, treat any confident prediction, including your own, with care."),
    pick, body);
  const load = async () => {
    body.classList.add("loading");
    const f = await api(`/api/forecasts?set=${S.fset}`);
    body.classList.remove("loading");
    if (f.error || !f.vintages) { body.replaceChildren(el("div", { class: "notice", text: `Couldn't load: ${f.error || "no data"}` })); return; }
    body.replaceChildren(...forecastView(f));
  };
  await load();
}

function forecastView(f) {
  const unitShort = f.unit === "%" ? " pts" : f.unit === "million" ? "m" : "";
  const d = f.decimals;
  const H = (h) => f.byHorizon.find((x) => x.horizon === h);
  const h1 = H(1), h2 = H(2);
  const gloomyWord = f.pessimistic === "above" ? "forecast higher than what happened" : "forecast lower than what happened";
  const stats = el("div", { class: "stat-row" },
    el("div", { class: "card stat" }, el("div", { class: "v", text: h1 ? `±${h1.mae.toFixed(2)}${unitShort}` : "–" }), el("div", { class: "l", text: "Average miss, forecasting one year ahead" })),
    el("div", { class: "card stat" }, el("div", { class: "v", text: h2 ? `±${h2.mae.toFixed(2)}${unitShort}` : "–" }), el("div", { class: "l", text: "Average miss, two years ahead" })),
    el("div", { class: "card stat" }, el("div", { class: "v", text: h1 ? pct(h1.tooGloomy) : "–" }), el("div", { class: "l", text: `Too gloomy one year ahead (${gloomyWord})` })),
    el("div", { class: "card stat" }, el("div", { class: "v", text: h1 ? pct(h1.within) : "–" }), el("div", { class: "l", text: `One-year forecasts within ±${f.tolerance}${unitShort} of the outcome` })));

  // Hedgehog chart: every forecast path (grey) against what happened (blue).
  const isSPF = f.id.startsWith("spf");
  const st = { vintage: f.vintages[f.vintages.length - 1].label, from: isSPF ? 2000 : 2008, q1: isSPF };
  const chartBox = el("div"), tableBox = el("div", { class: "hidden" });
  const vSel = el("select", { "aria-label": "Highlight one forecast" });
  const controls = el("div", { class: "filters", style: { margin: 0 } });
  const drawChart = () => {
    const vint = f.vintages.filter((v) => (!st.q1 || !v.quarter || v.quarter === 1 || v.label === st.vintage) && +v.date.slice(0, 4) >= st.from);
    vSel.replaceChildren(...[...f.vintages].reverse().filter((v) => +v.date.slice(0, 4) >= st.from)
      .map((v) => el("option", { value: v.label, selected: v.label === st.vintage, text: v.label })));
    const actual = f.actual.filter((a) => a[0] >= st.from).map((a) => [a[0], a[1]]);
    const sel = f.vintages.find((v) => v.label === st.vintage);
    const series = [
      ...vint.filter((v) => v.label !== st.vintage).map((v) => ({ name: v.label, ghost: true, noTip: true, width: 1.1, opacity: 0.4, points: v.points })),
      { name: "What happened", color: "var(--s1)", width: 2.5, points: actual, dots: true },
      sel ? { name: `Forecast: ${sel.label}`, color: "var(--s2)", width: 2, points: sel.points, dots: true } : null,
    ].filter(Boolean);
    lineChart(chartBox, {
      series, x: "year", height: 320, yFormat: (v) => `${+v.toFixed(d)}${f.unit === "%" ? "%" : f.unit === "million" ? "m" : ""}`,
      legend: [{ name: "What happened", color: "var(--s1)" }, { name: `Highlighted: ${st.vintage}`, color: "var(--s2)" },
               { name: "Every other forecast", color: "var(--ghost)", kind: "ghost" }],
      label: `${f.name}: forecasts against outcomes`,
      tip: (year, rows) => {
        const fs = f.vintages.map((v) => (v.points.find((p) => p[0] === year) || [])[1]).filter((v) => v !== undefined);
        if (fs.length) rows.push({ color: "var(--ghost)", value: `${Math.min(...fs).toFixed(d)}–${Math.max(...fs).toFixed(d)}`, name: `range of ${fs.length} forecasts for ${year}` });
        return rows;
      },
    });
    tableView(tableBox, [{ name: "What happened", points: actual },
      ...(sel ? [{ name: sel.label, points: sel.points }] : [])], { x: "year", fmt: (v) => v.toFixed(d) });
  };
  vSel.addEventListener("change", () => { st.vintage = vSel.value; drawChart(); });
  const rangeSeg = () => seg(isSPF ? [[1968, "Since 1968"], [2000, "Since 2000"], [2015, "Last 10 years"]] : [[2008, "All (since 2010)"], [2018, "Since 2018"]],
    st.from, (v) => { st.from = v; controls.replaceChildren(...ctl().filter(Boolean)); drawChart(); }, "Range");
  const ctl = () => [el("label", {}, "Highlight", vSel), rangeSeg(),
    isSPF ? el("label", {}, el("input", { type: "checkbox", checked: st.q1, onchange: (e) => { st.q1 = e.target.checked; drawChart(); } }), "First survey of each year only") : null,
    seg([["chart", "Chart"], ["table", "Table"]], "chart", (v) => {
      chartBox.classList.toggle("hidden", v !== "chart"); tableBox.classList.toggle("hidden", v !== "table");
    }, "View")];
  controls.replaceChildren(...ctl().filter(Boolean));
  const hedgehog = el("div", { class: "card chart-card" },
    el("div", {}, el("h3", { text: `${f.name}: every forecast against what happened` }),
      el("p", { class: "chart-sub", text: `${f.what} Each grey line is one published forecast, starting from when it was made. ${isSPF ? "Median of the professional forecasters surveyed." : ""}` })),
    controls, chartBox, tableBox, sourceLine([f.source]));

  // Accuracy by horizon.
  const hname = (h) => (h === 0 ? "Same year" : h === 1 ? "1 year ahead" : `${h} years ahead`);
  const acc = el("div", { class: "card chart-card" },
    el("h3", { text: "Accuracy by how far ahead they looked" }),
    el("div", { class: "table-wrap", style: { maxHeight: "none" } }, el("table", { class: "data" },
      el("thead", {}, el("tr", {}, ["Horizon", "Forecasts scored", "Average miss", "Average bias", `Within ±${f.tolerance}${unitShort}`, "Too gloomy"].map((t) => el("th", { text: t })))),
      el("tbody", {}, f.byHorizon.map((h) => el("tr", {},
        el("td", { text: hname(h.horizon) }), el("td", { text: h.n }), el("td", { text: `±${h.mae.toFixed(2)}${unitShort}` }),
        el("td", { text: `${signed(h.bias, 2)}${unitShort}` }), el("td", { text: pct(h.within) }), el("td", { text: pct(h.tooGloomy) })))))),
    el("p", { class: "small muted", text: `Bias above zero means forecasts were too high on average. For ${lower(f.name)}, "too gloomy" means ${gloomyWord}.` }));

  const misses = el("div", { class: "card chart-card" },
    el("h3", { text: "The biggest misses" }),
    el("div", { class: "table-wrap", style: { maxHeight: "none" } }, el("table", { class: "data" },
      el("thead", {}, el("tr", {}, ["Forecast made", "For year", "Said", "Happened", "Miss"].map((t) => el("th", { text: t })))),
      el("tbody", {}, f.misses.map((m) => el("tr", {},
        el("td", { text: m.vintage }), el("td", { text: m.year }), el("td", { text: m.forecast.toFixed(d) }),
        el("td", { text: m.actual.toFixed(d) }), el("td", { text: `${signed(m.error, d)}${unitShort}` })))))));

  const live = f.live ? `Latest actual reading: ${fmtUnit(f.live.value, f.unit === "million" ? "million" : "%")} (${monthLabel(f.live.date)}${f.id === "obr-earnings" ? ", total pay growth" : ""}).` : "";
  const open = el("div", { class: "card chart-card" },
    el("h3", { text: `Still open: the ${f.latestVintage} forecast` }),
    el("p", { class: "small muted", text: `${live} These resolve as each year's figures come in. Given the record above, expect misses of roughly the size shown.` }),
    el("div", { class: "table-wrap", style: { maxHeight: "none" } }, el("table", { class: "data" },
      el("thead", {}, el("tr", {}, ["Year", "Forecast", "Typical miss at this range"].map((t) => el("th", { text: t })))),
      el("tbody", {}, f.pending.map((p) => {
        const h = H(p.year - +f.vintages[f.vintages.length - 1].date.slice(0, 4));
        return el("tr", {}, el("td", { text: p.year }), el("td", { text: p.forecast.toFixed(d) + (f.unit === "%" ? "%" : f.unit === "million" ? "m" : "") }),
          el("td", { text: h ? `±${h.mae.toFixed(2)}${unitShort}` : "–" }));
      })))));
  setTimeout(drawChart, 0); // after the caller has put these nodes on the page
  return [stats, hedgehog, el("div", { class: "grid two" }, acc, open), misses];
}

// ======================================================================
// Salaries
// ======================================================================

async function renderSalaries(root) {
  root.replaceChildren(el("div", { class: "empty", text: "Loading salary tables…" }));
  let data = await api("/api/salaries");
  const body = el("div", { class: "grid" });
  const status = el("div");
  const controls = el("div", { class: "filters" });
  root.replaceChildren(
    head("Salaries: UK against US", "Official pay by occupation: full-time gross annual pay from the ONS Annual Survey of Hours and Earnings, against the US Bureau of Labor Statistics' occupational wage survey. Convert at the market exchange rate, or at purchasing power (what the money actually buys)."),
    status, controls, body);

  const poll = async () => {
    const job = await api("/api/salaries/status");
    if (job.running) {
      status.replaceChildren(el("div", { class: "notice" }, `Downloading official salary tables: ${job.message}`,
        el("div", { class: "bar" }, el("div", { style: { width: `${job.total ? (100 * job.done) / job.total : 5}%` } }))));
      setTimeout(poll, 2000);
    } else {
      status.replaceChildren(job.error ? el("div", { class: "notice", text: `Salary download stopped: ${job.error}. What was saved is shown.` }) : "");
      if (job.finished && (!data.updated || job.finished > data.updated)) { data = await api("/api/salaries"); draw(); }
    }
  };
  if (!Object.keys(data.uk).length && !data.job.running) await api("/api/salaries/refresh", {});
  poll();

  const draw = () => {
    const st = S.sal;
    const occ = data.occupations.find((o) => o.id === st.occ) || data.occupations[0];
    const uk = data.uk[occ.id] || [], us = data.us[occ.id] || [];
    const years = [...uk.map((r) => r.year), ...us.map((r) => r.year)];
    if (!years.length) { body.replaceChildren(el("div", { class: "empty", text: "No salary data yet - it downloads on first run." })); drawControls(); return; }
    const L = Math.max(...years);
    const lastKey = (o) => { const ks = Object.keys(o).map(Number).filter((k) => o[k] !== null); return Math.max(...ks); };
    const fxAt = (y) => data.fx[y] || data.fx[lastKey(data.fx)];
    const pppAt = (y) => data.ppp[y] || data.ppp[lastKey(data.ppp)];
    const cpi = (tbl, y) => tbl[y] || tbl[lastKey(tbl)];
    const real = st.prices === "real";
    const ukGBP = (v, y) => (v === null || v === undefined ? null : real ? v * cpi(data.cpiUK, L) / cpi(data.cpiUK, y) : v);
    const usGBP = (v, y) => {
      if (v === null || v === undefined) return null;
      const usd = real ? v * cpi(data.cpiUS, L) / cpi(data.cpiUS, y) : v;
      const ry = real ? L : y;
      return st.money === "ppp" ? usd * pppAt(ry) : usd / fxAt(ry);
    };
    const moneyWord = st.money === "ppp" ? "at purchasing-power parity" : "at the market exchange rate";
    const priceWord = real ? `in ${L} prices` : "in each year's money";
    const ukL = uk.find((r) => r.year === L) || uk[uk.length - 1];
    const usL = us.find((r) => r.year === L) || us[us.length - 1];
    const ukFirst = uk[0], usFirst = us[0];

    // Tiles.
    // Real growth in each country's own currency and prices, so exchange-rate swings don't distort it.
    const growth = (rows, cpiTable) => {
      if (rows.length < 2) return null;
      const a = rows[0], b = rows[rows.length - 1];
      return { from: a.year, to: b.year, real: (b.median / a.median) * (cpi(cpiTable, a.year) / cpi(cpiTable, b.year)) - 1 };
    };
    const gUK = growth(uk, data.cpiUK), gUS = growth(us, data.cpiUS);
    const tiles = el("div", { class: "stat-row" },
      el("div", { class: "card stat" }, el("div", { class: "v", text: ukL ? gbp(ukGBP(ukL.median, ukL.year)) : "–" }),
        el("div", { class: "l", text: `UK median, ${ukL ? ukL.year : ""} (${ukL ? ukL.title : ""})` })),
      el("div", { class: "card stat" }, el("div", { class: "v", text: usL ? gbp(usGBP(usL.median, usL.year)) : "No US match" }),
        el("div", { class: "l", text: usL ? `US median, ${usL.year}, ${moneyWord} ($${Math.round(usL.median).toLocaleString("en-GB")})` : occ.note })),
      el("div", { class: "card stat" }, el("div", { class: "v", text: ukL && usL ? `${(usGBP(usL.median, usL.year) / ukGBP(ukL.median, ukL.year)).toFixed(2)}×` : "–" }),
        el("div", { class: "l", text: `US pay as a multiple of UK pay (${st.money === "ppp" ? "purchasing power" : "market rate"})` })),
      el("div", { class: "card stat" }, el("div", { class: "v", text: gUK ? `${signed(gUK.real * 100, 0)}%` : "–" }),
        el("div", { class: "l", text: gUK ? `UK real pay change ${gUK.from}–${gUK.to} (after inflation)${gUS ? `; US ${signed(gUS.real * 100, 0)}%` : ""}` : "Not enough years yet" })));

    // Median over time with the middle-half band.
    const mk = (rows, conv) => rows.map((r) => [r.year, conv(r.median, r.year)]);
    const band = (rows, conv) => rows.filter((r) => r.p25 && r.p75).map((r) => [r.year, conv(r.p25, r.year), conv(r.p75, r.year)]);
    const lineBox = el("div"), lineTable = el("div", { class: "hidden" });
    const trend = [
      { name: "UK median", color: "var(--s1)", points: mk(uk, ukGBP), area: band(uk, ukGBP), dots: true },
      us.length ? { name: "US median", color: "var(--s2)", points: mk(us, usGBP), area: band(us, usGBP), dots: true } : null,
    ].filter(Boolean);
    const trendCard = el("div", { class: "card chart-card" },
      el("div", { class: "chart-head" },
        el("div", {}, el("h3", { text: `${occ.name}: median full-time pay` }),
          el("p", { class: "chart-sub", text: `Pounds ${priceWord}, US converted ${moneyWord}. Shaded: the middle half of earners (25th to 75th percentile).` })),
        seg([["chart", "Chart"], ["table", "Table"]], "chart", (v) => {
          lineBox.classList.toggle("hidden", v !== "chart"); lineTable.classList.toggle("hidden", v !== "table");
        }, "View")),
      lineBox, lineTable,
      el("p", { class: "small muted", text: occ.note + (uk.some((r) => r.year >= 2021) && uk.some((r) => r.year < 2021) ? " UK occupation codes changed in 2021 (SOC 2010 to SOC 2020), so the line has a small break there." : "") }));

    // Pay range, latest year.
    const rangeRows = [ukL ? { label: `UK ${ukL.year}`, marks: [{ name: "UK", color: "var(--s1)", value: ukGBP(ukL.median, ukL.year), lo: ukGBP(ukL.p10, ukL.year), hi: ukGBP(ukL.p90, ukL.year), lo2: ukGBP(ukL.p25, ukL.year), hi2: ukGBP(ukL.p75, ukL.year) }] } : null,
      usL ? { label: `US ${usL.year}`, marks: [{ name: "US", color: "var(--s2)", value: usGBP(usL.median, usL.year), lo: usGBP(usL.p10, usL.year), hi: usGBP(usL.p90, usL.year), lo2: usGBP(usL.p25, usL.year), hi2: usGBP(usL.p75, usL.year) }] } : null].filter(Boolean);
    const rangeBox = el("div");
    const rangeCard = el("div", { class: "card chart-card" },
      el("div", {}, el("h3", { text: "What the bottom, middle and top earn" }),
        el("p", { class: "chart-sub", text: "Thin line: 10th to 90th percentile. Thick: 25th to 75th. Dot: median. A new graduate typically starts near the 10th-25th percentile." })),
      rangeBox,
      usL && usL.topcoded && usL.topcoded.length ? el("p", { class: "small muted", text: "Some US values are above the BLS's top reporting limit and aren't shown." }) : null);

    // Every occupation, UK vs US medians.
    const allRows = data.occupations.map((o) => {
      const u = (data.uk[o.id] || []).find((r) => r.year === L) || (data.uk[o.id] || []).slice(-1)[0];
      const a = (data.us[o.id] || []).find((r) => r.year === L) || null;
      return { o, u, a };
    }).filter((r) => r.u).sort((x, y) => ukGBP(y.u.median, y.u.year) - ukGBP(x.u.median, x.u.year));
    const dumbBox = el("div"), dumbTable = el("div", { class: "hidden" });
    const dumbCard = el("div", { class: "card chart-card" },
      el("div", { class: "chart-head" },
        el("div", {}, el("h3", { text: `Every occupation tracked, ${L}: UK against US median` }),
          el("p", { class: "chart-sub", text: `Pounds, US ${moneyWord}. Sorted by UK pay.` })),
        seg([["chart", "Chart"], ["table", "Table"]], "chart", (v) => {
          dumbBox.classList.toggle("hidden", v !== "chart"); dumbTable.classList.toggle("hidden", v !== "table");
        }, "View")),
      dumbBox, dumbTable);

    body.replaceChildren(tiles, trendCard, el("div", { class: "grid two" }, rangeCard, el("div", { class: "card chart-card" },
      el("h3", { text: "How to read this" }),
      el("ul", { class: "small", style: { margin: 0, paddingLeft: "18px", display: "grid", gap: "6px" } },
        el("li", { text: "UK figures are full-time employees only. US figures are hourly pay × 2,080 hours, a full-time equivalent." }),
        el("li", { text: "Market rate is what you'd get changing money. Purchasing power adjusts for US prices being higher, so it's the fairer measure of living standards." }),
        el("li", { text: "Neither includes US health insurance costs, which employees often part-pay, or the UK's lower cost of university and healthcare." }),
        el("li", { text: "Big-tech and finance pay (bonuses, shares) sits in the top 10%, above what these medians show." })),
      sourceLine([data.sources.uk, data.sources.us, st.money === "ppp" ? data.sources.ppp : data.sources.fx]))), dumbCard);

    lineChart(lineBox, { series: trend, x: "year", height: 280, yFormat: gbpK, zero: false,
                         vlines: uk.some((r) => r.year >= 2021) && uk.some((r) => r.year < 2021) ? [{ x: 2021, label: "UK codes change" }] : [],
                         label: `${occ.name} median pay, UK and US` });
    tableView(lineTable, [
      { name: "UK median", points: uk.map((r) => [r.year, ukGBP(r.median, r.year)]) },
      { name: "UK 25th pct", points: uk.map((r) => [r.year, ukGBP(r.p25, r.year)]) },
      { name: "UK 75th pct", points: uk.map((r) => [r.year, ukGBP(r.p75, r.year)]) },
      ...(us.length ? [{ name: "US median (£)", points: us.map((r) => [r.year, usGBP(r.median, r.year)]) },
                       { name: "US median ($, as published)", points: us.map((r) => [r.year, r.median]) }] : []),
    ], { x: "year", fmt: (v) => Math.round(v).toLocaleString("en-GB") });
    dotChart(rangeBox, rangeRows, { fmt: gbpK, label: "Pay distribution, UK and US" });
    dotChart(dumbBox, allRows.map((r) => ({ label: r.o.name, marks: [
      { name: "UK", color: "var(--s1)", value: ukGBP(r.u.median, r.u.year) },
      { name: "US", color: "var(--s2)", value: r.a ? usGBP(r.a.median, r.a.year) : null }] })),
    { fmt: gbpK, connect: true, legend: [{ name: "UK", color: "var(--s1)" }, { name: "US", color: "var(--s2)" }], label: "Median pay by occupation" });
    dumbTable.replaceChildren(el("div", { class: "table-wrap" }, el("table", { class: "data" },
      el("thead", {}, el("tr", {}, ["Occupation", "UK median", "US median (£)", "US median ($)", "US ÷ UK"].map((t) => el("th", { text: t })))),
      el("tbody", {}, allRows.map((r) => {
        const u = ukGBP(r.u.median, r.u.year), a = r.a ? usGBP(r.a.median, r.a.year) : null;
        return el("tr", {}, el("td", { class: "text", text: r.o.name }), el("td", { text: gbp(u) }), el("td", { text: gbp(a) }),
          el("td", { text: r.a ? `$${Math.round(r.a.median).toLocaleString("en-GB")}` : "–" }), el("td", { text: a ? `${(a / u).toFixed(2)}×` : "–" }));
      })))));
    drawControls();
  };
  const drawControls = () => {
    const sel = el("select", { "aria-label": "Occupation", onchange: (e) => { S.sal.occ = e.target.value; draw(); } },
      data.occupations.map((o) => el("option", { value: o.id, selected: o.id === S.sal.occ, text: o.name + (o.hasUS ? "" : " (UK only)") })));
    controls.replaceChildren(el("label", {}, "Occupation", sel),
      seg([["market", "£ at market rate"], ["ppp", "£ at purchasing power"]], S.sal.money, (v) => { S.sal.money = v; draw(); }, "Currency"),
      seg([["nominal", "Each year's money"], ["real", "Today's prices"]], S.sal.prices, (v) => { S.sal.prices = v; draw(); }, "Prices"),
      el("span", { class: "small muted", text: data.updated ? `Tables downloaded ${data.updated.slice(0, 10)}` : "" }));
  };
  draw();
}

// ======================================================================
// Explore data
// ======================================================================

async function renderData(root, params) {
  await catalog();
  const ex = S.ex;
  if (params && params.get("ids")) ex.ids = params.get("ids").split(",").filter((id) => S.byId[id]);
  if (!ex.ids || !ex.ids.length) ex.ids = ["uk.unemployment", "us.unemployment"];
  const assign = () => {
    for (const id of [...ex.colors.keys()]) if (!ex.ids.includes(id)) ex.colors.delete(id);
    for (const id of ex.ids) {
      if (!ex.colors.has(id)) {
        const used = new Set(ex.colors.values());
        ex.colors.set(id, SLOTS.find((c) => !used.has(c)) || SLOTS[0]);
      }
    }
  };
  assign();

  const picker = el("div", { class: "card picker" });
  const main = el("div", { class: "grid" });
  root.replaceChildren(
    head("Explore the data", "Every series the predictions are checked against. Pick up to eight; series in different units are put on a common index (start = 100) so they can share one axis."),
    el("div", { class: "explorer" }, picker, main));

  const toggle = (id, on) => {
    if (on && !ex.ids.includes(id) && ex.ids.length < 8) ex.ids.push(id);
    if (!on) ex.ids = ex.ids.filter((x) => x !== id);
    assign();
    history.replaceState(null, "", `#data?ids=${ex.ids.join(",")}`);
    drawPicker();
    drawMain();
  };
  let search = "";
  const drawPicker = () => {
    const box = (s) => el("label", {},
      el("input", { type: "checkbox", checked: ex.ids.includes(s.id), disabled: !ex.ids.includes(s.id) && ex.ids.length >= 8,
                    onchange: (e) => toggle(s.id, e.target.checked) }),
      el("span", { class: "swatch", style: { background: ex.colors.get(s.id) || "transparent", border: ex.colors.get(s.id) ? "0" : "1px solid var(--axis)" } }),
      el("span", { text: s.sector ? `${s.country} · ${s.sector}` : s.name }));
    const nodes = [];
    for (const country of ["UK", "US"]) {
      nodes.push(el("h4", { text: country === "UK" ? "United Kingdom" : "United States" }));
      const list = S.catalog.series.filter((s) => s.country === country && !s.hidden && !s.sector);
      for (const s of list) nodes.push(box(s));
    }
    nodes.push(el("h4", { text: "Job postings by sector (Indeed)" }));
    const input = el("input", { type: "search", placeholder: "Search sectors, e.g. software", value: search,
      oninput: (e) => { search = e.target.value; drawPicker(); const i = picker.querySelector("input[type=search]"); i.focus(); i.setSelectionRange(search.length, search.length); } });
    nodes.push(input);
    const q = search.trim().toLowerCase();
    const sectors = S.catalog.series.filter((s) => s.sector && (q ? s.sector.toLowerCase().includes(q) : s.featured || ex.ids.includes(s.id)));
    for (const s of sectors) nodes.push(box(s));
    if (!q) nodes.push(el("p", { class: "tiny muted", text: `Showing featured sectors. Search to see all ${S.catalog.series.filter((s) => s.sector).length / 2} per country.` }));
    picker.replaceChildren(...nodes);
  };

  const chartBox = el("div"), tableBox = el("div", { class: "hidden" }), notes = el("div", { class: "grid", style: { gap: "6px" } });
  const controls = el("div", { class: "filters", style: { margin: 0 } });
  const drawMain = async () => {
    const card = el("div", { class: "card chart-card" }, controls, chartBox, tableBox);
    main.replaceChildren(card, el("div", { class: "card" }, notes));
    const ranges = [["1y", "1Y"], ["3y", "3Y"], ["5y", "5Y"], ["2020", "Since 2020"], ["10y", "10Y"], ["all", "All"]];
    const units = new Set(ex.ids.map((id) => S.byId[id].unit));
    const mustIndex = units.size > 1;
    controls.replaceChildren(
      seg(ranges, ex.range, (v) => { ex.range = v; drawMain(); }, "Range"),
      el("label", {}, el("input", { type: "checkbox", checked: ex.index || mustIndex, disabled: mustIndex,
        onchange: (e) => { ex.index = e.target.checked; drawMain(); } }), "Index to 100 at start"),
      seg([["chart", "Chart"], ["table", "Table"]], ex.view, (v) => { ex.view = v; drawMain(); }, "View"));
    chartBox.classList.toggle("hidden", ex.view !== "chart");
    tableBox.classList.toggle("hidden", ex.view !== "table");
    if (!ex.ids.length) { chartBox.replaceChildren(el("div", { class: "empty", text: "Pick a series on the left." })); notes.replaceChildren(); return; }
    chartBox.classList.add("loading");
    const data = await loadSeries(ex.ids);
    chartBox.classList.remove("loading");
    const now = new Date();
    const start = ex.range === "all" ? "0000" : ex.range === "2020" ? "2020-01-01"
      : new Date(Date.UTC(now.getUTCFullYear() - parseInt(ex.range, 10), now.getUTCMonth(), 1)).toISOString().slice(0, 10);
    const indexed = ex.index || mustIndex;
    const series = data.map((d, i) => {
      const meta = S.byId[ex.ids[i]];
      let pts = (d.points || []).filter((p) => p[0] >= start);
      if (indexed && pts.length) { const b = pts[0][1]; pts = pts.map((p) => [p[0], (p[1] / b) * 100]); }
      return { name: seriesLabel(meta.id), color: ex.colors.get(meta.id), points: pts, unit: meta.unit, error: d.error };
    });
    const unit = indexed ? "index" : [...units][0];
    lineChart(chartBox, { series, x: "date", height: 340, yFormat: axisFmt(unit),
                          hlines: indexed ? [{ value: 100, label: "Start = 100" }] : [], label: "Selected series" });
    tableView(tableBox, series, { fmt: (v) => fmtUnit(v, unit) });
    notes.replaceChildren(
      mustIndex ? el("p", { class: "small", text: "These series are in different units, so each is shown relative to its first value in the range (= 100). Untick series to compare raw values." }) : null,
      ...ex.ids.map((id, i) => {
        const s = S.byId[id];
        const d = data[i];
        const lastP = d.points && d.points.length ? d.points[d.points.length - 1] : null;
        return el("div", { class: "small" },
          el("span", { class: "swatch", style: { display: "inline-block", width: "10px", height: "10px", borderRadius: "50%", background: ex.colors.get(id), marginRight: "6px" } }),
          el("b", { text: seriesLabel(id) }), lastP ? ` · latest ${fmtUnit(lastP[1], s.unit)} (${s.unit.startsWith("index") ? dayLabel(lastP[0]) : monthLabel(lastP[0])})` : "",
          d.error ? el("span", { class: "up-bad", text: ` · ${d.stale ? "showing saved copy: " : ""}${d.error}` }) : "",
          s.note ? el("div", { class: "muted", text: s.note }) : null,
          el("div", {}, el("a", { href: s.source.url, target: "_blank", rel: "noopener", class: "tiny", text: `${s.source.name} ${s.source.code}` })));
      }));
  };
  drawPicker();
  drawMain();
}

// ======================================================================
// My predictions
// ======================================================================

const IDEAS = [
  { label: "UK software postings stay low", claim: "UK software development job postings will still be at least 30% below their Feb 2020 level in Sep 2030.",
    check: { series: "uk.postings.software-development", test: "level", op: "<=", value: 70, end: "2030-09-01" } },
  { label: "UK youth unemployment hits 20%", claim: "UK youth unemployment (16-24) will reach 20% before Sep 2030.",
    check: { series: "uk.youth_unemployment", test: "reach", op: ">=", value: 20, start: TODAY, end: "2030-09-01" } },
  { label: "Amodei's 10% call", claim: "US unemployment will reach 10% before the end of May 2030.",
    check: { series: "us.unemployment", test: "reach", op: ">=", value: 10, start: TODAY, end: "2030-05-28" } },
  { label: "UK pay keeps rising", claim: "Average UK weekly pay will rise at least 20% by Sep 2030.",
    check: { series: "uk.weekly_pay", test: "change", op: ">=", pct: 20, start: TODAY, end: "2030-09-01" } },
  { label: "UK vacancies below 600k", claim: "UK job vacancies will drop below 600,000 before the end of 2028.",
    check: { series: "uk.vacancies", test: "reach", op: "<=", value: 600, start: TODAY, end: "2028-12-01" } },
  { label: "US data jobs recover", claim: "US Data & Analytics job postings will be back above their Feb 2020 level in Sep 2029.",
    check: { series: "us.postings.data-and-analytics", test: "level", op: ">=", value: 100, end: "2029-09-01" } },
];

async function renderMine(root) {
  await catalog();
  let data = await api("/api/mine");
  const form = el("form", { class: "form", novalidate: true });
  const listBox = el("div", { class: "grid" });
  const statsBox = el("div", { class: "stat-row" });
  root.replaceChildren(
    head("My predictions", "Write down what you expect, tie it to real data, and the app scores it automatically when the deadline passes. The aim isn't to be right every time. It's for your confidence to match how often you turn out right."),
    statsBox,
    el("div", { class: "card", style: { marginBottom: "16px" } }, el("h3", { text: "New prediction", id: "form-title", style: { marginBottom: "10px" } }), form),
    listBox);

  let editing = null;
  const f = {};
  const field = (label, input, hint) => el("label", { class: "field" }, el("span", { text: label }), input, hint ? el("span", { class: "hint", text: hint }) : null);
  f.claim = el("textarea", { maxlength: 400, placeholder: "e.g. UK youth unemployment will reach 20% before 2030" });
  f.series = el("select", {});
  const groups = new Map();
  for (const s of S.catalog.series.filter((x) => !x.hidden)) {
    const g = s.sector ? `${s.country} · job postings by sector` : `${s.country} · ${s.topic}`;
    if (!groups.has(g)) groups.set(g, []);
    groups.get(g).push(s);
  }
  f.series.append(el("option", { value: "", text: "Choose the data that settles it…" }),
    ...[...groups.entries()].map(([g, list]) => el("optgroup", { label: g }, list.map((s) => el("option", { value: s.id, text: s.sector || s.name })))));
  f.test = el("select", {}, el("option", { value: "reach", text: "hits a level at any point before the deadline" }),
    el("option", { value: "level", text: "is at a level on the deadline" }),
    el("option", { value: "change", text: "changes by a percentage between two dates" }));
  f.op = el("select", {}, el("option", { value: ">=", text: "at or above" }), el("option", { value: "<=", text: "at or below" }));
  f.value = el("input", { type: "number", step: "any", style: { width: "120px" } });
  f.start = el("input", { type: "date", value: TODAY });
  f.end = el("input", { type: "date", value: "2030-09-01" });
  f.conf = el("input", { type: "range", min: 1, max: 99, value: 50 });
  const confOut = el("b", { text: "50%" });
  f.conf.addEventListener("input", () => { confOut.textContent = `${f.conf.value}%`; });
  f.notes = el("textarea", { maxlength: 2000, placeholder: "Why you think this (optional). Useful when you look back." });
  const latest = el("span", { class: "hint" });
  const unitHint = el("span", { class: "hint" });
  const preview = el("p", { class: "small muted" });
  const err = el("p", { class: "error", role: "alert" });
  const startField = field("Start", f.start);
  const syncForm = async () => {
    const s = S.byId[f.series.value];
    startField.classList.toggle("hidden", f.test.value === "level");
    unitHint.textContent = f.test.value === "change" ? "% change (use a minus sign for a fall)" : s ? s.unit : "";
    latest.textContent = "";
    if (s) {
      const [d] = await loadSeries([s.id]);
      const p = d.points && d.points.length ? d.points[d.points.length - 1] : null;
      latest.textContent = p ? `Latest: ${fmtUnit(p[1], s.unit)} (${s.unit.startsWith("index") ? dayLabel(p[0]) : monthLabel(p[0])})` : (d.error || "");
    }
    const c = readCheck();
    preview.textContent = c && c.series && isFinite(c.value ?? c.pct) && c.end ? `Scored as true if ${describeCheck(c)}.` : "";
  };
  const readCheck = () => {
    const c = { series: f.series.value, test: f.test.value, op: f.op.value, start: f.test.value === "level" ? null : f.start.value, end: f.end.value };
    if (c.test === "change") c.pct = parseFloat(f.value.value); else c.value = parseFloat(f.value.value);
    return c;
  };
  for (const k of ["series", "test", "op", "value", "start", "end"]) f[k].addEventListener(k === "value" ? "input" : "change", syncForm);
  const fill = (item) => {
    const c = item.check || item.checks[0];
    f.claim.value = item.claim || "";
    f.series.value = c.series; f.test.value = c.test; f.op.value = c.op;
    f.value.value = c.test === "change" ? c.pct : c.value;
    f.start.value = c.start || TODAY; f.end.value = c.end || "";
    f.conf.value = item.confidence || 50; confOut.textContent = `${f.conf.value}%`;
    f.notes.value = item.notes || "";
    syncForm();
  };
  const reset = () => {
    editing = null; form.reset(); f.start.value = TODAY; f.end.value = "2030-09-01"; f.conf.value = 50; confOut.textContent = "50%";
    $("#form-title").textContent = "New prediction"; submit.textContent = "Save prediction"; cancel.classList.add("hidden"); err.textContent = ""; syncForm();
  };
  const submit = el("button", { class: "btn primary", type: "submit", text: "Save prediction" });
  const cancel = el("button", { class: "btn hidden", type: "button", text: "Cancel", onclick: reset });
  form.append(
    el("div", { class: "field" }, el("span", { class: "small", style: { fontWeight: 560, color: "var(--ink-2)" }, text: "Start from an idea (then make it yours)" }),
      el("div", { class: "ideas" }, IDEAS.map((idea) => el("button", { type: "button", class: "btn small", text: idea.label,
        onclick: () => { fill({ ...idea, confidence: 50 }); f.claim.focus(); } })))),
    field("Your prediction", f.claim),
    el("div", { class: "row" }, field("Settled by", f.series, ""), latest),
    el("div", { class: "row" }, field("Came true if it", f.test), field("", f.op), field("Threshold", f.value), unitHint),
    el("div", { class: "row" }, startField, field("Deadline", f.end),
      field("Your confidence it comes true", el("span", { style: { display: "flex", gap: "8px", alignItems: "center" } }, f.conf, confOut))),
    preview,
    field("Notes", f.notes),
    err,
    el("div", { class: "row" }, submit, cancel));
  form.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    err.textContent = "";
    const item = { claim: f.claim.value, confidence: +f.conf.value, notes: f.notes.value, check: readCheck() };
    if (editing) { item.id = editing.id; item.madeOn = editing.madeOn; }
    try {
      data = await api("/api/mine", { action: editing ? "update" : "add", item });
      reset(); drawList();
    } catch (e) { err.textContent = e.message; }
  });

  const drawList = () => {
    const items = data.items;
    const resolved = items.filter((i) => i.status === "true" || i.status === "false");
    statsBox.replaceChildren(
      el("div", { class: "card stat" }, el("div", { class: "v", text: items.length }), el("div", { class: "l", text: "Predictions logged" })),
      el("div", { class: "card stat" }, el("div", { class: "v", text: `${resolved.filter((i) => i.status === "true").length} / ${resolved.length}` }), el("div", { class: "l", text: "Came true / resolved" })),
      el("div", { class: "card stat" }, el("div", { class: "v", text: data.brier ? data.brier.score.toFixed(3) : "–" }),
        el("div", { class: "l", text: data.brier ? `Brier score over ${data.brier.n} resolved (0 is perfect; 0.25 is what always guessing 50% gets)` : "Brier score: appears once a prediction resolves. Lower is better." })));
    if (!items.length) {
      listBox.replaceChildren(el("div", { class: "card empty", text: "No predictions yet. Start from an idea above, or write your own. A good prediction has a number, a date and a source." }));
      return;
    }
    listBox.replaceChildren(...items.map((item) => {
      const r = (item.results || [])[0] || {};
      const charts = el("div");
      lazy(charts, () => predictionCharts({ ...item, date: item.madeOn }, charts));
      return el("article", { class: "card pred" },
        el("div", { class: "pred-head" },
          el("div", { class: "who" }, el("b", { text: `${item.confidence}% confident` }), el("span", { class: "muted", text: ` · made ${dayLabel(item.madeOn)}` })),
          chip(item.status),
          el("button", { class: "btn small", type: "button", text: "Edit", onclick: () => {
            editing = item; fill(item); $("#form-title").textContent = "Edit prediction"; submit.textContent = "Save changes";
            cancel.classList.remove("hidden"); form.scrollIntoView({ behavior: "smooth", block: "start" }); } }),
          el("button", { class: "btn small ghost", type: "button", text: "Delete", onclick: async () => {
            if (!confirm("Delete this prediction? This can't be undone.")) return;
            data = await api("/api/mine", { action: "delete", id: item.id }); drawList(); } })),
        el("p", { class: "claim", text: item.claim }),
        el("p", { class: "small muted", text: `Came true if ${describeCheck(item.checks[0])}.` }),
        r.status ? resultRow(r, item.checks[0]) : null,
        item.notes ? el("p", { class: "lesson", text: item.notes }) : null,
        charts);
    }));
  };
  reset();
  drawList();
}

// ======================================================================
// Router, theme, refresh
// ======================================================================

const TABS = { overview: renderOverview, famous: renderFamous, forecasts: renderForecasts, salaries: renderSalaries, data: renderData, mine: renderMine };

function route() {
  const [name, query] = (location.hash.slice(1) || "overview").split("?");
  const tab = TABS[name] ? name : "overview";
  for (const b of document.querySelectorAll("nav.tabs button")) b.setAttribute("aria-selected", String(b.dataset.tab === tab));
  for (const s of document.querySelectorAll("section.tab")) s.classList.toggle("active", s.id === `tab-${tab}`);
  const params = new URLSearchParams(query || "");
  const root = $(`#tab-${tab}`);
  if (!S.rendered[tab] || [...params.keys()].length) {
    S.rendered[tab] = true;
    TABS[tab](root, params).catch((e) => {
      S.rendered[tab] = false;
      root.replaceChildren(el("div", { class: "notice", text: `Couldn't load this page: ${e.message}. Is the app still running?` }));
    });
  }
  window.scrollTo(0, 0);
}

for (const b of document.querySelectorAll("nav.tabs button")) b.addEventListener("click", () => { location.hash = b.dataset.tab; });
window.addEventListener("hashchange", route);

const themeBtn = $("#theme");
const effectiveDark = () => (document.documentElement.dataset.theme || (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light")) === "dark";
const syncThemeLabel = () => { themeBtn.textContent = effectiveDark() ? "Light mode" : "Dark mode"; };
themeBtn.addEventListener("click", () => {
  const next = effectiveDark() ? "light" : "dark";
  document.documentElement.dataset.theme = next;
  try { localStorage.setItem("rc-theme", next); } catch (e) { /* private mode */ }
  syncThemeLabel();
});
syncThemeLabel();

$("#refresh").addEventListener("click", async () => {
  const btn = $("#refresh");
  btn.disabled = true;
  notice("Fetching the latest figures from ONS, FRED, Indeed, the OBR and the Philadelphia Fed. Sources are asked one at a time, so this takes about a minute.");
  try {
    await api("/api/refresh", {});
    setTimeout(() => {
      S.series.clear(); S.famous = null; S.rendered = {};
      notice(""); btn.disabled = false; route();
    }, 45000);
  } catch (e) {
    notice(`Refresh failed: ${e.message}`, "error"); btn.disabled = false;
  }
});

route();
