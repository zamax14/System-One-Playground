import { $, watchModel } from "./common.js";

watchModel($("#model"));
const PRIORITY = { baja: "Baja", media: "Media", alta: "Alta", critica: "Crítica" };
const usd = new Intl.NumberFormat("es", { style: "currency", currency: "USD", maximumSignificantDigits: 2 });
let tickets = [], models = {}, saved = {}, suite, source, run;

function el(tag, attributes = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attributes)) node.setAttribute(key, value);
  node.append(...children);
  return node;
}

async function init() {
  const [status, desk] = await Promise.all([fetch("/api/status").then(r => r.json()), fetch("/api/tickets").then(r => r.json())]);
  tickets = desk.tickets;
  models = status.models;
  suite = status.benchmark;
  const snapshots = await Promise.all(["jev", "gpt-luna"].map(key =>
    fetch(`/results/${key}.json`).then(r => r.ok ? r.json() : null).catch(() => null)));
  for (const snapshot of snapshots) {
    if (snapshot?.status === "complete" && snapshot.suite === suite.suite && snapshot.fingerprint === suite.fingerprint)
      saved[snapshot.key] = snapshot;
  }
  for (const [key, m] of Object.entries(models)) {
    const box = el("input", { type: "checkbox", value: key });
    box.checked = !m.remote && m.status !== "error";
    box.disabled = m.remote || m.status === "error";
    const label = el("label", { title: m.error ?? "" }, box, m.name,
                     el("small", {}, m.remote ? (saved[key] ? "API · guardado" : "API · sin corrida") : "local"));
    $("#pick").append(label);
  }
  if (!Object.values(models).some(m => !m.remote && m.status !== "error")) {
    $("#run").disabled = true;
    $("#run").title = "Las corridas de Jev y Luna ya están guardadas; para medir un modelo local inicia sin --remote-only.";
  }
  showSaved();
}

function showSaved(keys = Object.keys(saved)) {
  run = { ...suite, created_at: new Date().toISOString(), models: { ...saved } };
  if (!keys.length) return;
  buildTable(keys);
  for (const key of Object.keys(saved))
    for (const row of saved[key].rows) fillRow({ key, ...row });
  renderCards();
  $("#download").hidden = false;
}

function setProgress(key, text) {
  let item = document.getElementById(`progress-${key}`);
  if (!item) $("#progress").append(item = el("li", { id: `progress-${key}` }, el("b", {}, models[key].name), " ", el("span")));
  item.querySelector("span").textContent = text;
}

function buildTable(keys) {
  const head = el("tr", {}, el("th", {}, "Ticket"), el("th", {}, "Referencia"), ...keys.map(k => el("th", {}, models[k].name)));
  const rows = tickets.map(t => {
    const details = el("details", {}, el("summary", {}, `${t.id} · ${t.titulo}`), el("p", {}, t.descripcion));
    const tr = el("tr", { "data-id": t.id }, el("td", {}, details), el("td", { class: "reference" }, "—"),
                  ...keys.map(k => el("td", { "data-model": k, class: "pending" }, "…")));
    tr.dataset.miss = "false";
    return tr;
  });
  $("#table").replaceChildren(el("thead", {}, head), el("tbody", {}, ...rows));
  $("#cases").hidden = false;
}

function fillRow(row) {
  const tr = $(`#table tr[data-id="${row.id}"]`);
  const reference = tr.querySelector(".reference");
  if (reference.textContent === "—") {
    reference.replaceChildren(row.expected_category ?? "ambiguo",
      el("small", {}, `Prioridad ${PRIORITY[row.expected_priority]} · ${row.expected_blocking ? "bloquea" : "no bloquea"}`));
  }
  const categoryOk = !row.expected_category || row.category === row.expected_category;
  const priorityOk = row.priority === row.expected_priority, blockingOk = (row.blocking >= .5) === row.expected_blocking;
  const mark = ok => ok ? "✓" : "✗";
  const cell = tr.querySelector(`[data-model="${row.key}"]`);
  cell.className = row.expected_category ? (categoryOk ? "hit" : "miss") : "";
  cell.replaceChildren(row.category,
    el("small", {}, el("span", { class: "dot", "data-color": row.light }), `${row.category_confidence} %`),
    el("small", {}, `Prioridad ${PRIORITY[row.priority]} ${mark(priorityOk)}`),
    el("small", {}, `Bloqueo ${Math.round(100 * row.blocking)} % ${mark(blockingOk)}`),
    el("small", {}, `${Math.round(row.latency_ms)} ms`));
  if (!(categoryOk && priorityOk && blockingOk)) tr.dataset.miss = "true";
}

const ratio = (a, b) => b ? a / b : 0;
// [etiqueta, texto, valor comparable, ¿más es mejor?, detalle]
const METRICS = [
  ["Categoría", s => `${s.category_correct}/${s.category_total}`, s => ratio(s.category_correct, s.category_total), true],
  ["Prioridad exacta", s => `${s.priority_correct}/${s.priority_total}`, s => ratio(s.priority_correct, s.priority_total), true,
   s => `a ±1 nivel: ${s.priority_near}/${s.priority_total}`],
  ["Bloqueo (noul)", s => `${s.blocking_correct}/${s.blocking_total}`, s => ratio(s.blocking_correct, s.blocking_total), true,
   s => `Brier ${s.blocking_brier}`],
  ["Aciertos en verde", s => `${s.lights.verde.correct}/${s.lights.verde.total}`, s => ratio(s.lights.verde.correct, s.lights.verde.total), true,
   s => `amarillo ${s.lights.amarillo.correct}/${s.lights.amarillo.total} · rojo ${s.lights.rojo.correct}/${s.lights.rojo.total}`],
  ["Latencia p50", s => `${Math.round(s.p50_latency_ms)} ms`, s => s.p50_latency_ms, false,
   s => `p95 ${Math.round(s.p95_latency_ms)} ms · media ${Math.round(s.mean_latency_ms)} ms`],
  ["Carga y calentamiento", s => `${s.load_s} s`, s => s.load_s, false],
  ["Costo", s => s.cost_usd == null ? "local" : usd.format(s.cost_usd), s => s.cost_usd ?? 0, false],
];

function renderCards() {
  const done = Object.values(run.models).filter(s => !s.error);
  const best = METRICS.map(([, , value, higher]) => done.length > 1 ? (higher ? Math.max : Math.min)(...done.map(value)) : null);
  $("#results").replaceChildren(...Object.values(run.models).map(s => {
    const where = s.status === "complete" ? `vía OpenRouter · guardado ${s.created_at.slice(0, 10)}` :
      s.device === "api" ? "vía OpenRouter" : s.device === "cuda" ? "en GPU" : s.device ? "en CPU" : "";
    const panel = el("section", { class: "panel result" }, el("h2", {}, s.name), el("p", { class: "where" }, where));
    if (!s.calibrated) panel.append(el("span", { class: "tag", title: "Sin logprobs: el modelo declara sus probabilidades" }, "confianza autodeclarada"));
    if (s.error) return panel.append(el("p", { class: "status" }, s.error)), panel;
    METRICS.forEach(([label, text, value, , detail], i) => {
      const row = el("p", { class: `metric${best[i] !== null && value(s) === best[i] ? " best" : ""}` },
                     el("span", {}, label, detail ? el("small", {}, detail(s)) : ""), el("b", {}, text(s)));
      panel.append(row);
    });
    return panel;
  }));
}

function finish(message) {
  source?.close();
  source = null;
  $("#run").disabled = false;
  $("#cancel").hidden = true;
  $("#download").hidden = !Object.keys(run?.models ?? {}).length;
  if (message) $("#progress").append(el("li", {}, message));
}

$("#run").addEventListener("click", () => {
  const keys = [...document.querySelectorAll("#pick input:checked")].map(box => box.value);
  if (!keys.length) return;
  const shown = [...new Set([...Object.keys(saved), ...keys])];
  showSaved(shown);
  $("#title").textContent = `Los mismos casos, ${shown.length} ${shown.length === 1 ? "modelo" : "modelos"}`;
  $("#run").disabled = true;
  $("#cancel").hidden = false;
  $("#download").hidden = true;
  $("#progress").replaceChildren();
  for (const key of keys) setProgress(key, "en cola");
  source = new EventSource(`/api/benchmark/stream?models=${keys.map(encodeURIComponent).join(",")}`);
  const on = (kind, handler) => source.addEventListener(kind, event => handler(JSON.parse(event.data)));
  on("start", ({ models: _keys, ...metadata }) => Object.assign(run, metadata));
  on("model", data => setProgress(data.key, data.status === "loading" ? "cargando…" : `0/${tickets.length}`));
  on("row", row => {
    fillRow(row);
    const count = document.querySelectorAll(`#table td[data-model="${row.key}"]:not(.pending)`).length;
    setProgress(row.key, `${count}/${tickets.length}`);
  });
  on("summary", summary => {
    run.models[summary.key] = summary;
    setProgress(summary.key, summary.error ? "falló" : "listo");
    renderCards();
  });
  on("done", () => finish());
  on("failed", message => finish(message));
  source.onerror = () => { if (source) finish("Se perdió la conexión con el servidor."); };
});

$("#cancel").addEventListener("click", () => finish("Cancelado: el modelo en curso se detiene en el siguiente ticket."));

$("#only-misses").addEventListener("change", event => $("#table").classList.toggle("only-misses", event.target.checked));

$("#download").addEventListener("click", () => {
  const url = URL.createObjectURL(new Blob([JSON.stringify(run, null, 2)], { type: "application/json" }));
  const link = el("a", { href: url, download: `pondera-${run.suite}-${run.created_at.slice(0, 10)}.json` });
  link.click();
  URL.revokeObjectURL(url);
});

init();
