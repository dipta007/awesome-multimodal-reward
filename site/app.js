"use strict";

const DATA = window.SURVEY_DATA;
const PAPERS = DATA.papers;
const SURVEY = DATA.survey;
const BY_KEY = new Map(PAPERS.map((p) => [p.key, p]));
const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

const LABELS = {
  direction: { understanding: "Understanding", generation: "Generation" },
  signal: { scalar: "Scalar score", critique: "Generated critique", rubric: "Rubric", implicit: "Likelihood-derived",
    programmatic: "Programmatic check", latent: "Latent score" },
  supervision: { human: "Human comparisons", ai: "AI feedback", perturbation: "Perturbations",
    verifiable: "Verifiable targets", self: "Self-generated" },
  granularity: { outcome: "Outcome", process: "Step", token: "Token or region", criterion: "Criterion" },
  roles: { train: "Policy training", select: "Candidate selection", data: "Data curation", agent: "Agent verification" },
  kind: { method: "Method", benchmark: "Benchmark", survey: "Survey" },
};
const FACETS = [
  { id: "section", title: "Survey section", open: true },
  { id: "direction", title: "Direction", open: true },
  { id: "signal", title: "Signal construction" },
  { id: "supervision", title: "Supervision" },
  { id: "granularity", title: "Granularity" },
  { id: "roles", title: "Deployment role" },
  { id: "modality", title: "Modality" },
  { id: "failure", title: "Failure" },
  { id: "kind", title: "Type" },
  { id: "review", title: "Status" },
];
const SECTION_TITLE = Object.fromEntries(SURVEY.sections.map((s) => [s.id, s.title]));
const SUB_TITLE = Object.fromEntries(SURVEY.sections.flatMap((s) => s.subsections.map((x) => [`${s.id}/${x.id}`, x.title])));
const SECTION_INDEX = Object.fromEntries(SURVEY.sections.map((s, i) => [s.id, i]));
const FAILURE_BY_NAME = Object.fromEntries(SURVEY.failures.map((f) => [f.name, f]));

const NARROW = matchMedia("(max-width: 980px)");
const state = { tab: "papers", query: "", sort: "relevance", filters: {}, selected: null, methodDirection: "all", failureFilter: "all", failure: null };

const STOP = new Set("a an and are as at be by for from in into is it its of on or that the this to with we our via using".split(" "));
const tokenize = (s) => (s || "").toLowerCase().normalize("NFKD").replace(/[^\p{L}\p{N}]+/gu, " ").split(" ").filter((t) => t && !STOP.has(t));

const FIELDS = [["name", 3], ["title", 2.5], ["tagtext", 1.5], ["abstract", 1]];
const DOCS = PAPERS.map((p) => {
  const tagtext = Object.values(p.tags || {}).flat().map((v) => v.replace(/-/g, " ")).join(" ");
  const fields = { name: tokenize(p.name), title: tokenize(p.title), tagtext: tokenize(tagtext), abstract: tokenize(p.abstract) };
  const tf = {};
  for (const [f, w] of FIELDS) for (const t of fields[f]) tf[t] = (tf[t] || 0) + w;
  const len = FIELDS.reduce((a, [f, w]) => a + fields[f].length * w, 0);
  const lower = `${p.name || ""} ${p.title} ${p.abstract || ""}`.toLowerCase();
  return { key: p.key, tf, len, lower };
});
const AVG = DOCS.reduce((a, d) => a + d.len, 0) / DOCS.length;
const DF = {};
for (const d of DOCS) for (const t of Object.keys(d.tf)) DF[t] = (DF[t] || 0) + 1;
const VOCAB = Object.keys(DF);
const idf = (t) => Math.log(1 + (DOCS.length - (DF[t] || 0) + 0.5) / ((DF[t] || 0) + 0.5));

function parseQuery(q) {
  const phrases = [...q.matchAll(/"([^"]+)"/g)].map((m) => m[1].toLowerCase());
  const terms = tokenize(q.replace(/"[^"]+"/g, " "));
  return { phrases, terms };
}

function expand(term, isLast) {
  if (!isLast || term.length < 3) return [term];
  const hits = VOCAB.filter((v) => v.startsWith(term)).slice(0, 30);
  return hits.length ? hits : [term];
}

function score(query) {
  const { phrases, terms } = parseQuery(query);
  const out = new Map();
  if (!terms.length && !phrases.length) return out;
  for (const d of DOCS) {
    if (phrases.some((ph) => !d.lower.includes(ph))) continue;
    let s = 0, matched = 0;
    terms.forEach((t, i) => {
      let best = 0;
      for (const v of expand(t, i === terms.length - 1)) {
        const f = d.tf[v];
        if (!f) continue;
        const k1 = 1.2, b = 0.75;
        best = Math.max(best, idf(v) * (f * (k1 + 1)) / (f + k1 * (1 - b + b * d.len / AVG)));
      }
      if (best > 0) matched++;
      s += best;
    });
    if (terms.length && matched < Math.ceil(terms.length * 0.6)) continue;
    out.set(d.key, s + phrases.length * 5);
  }
  return out;
}

let VECS = null;
function vectors() {
  if (VECS) return VECS;
  VECS = new Map();
  for (const p of PAPERS) {
    const tf = {};
    for (const t of tokenize(`${p.title} ${p.title} ${p.abstract || ""}`)) tf[t] = (tf[t] || 0) + 1;
    const v = {};
    let norm = 0;
    for (const [t, f] of Object.entries(tf)) { v[t] = (1 + Math.log(f)) * idf(t); norm += v[t] ** 2; }
    norm = Math.sqrt(norm) || 1;
    for (const t in v) v[t] /= norm;
    VECS.set(p.key, v);
  }
  return VECS;
}
function similarTo(key, k = 5) {
  const vs = vectors(), a = vs.get(key);
  return PAPERS.filter((p) => p.key !== key)
    .map((p) => { const b = vs.get(p.key); let s = 0; for (const t in a) if (b[t]) s += a[t] * b[t]; return [p, s]; })
    .sort((x, y) => y[1] - x[1]).slice(0, k).map(([p]) => p);
}

function valuesOf(p, facet) {
  if (facet === "section") return [p.section];
  if (facet === "review") return [p.peer_reviewed ? "Peer reviewed" : "Preprint"];
  return (p.tags || {})[facet] || [];
}
function labelOf(facet, v) {
  if (facet === "section") return SECTION_TITLE[v] || v;
  return (LABELS[facet] && LABELS[facet][v]) || v;
}
function passes(p, except) {
  for (const [facet, set] of Object.entries(state.filters)) {
    if (facet === except || !set.size) continue;
    if (!valuesOf(p, facet).some((v) => set.has(v))) return false;
  }
  return true;
}

function renderFacets() {
  const host = $("#facets");
  const openNow = new Set($$(".facet[open]", host).map((d) => d.dataset.facet));
  host.innerHTML = "";
  for (const f of FACETS) {
    const counts = new Map();
    const all = new Set();
    for (const p of PAPERS) for (const v of valuesOf(p, f.id)) all.add(v);
    for (const p of PAPERS) if (passes(p, f.id) && matchesQuery(p)) for (const v of valuesOf(p, f.id)) counts.set(v, (counts.get(v) || 0) + 1);
    if (!all.size) continue;
    let opts = [...all];
    if (f.id === "section") opts.sort((a, b) => SECTION_INDEX[a] - SECTION_INDEX[b]);
    else opts.sort((a, b) => (counts.get(b) || 0) - (counts.get(a) || 0) || labelOf(f.id, a).localeCompare(labelOf(f.id, b)));
    const sel = state.filters[f.id] || new Set();
    const det = document.createElement("details");
    det.className = "facet";
    det.dataset.facet = f.id;
    det.open = openNow.size ? openNow.has(f.id) || sel.size > 0 : !!f.open || sel.size > 0;
    det.innerHTML = `<summary>${f.title}</summary><ul class="facet-options"></ul>`;
    const ul = $("ul", det);
    for (const v of opts) {
      const n = counts.get(v) || 0;
      const li = document.createElement("li");
      if (!n && !sel.has(v)) li.className = "zero";
      li.innerHTML = `<label><input type="checkbox" ${sel.has(v) ? "checked" : ""}><span>${esc(labelOf(f.id, v))}</span><span class="n">${n}</span></label>`;
      $("input", li).addEventListener("change", (e) => toggleFilter(f.id, v, e.target.checked));
      ul.append(li);
    }
    host.append(det);
  }
}

function toggleFilter(facet, value, on) {
  const set = state.filters[facet] || (state.filters[facet] = new Set());
  on ? set.add(value) : set.delete(value);
  if (!set.size) delete state.filters[facet];
  renderPapers();
  writeHash();
}

let SCORES = new Map();
const matchesQuery = (p) => !state.query.trim() || SCORES.has(p.key);

function renderPapers() {
  SCORES = score(state.query);
  let list = PAPERS.filter((p) => passes(p) && matchesQuery(p));
  const bySection = (a, b) => SECTION_INDEX[a.section] - SECTION_INDEX[b.section] || b.year - a.year;
  const sorts = {
    relevance: (a, b) => state.query.trim() ? (SCORES.get(b.key) - SCORES.get(a.key)) : bySection(a, b),
    newest: (a, b) => b.year - a.year || a.title.localeCompare(b.title),
    section: bySection,
    title: (a, b) => a.title.localeCompare(b.title),
  };
  list.sort(sorts[state.sort]);
  state.visible = list;

  const n = list.length;
  $("#result-count").innerHTML = `<strong>${n}</strong> of ${PAPERS.length} papers`;
  const active = Object.values(state.filters).reduce((a, set) => a + set.size, 0);
  $(".filters-toggle").textContent = active ? `Filters (${active})` : "Filters";
  $(".filters-done button").textContent = `Show ${n} papers`;
  renderActiveChips();

  const ol = $("#paper-list");
  ol.innerHTML = "";
  if (!n) {
    ol.innerHTML = `<li class="empty"><strong>No papers match.</strong>Remove a filter or try fewer words. Quotes search for an exact phrase.</li>`;
  }
  const terms = parseQuery(state.query).terms;
  for (const p of list) {
    const li = document.createElement("li");
    li.className = "paper";
    li.tabIndex = 0;
    li.dataset.key = p.key;
    li.setAttribute("aria-selected", String(state.selected === p.key));
    const name = p.name && !p.title.toLowerCase().startsWith(p.name.toLowerCase()) ? `<span class="name">${esc(p.name)}: </span>` : "";
    li.innerHTML = `
      <p class="paper-title">${name}${highlight(p.title, terms)}</p>
      <span class="paper-meta">${esc(p.venue || "")} ${p.year}</span>
      <div class="paper-tags">${tagChips(p)}</div>`;
    li.addEventListener("click", () => openPaper(p.key));
    li.addEventListener("keydown", (e) => { if (e.key === "Enter") openPaper(p.key); });
    ol.append(li);
  }
  renderFacets();
}

function renderActiveChips() {
  let host = $(".chips-active");
  if (!host) {
    host = document.createElement("div");
    host.className = "chips-active";
    $(".results-bar").after(host);
  }
  host.innerHTML = "";
  for (const [facet, set] of Object.entries(state.filters)) {
    for (const v of set) {
      const b = document.createElement("button");
      b.type = "button";
      b.className = "chip-remove";
      b.textContent = `${labelOf(facet, v)} ×`;
      b.setAttribute("aria-label", `Remove filter ${labelOf(facet, v)}`);
      b.addEventListener("click", () => toggleFilter(facet, v, false));
      host.append(b);
    }
  }
}

function tagChips(p) {
  const t = p.tags || {};
  const chips = [];
  for (const facet of ["direction", "signal", "supervision", "granularity", "roles"]) for (const v of t[facet] || []) chips.push(`<span class="tag">${esc(labelOf(facet, v))}</span>`);
  for (const v of t.modality || []) chips.push(`<span class="tag">${esc(v)}</span>`);
  for (const v of t.failure || []) {
    const f = FAILURE_BY_NAME[v];
    const cls = f && f.perception === "fail" && f.preference === "fail" ? "failure-b" : f && f.perception === "fail" ? "failure-p" : f && f.preference === "fail" ? "failure-f" : "";
    chips.push(`<span class="tag ${cls}">${esc(v)}</span>`);
  }
  return chips.slice(0, 8).join("");
}

function openPaper(key, fromTab) {
  const p = BY_KEY.get(key);
  if (!p) return;
  state.selected = key;
  $$(".paper").forEach((el) => el.setAttribute("aria-selected", String(el.dataset.key === key)));
  const authors = p.authors || [];
  const who = authors.length > 6 ? `${authors.slice(0, 6).join(", ")}, and ${authors.length - 6} more` : authors.join(", ");
  const links = [];
  if (p.links.paper) links.push(`<a href="${attr(p.links.paper)}" target="_blank" rel="noopener">Paper</a>`);
  if (p.links.arxiv && p.links.arxiv !== p.links.paper) links.push(`<a href="${attr(p.links.arxiv)}" target="_blank" rel="noopener">arXiv</a>`);
  const sub = SUB_TITLE[`${p.section}/${p.subsection}`];
  const rows = [];
  for (const facet of ["direction", "signal", "supervision", "granularity", "roles", "modality", "failure"]) {
    const vs = (p.tags || {})[facet];
    if (vs && vs.length) rows.push(`<dt>${FACETS.find((f) => f.id === facet).title}</dt><dd>${vs.map((v) => esc(labelOf(facet, v))).join(", ")}</dd>`);
  }
  const sim = similarTo(key);
  $("#drawer-body").innerHTML = `
    <h2>${p.name && !p.title.toLowerCase().startsWith(p.name.toLowerCase()) ? esc(p.name) + ": " : ""}${esc(p.title)}</h2>
    <p class="who">${esc(who)}<br>${esc(p.venue || "")} ${p.year}${p.peer_reviewed ? "" : ", preprint"}</p>
    <p class="placement">Discussed in <a href="#papers" data-goto-section="${attr(p.section)}">${esc(SECTION_TITLE[p.section])}</a>${sub ? `, ${esc(sub)}` : ""}.</p>
    <div class="links">${links.join("")}</div>
    ${rows.length ? `<dl>${rows.join("")}</dl>` : ""}
    <h3>Abstract</h3>
    ${p.abstract ? `<p class="abstract">${esc(p.abstract)}</p>` : `<p class="abstract missing">No abstract was found for this paper. Follow the paper link to read it.</p>`}
    <h3>Similar papers</h3>
    <ul class="similar">${sim.map((s) => `<li><button type="button" data-open="${attr(s.key)}">${esc(s.title)}</button> <span class="why">${esc(s.venue || "")} ${s.year}</span></li>`).join("")}</ul>
    <h3>BibTeX <button type="button" class="link-button" data-copy-bib>Copy</button></h3>
    <pre class="bibtex">${esc(p.bibtex || "")}</pre>`;
  $$("[data-open]", $("#drawer-body")).forEach((b) => b.addEventListener("click", () => openPaper(b.dataset.open)));
  $("[data-goto-section]", $("#drawer-body")).addEventListener("click", (e) => {
    e.preventDefault();
    state.filters = { section: new Set([p.section]) };
    state.query = "";
    $("#search").value = "";
    closeDrawer();
    showTab("papers");
  });
  $("[data-copy-bib]", $("#drawer-body")).addEventListener("click", (e) => copy(p.bibtex, e.target));
  const drawer = $("#drawer");
  drawer.hidden = false;
  drawer.scrollTop = 0;
  $(".drawer-close").focus({ preventScroll: true });
  writeHash();
}

function closeDrawer() {
  $("#drawer").hidden = true;
  const back = state.selected && $(`.paper[data-key="${CSS.escape(state.selected)}"]`);
  state.selected = null;
  $$(".paper").forEach((el) => el.setAttribute("aria-selected", "false"));
  if (back) back.focus({ preventScroll: true });
  writeHash();
}

function renderTaxonomy() {
  const host = $("#taxonomy");
  host.innerHTML = "";
  for (const group of SURVEY.taxonomy) {
    const g = document.createElement("div");
    g.className = "taxonomy-group";
    g.innerHTML = `<h3>${esc(group.name)}</h3><div class="branches"></div>`;
    for (const br of group.branches) {
      const targets = br.leaves.map((l) => leafTarget(br.name, l.name));
      const n = PAPERS.filter((p) => targets.some((t) => matchesTarget(p, t))).length;
      const el = document.createElement("div");
      el.className = "branch";
      el.innerHTML = `<h4>${esc(br.name)}<span>${n} papers</span></h4><ul class="leaves"></ul>`;
      for (const leaf of br.leaves) {
        const target = leafTarget(br.name, leaf.name);
        const count = PAPERS.filter((p) => matchesTarget(p, target)).length;
        const li = document.createElement("li");
        li.className = "leaf";
        li.innerHTML = `<button type="button"><span class="leaf-name">${esc(leaf.name)}</span><span class="leaf-n">${count}</span><span class="leaf-works">${leaf.works.map((w) => esc(w.name)).join(", ")}</span></button>`;
        $("button", li).addEventListener("click", () => {
          state.filters = { [target.facet]: new Set(target.values) };
          state.query = "";
          $("#search").value = "";
          showTab("papers");
        });
        $(".leaves", el).append(li);
      }
      $(".branches", g).append(el);
    }
    host.append(g);
  }
}
const BRANCH_SECTION = { "Signal construction": "signal", Supervision: "supervision", Granularity: "granularity",
  Deployment: "roles", Modality: "understanding", Evaluation: "benchmarks", "Failure diagnosis": "failures" };
const sectionForBranch = (name) => BRANCH_SECTION[name] || "foundations";
const LEAF_TARGETS = {
  "Scalar scores": ["signal", "scalar"], "Generated critique": ["signal", "critique"], Rubric: ["signal", "rubric"],
  "Likelihood-derived score": ["signal", "implicit"], "Programmatic check": ["signal", "programmatic"], "Latent score": ["signal", "latent"],
  "Human comparisons": ["supervision", "human"], "AI feedback": ["supervision", "ai"], Perturbations: ["supervision", "perturbation"],
  "Verifiable targets": ["supervision", "verifiable"], "Self-generated signals": ["supervision", "self"],
  Outcome: ["granularity", "outcome"], "Reasoning / action step": ["granularity", "process"], "Token / region": ["granularity", "token"],
  "Criterion / dimension": ["granularity", "criterion"], "Policy training": ["roles", "train"], "Candidate selection": ["roles", "select"],
  "Data curation": ["roles", "data"], "Agent verification": ["roles", "agent"], "Non-text evidence": ["direction", "understanding"],
  "Non-text output": ["direction", "generation"], "Both (unified, omni)": ["section", "transfer"], "Transfer across settings": ["section", "transfer"],
  Benchmarks: ["kind", "benchmark"], "Downstream evidence": ["section", "benchmarks"], "Annotator population, language": ["section", "benchmarks"],
};
function leafTarget(branch, leaf) {
  if (branch === "Failure diagnosis") {
    const hit = (f) => leaf === "Perception" ? f.perception === "fail" : leaf === "Preference" ? f.preference === "fail" : f.group === leaf;
    return { facet: "failure", values: SURVEY.failures.filter(hit).map((f) => f.name) };
  }
  const [facet, value] = LEAF_TARGETS[leaf] || ["section", sectionForBranch(branch)];
  return { facet, values: [value] };
}
const matchesTarget = (p, t) => valuesOf(p, t.facet).some((v) => t.values.includes(v));

let methodSort = { col: "name", dir: 1 };
const METHOD_COLS = [["name", "Method"], ["direction", "Direction"], ["construction", "Construction"], ["supervision", "Supervision"],
  ["granularity", "Granularity"], ["modality", "Modality"], ["roles", "Roles"]];
function renderMethods() {
  const seg = $("#method-direction");
  if (!seg.childElementCount) {
    for (const [v, label] of [["all", "All"], ["understanding", "Understanding"], ["generation", "Generation"]]) {
      const b = document.createElement("button");
      b.type = "button";
      b.textContent = label;
      b.dataset.v = v;
      b.addEventListener("click", () => { state.methodDirection = v; renderMethods(); });
      seg.append(b);
    }
  }
  $$("button", seg).forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.v === state.methodDirection)));
  const rows = SURVEY.methods.filter((m) => state.methodDirection === "all" || m.direction === state.methodDirection)
    .sort((a, b) => methodSort.dir * String(a[methodSort.col]).localeCompare(String(b[methodSort.col])));
  const t = $("#methods-table");
  t.innerHTML = `<caption class="visually-hidden">Methods compared on the survey's attributes</caption><thead><tr>${METHOD_COLS.map(([c, l]) =>
    `<th scope="col"><button type="button" data-col="${c}" ${methodSort.col === c ? `aria-sort="${methodSort.dir > 0 ? "ascending" : "descending"}"` : ""}>${l}</button></th>`).join("")}</tr></thead>
    <tbody>${rows.map((m) => `<tr data-open="${attr(m.key)}" tabindex="0"><td class="method-name">${esc(m.name)}</td>${METHOD_COLS.slice(1).map(([c, l]) =>
      `<td data-label="${l}">${esc(c === "direction" ? LABELS.direction[m.direction] : m[c])}</td>`).join("")}</tr>`).join("")}</tbody>`;
  $$("thead button", t).forEach((b) => b.addEventListener("click", () => {
    methodSort = { col: b.dataset.col, dir: methodSort.col === b.dataset.col ? -methodSort.dir : 1 };
    renderMethods();
  }));
  bindRowOpen(t);
}

function renderBenchmarks() {
  const ev = $("#evidence");
  ev.innerHTML = `<h3>Does offline accuracy predict use?</h3>
    <p>Few studies test the link. Each one keeps its own metric, so compare within a study only.</p>
    <div class="evidence-rows">${SURVEY.evidence.map((e) => `
      <button type="button" class="ev" data-open="${attr(e.key)}">
        <span class="ev-use">${esc(e.use)}</span>
        <span class="ev-name">${esc(e.name)}</span>
        <span class="ev-link">${esc(e.link)}</span>
        <span class="ev-holds ${/mixed/i.test(e.holds) ? "mixed" : ""}">Link holds: ${esc(e.holds)}</span>
      </button>`).join("")}</div>`;
  $$("[data-open]", ev).forEach((b) => b.addEventListener("click", () => openPaper(b.dataset.open)));
  const t = $("#bench-table");
  let group = null, body = "";
  for (const b of SURVEY.benchmarks) {
    if (b.group !== group) { group = b.group; body += `<tr class="group-row"><td colspan="6">${esc(group)}</td></tr>`; }
    const note = b.note ? ` <span class="note">(${esc(b.note)})</span>` : "";
    body += `<tr data-open="${attr(b.key)}" tabindex="0"><td class="method-name">${esc(b.name)}${note}</td><td data-label="Input to output">${esc(b.input_output)}</td><td data-label="Format">${esc(b.format)}</td><td data-label="Labels">${esc(b.labels)}</td><td class="num" data-label="Scale">${esc(b.scale)}</td><td data-label="Metric">${esc(b.metric)}</td></tr>`;
  }
  t.innerHTML = `<caption class="visually-hidden">Benchmarks for multimodal reward models and judges</caption><thead><tr><th scope="col">Benchmark</th><th scope="col">Input to output</th><th scope="col">Format</th><th scope="col">Labels</th><th scope="col">Scale</th><th scope="col">Metric</th></tr></thead><tbody>${body}</tbody>`;
  bindRowOpen(t);
}

function renderFailures() {
  const seg = $("#failure-filter");
  if (!seg.childElementCount) {
    for (const [v, label] of [["all", "All failures"], ["perception", "Breaks perception"], ["preference", "Breaks preference"]]) {
      const b = document.createElement("button");
      b.type = "button";
      b.textContent = label;
      b.dataset.v = v;
      b.addEventListener("click", () => { state.failureFilter = v; renderFailures(); });
      seg.append(b);
    }
  }
  $$("button", seg).forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.v === state.failureFilter)));
  const dot = (m, side) => m === "fail" ? `<span class="dot fail ${side}" role="img" aria-label="fails"></span>` : m === "either" ? `<span class="dot either" role="img" aria-label="either"></span>` : "";
  let group = null, body = "";
  SURVEY.failures.forEach((f, i) => {
    if (f.group !== group) { group = f.group; body += `<tr class="group-row"><td colspan="5">${esc(group)}</td></tr>`; }
    const hide = (state.failureFilter === "perception" && f.perception !== "fail") || (state.failureFilter === "preference" && f.preference !== "fail");
    const ex = BY_KEY.get(f.example);
    body += `<tr data-failure="${i}" tabindex="0" class="${hide ? "hidden-row" : ""}" aria-selected="${state.failure === i}">
      <td class="method-name">${esc(f.name)}</td><td class="mark" data-label="Perception">${dot(f.perception, "p")}</td><td class="mark" data-label="Preference">${dot(f.preference, "f")}</td>
      <td data-label="Practice">${esc(f.practice)}</td><td data-label="Example">${ex ? esc(shortCite(ex)) : esc(f.example)}${f.text_only ? ' <span class="text-only">(text only)</span>' : ""}</td></tr>`;
  });
  const t = $("#failure-table");
  t.innerHTML = `<caption class="visually-hidden">Failure catalog</caption><thead><tr><th scope="col">Failure</th><th scope="col" class="mark mark-p">Perception</th><th scope="col" class="mark mark-f">Preference</th><th scope="col">Recommended practice</th><th scope="col">Example study</th></tr></thead><tbody>${body}</tbody>`;
  $$("tr[data-failure]", t).forEach((tr) => {
    const pick = () => {
      state.failure = Number(tr.dataset.failure);
      renderFailures();
      if (NARROW.matches) $("#failure-detail").scrollIntoView({ block: "nearest" });
    };
    tr.addEventListener("click", pick);
    tr.addEventListener("keydown", (e) => { if (e.key === "Enter") pick(); });
  });
  renderFailureDetail();
  updateQuestions();
}

function renderFailureDetail() {
  const host = $("#failure-detail");
  const f = SURVEY.failures[state.failure];
  if (!f) {
    const fails = (q) => SURVEY.failures.filter((x) => x[q] === "fail").length;
    host.innerHTML = `<h3>Select a failure</h3><p>${fails("perception")} failures break perception and ${fails("preference")} break preference. Optimization and security rows can amplify or exploit either error.</p>`;
    return;
  }
  const breaks = [f.perception === "fail" ? '<span class="p">perception</span>' : "", f.preference === "fail" ? '<span class="f">preference</span>' : ""].filter(Boolean);
  const keys = [...new Set([f.example, ...(f.evidence || [])])].filter((k) => BY_KEY.has(k));
  host.innerHTML = `<h3>${esc(f.name)}</h3>
    <p class="breaks">${breaks.length ? `Breaks ${breaks.join(" and ")}` : "Can amplify or exploit either error"}</p>
    <p><strong>Recommended practice:</strong> ${esc(f.practice)}.</p>
    <p><strong>Evidence in the survey</strong></p>
    <ul>${keys.map((k) => `<li><button type="button" data-open="${attr(k)}">${esc(BY_KEY.get(k).title)}</button></li>`).join("")}</ul>`;
  $$("[data-open]", host).forEach((b) => b.addEventListener("click", () => openPaper(b.dataset.open)));
}

function updateQuestions() {
  const q = $("#questions");
  q.className = "questions";
  const f = state.tab === "failures" ? SURVEY.failures[state.failure] : null;
  $$("[data-q-count]").forEach((el) => (el.textContent = ""));
  if (state.tab === "failures") {
    for (const side of ["perception", "preference"]) {
      const n = SURVEY.failures.filter((x) => x[side] === "fail").length;
      $(`[data-q-count="${side}"]`).textContent = `${n} failures`;
    }
  }
  if (!f) return;
  for (const side of ["perception", "preference"]) {
    if (f[side] === "either") q.classList.add(`open-${side}`);
    else if (f[side] !== "fail") q.classList.add(`dim-${side}`);
  }
}

function bindRowOpen(table) {
  $$("tr[data-open]", table).forEach((tr) => {
    tr.addEventListener("click", () => openPaper(tr.dataset.open));
    tr.addEventListener("keydown", (e) => { if (e.key === "Enter") openPaper(tr.dataset.open); });
  });
}
function shortCite(p) {
  const last = (p.authors && p.authors[0] ? p.authors[0].split(" ").pop() : "");
  return `${p.name ? p.name + ", " : ""}${last} et al., ${p.year}`;
}
function esc(s) { return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])); }
const attr = esc;
function highlight(text, terms) {
  let out = esc(text);
  for (const t of terms.filter((t) => t.length > 2)) out = out.replace(new RegExp(`\\b(${t.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}\\w*)`, "gi"), "<mark>$1</mark>");
  return out;
}
async function copy(text, button) {
  try { await navigator.clipboard.writeText(text); button.textContent = "Copied"; }
  catch { button.textContent = "Select the text to copy"; }
  setTimeout(() => (button.textContent = "Copy"), 1600);
}
function exportBib() {
  const list = state.visible || PAPERS;
  const blob = new Blob([list.map((p) => p.bibtex).join("\n\n") + "\n"], { type: "text/x-bibtex" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = "multimodal-reward-papers.bib";
  a.click();
  URL.revokeObjectURL(a.href);
}

function showTab(tab) {
  state.tab = tab;
  for (const b of $$(".tabs [role=tab]")) {
    const on = b.dataset.tab === tab;
    b.setAttribute("aria-selected", String(on));
    b.tabIndex = on ? 0 : -1;
  }
  for (const v of $$(".view")) v.hidden = v.id !== `view-${tab}`;
  if (tab === "papers") renderPapers();
  if (tab === "taxonomy") renderTaxonomy();
  if (tab === "methods") renderMethods();
  if (tab === "benchmarks") renderBenchmarks();
  if (tab === "failures") renderFailures();
  updateQuestions();
  writeHash();
  const top = $(".masthead").getBoundingClientRect().bottom + scrollY;
  if (scrollY > top) scrollTo(0, top);
}

function toggleFilters(open) {
  const wasOpen = $("#filters").classList.contains("is-open");
  $("#filters").classList.toggle("is-open", open);
  $(".filters-toggle").setAttribute("aria-expanded", String(open));
  document.body.classList.toggle("sheet-open", open);
  if (wasOpen && !open) $(".filters-toggle").focus({ preventScroll: true });
}

function writeHash() {
  const parts = [state.tab];
  const params = new URLSearchParams();
  if (state.query) params.set("q", state.query);
  for (const [f, set] of Object.entries(state.filters)) for (const v of set) params.append(f, v);
  if (state.selected) params.set("paper", state.selected);
  const qs = params.toString();
  history.replaceState(null, "", `#${parts.join("/")}${qs ? "?" + qs : ""}`);
}

function readHash() {
  const [path, qs] = location.hash.slice(1).split("?");
  const params = new URLSearchParams(qs || "");
  state.query = params.get("q") || "";
  state.filters = {};
  for (const f of FACETS) if (params.has(f.id)) state.filters[f.id] = new Set(params.getAll(f.id));
  $("#search").value = state.query;
  showTab(["papers", "taxonomy", "methods", "benchmarks", "failures"].includes(path) ? path : "papers");
  if (params.get("paper")) openPaper(params.get("paper"));
  else if (!$("#drawer").hidden) closeDrawer();
}

function init() {
  $$(".tabs [role=tab]").forEach((b) => b.addEventListener("click", () => showTab(b.dataset.tab)));
  $(".tabs").addEventListener("keydown", (e) => {
    const tabs = $$(".tabs [role=tab]");
    const i = tabs.findIndex((t) => t.dataset.tab === state.tab);
    if (e.key === "ArrowRight" || e.key === "ArrowLeft") {
      const next = tabs[(i + (e.key === "ArrowRight" ? 1 : tabs.length - 1)) % tabs.length];
      showTab(next.dataset.tab);
      next.focus();
    }
  });
  let timer;
  $("#search").addEventListener("input", (e) => {
    clearTimeout(timer);
    timer = setTimeout(() => {
      state.query = e.target.value;
      if (state.query && state.sort !== "relevance") { state.sort = "relevance"; $("#sort").value = "relevance"; }
      renderPapers();
      writeHash();
    }, 120);
  });
  $("#sort").addEventListener("change", (e) => { state.sort = e.target.value; renderPapers(); });
  $("[data-clear-filters]").addEventListener("click", () => { state.filters = {}; renderPapers(); writeHash(); });
  $("[data-export]").addEventListener("click", exportBib);
  $$("[data-toggle-filters]").forEach((b) => b.addEventListener("click", () => toggleFilters(!$("#filters").classList.contains("is-open"))));
  NARROW.addEventListener("change", () => toggleFilters(false));
  if (matchMedia("(hover: none), (max-width: 640px)").matches) $("#search").placeholder = "Search papers";
  $("[data-close-drawer]").addEventListener("click", closeDrawer);
  document.addEventListener("keydown", (e) => {
    const typing = /INPUT|TEXTAREA|SELECT/.test(document.activeElement.tagName);
    if (e.key === "/" && !typing) { e.preventDefault(); showTab("papers"); $("#search").focus(); }
    if (e.key === "Escape" && !$("#drawer").hidden) closeDrawer();
    else if (e.key === "Escape" && $("#filters").classList.contains("is-open")) toggleFilters(false);
    if (state.tab === "papers" && !typing && (e.key === "ArrowDown" || e.key === "ArrowUp")) {
      const items = $$(".paper");
      if (!items.length) return;
      const i = items.indexOf(document.activeElement);
      const next = items[Math.max(0, Math.min(items.length - 1, i + (e.key === "ArrowDown" ? 1 : -1)))];
      e.preventDefault();
      next.focus();
    }
  });
  window.addEventListener("hashchange", readHash);
  readHash();
}

init();
