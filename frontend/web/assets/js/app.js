/* =========================================================================
   BugHound dashboard — vanilla JS, no build step, no external libraries.
   Charts are hand-drawn SVG so the UI works offline and stays under 20 KB.
   ========================================================================= */
(() => {
  "use strict";

  const API = "/api";
  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

  const STAGES = [
    { node: "validate_input", label: "Input check" },
    { node: "knowledge_base_agent", label: "Knowledge base" },
    { node: "debug_agent", label: "Debug analysis" },
    { node: "research_agent", label: "Research" },
    { node: "root_cause_agent", label: "Root cause" },
    { node: "fix_agent", label: "Proposed fix" },
    { node: "code_reviewer", label: "Code review" },
    { node: "validation_agent", label: "Validation" },
    { node: "compose_report", label: "Final report" },
  ];

  const SKIPPED_ON_KB_HIT = [
    "debug_agent",
    "research_agent",
    "root_cause_agent",
    "fix_agent",
    "code_reviewer",
  ];

  const PALETTE = ["#1668e3", "#0b3c7e", "#2e86f0", "#7fb3f0", "#b9d6fa", "#4c6f9c"];

  const state = { config: null, lastResult: null, running: false };

  /* --------------------------------------------------------------- utils */
  const esc = (value) =>
    String(value ?? "").replace(/[&<>"']/g, (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])
    );

  const pct = (n) => `${Math.round((Number(n) || 0) * 100)}%`;

  const ms = (n) => (n >= 1000 ? `${(n / 1000).toFixed(1)}s` : `${n || 0}ms`);

  function toast(message) {
    const el = $("#toast");
    el.textContent = message;
    el.classList.add("is-visible");
    clearTimeout(toast._t);
    toast._t = setTimeout(() => el.classList.remove("is-visible"), 2600);
  }

  async function api(path, options) {
    const res = await fetch(API + path, options);
    if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
    return res.json();
  }

  /* ------------------------------------------------------------ navigation */
  function showView(name) {
    $$(".view").forEach((v) => v.classList.toggle("is-active", v.id === `view-${name}`));
    $$(".nav-item").forEach((b) => b.classList.toggle("is-active", b.dataset.view === name));
    $("#sidebar").classList.remove("is-open");
    window.scrollTo({ top: 0, behavior: "smooth" });
    if (name === "dashboard" || name === "feed") loadMetrics();
    if (name === "settings") loadFreeModels();
    if (name === "knowledge") loadKnowledgeBase();
  }

  $$(".nav-item").forEach((btn) =>
    btn.addEventListener("click", () => showView(btn.dataset.view))
  );
  $("#menu-btn").addEventListener("click", () => $("#sidebar").classList.toggle("is-open"));
  $("#btn-refresh").addEventListener("click", () => {
    loadMetrics();
    toast("Dashboard refreshed");
  });

  /* ---------------------------------------------------------------- charts */
  function lineChart(points) {
    const W = 640;
    const H = 190;
    const pad = { t: 14, r: 10, b: 24, l: 30 };
    const iw = W - pad.l - pad.r;
    const ih = H - pad.t - pad.b;

    if (!points.length) {
      return `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="No data yet">
        <text x="${W / 2}" y="${H / 2}" text-anchor="middle" fill="#9aa9bd" font-size="13"
          font-family="Inter, sans-serif">Run an investigation to plot confidence over time</text></svg>`;
    }

    const values = points.map((p) => Number(p.confidence) || 0);
    const x = (i) => pad.l + (points.length === 1 ? iw / 2 : (i / (points.length - 1)) * iw);
    const y = (v) => pad.t + ih - v * ih;

    const line = values.map((v, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(" ");
    const area = `${line} L${x(values.length - 1).toFixed(1)},${pad.t + ih} L${x(0).toFixed(1)},${pad.t + ih} Z`;

    const gridLines = [0, 0.25, 0.5, 0.75, 1]
      .map((g) => {
        const gy = y(g).toFixed(1);
        return `<line x1="${pad.l}" y1="${gy}" x2="${W - pad.r}" y2="${gy}" stroke="#e3eaf5" stroke-width="1"
          ${g === 0 ? "" : 'stroke-dasharray="3 4"'} />
          <text x="${pad.l - 8}" y="${Number(gy) + 3.5}" text-anchor="end" fill="#9aa9bd" font-size="10"
            font-family="JetBrains Mono, monospace">${g * 100}</text>`;
      })
      .join("");

    const threshold = state.config?.confidence_threshold ?? 0.8;
    const ty = y(threshold).toFixed(1);

    const dots = values
      .map((v, i) => {
        const fill = v >= threshold ? "#1668e3" : "#f2a93b";
        return `<circle cx="${x(i).toFixed(1)}" cy="${y(v).toFixed(1)}" r="3.4" fill="#fff"
          stroke="${fill}" stroke-width="2"><title>${pct(v)}</title></circle>`;
      })
      .join("");

    return `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Confidence per investigation">
      <defs>
        <linearGradient id="areaFill" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stop-color="#2e86f0" stop-opacity="0.26"/>
          <stop offset="100%" stop-color="#2e86f0" stop-opacity="0"/>
        </linearGradient>
      </defs>
      ${gridLines}
      <line x1="${pad.l}" y1="${ty}" x2="${W - pad.r}" y2="${ty}" stroke="#0b3c7e" stroke-width="1"
        stroke-dasharray="5 5" opacity="0.45"/>
      <text x="${W - pad.r}" y="${Number(ty) - 6}" text-anchor="end" fill="#0b3c7e" font-size="9.5"
        font-family="JetBrains Mono, monospace" opacity="0.7">gate ${pct(threshold)}</text>
      <path d="${area}" fill="url(#areaFill)"/>
      <path d="${line}" fill="none" stroke="#1668e3" stroke-width="2.2" stroke-linejoin="round" stroke-linecap="round"/>
      ${dots}
    </svg>`;
  }

  function donutChart(slices) {
    const size = 168;
    const r = 62;
    const stroke = 22;
    const c = size / 2;
    const total = slices.reduce((sum, s) => sum + s.count, 0);

    if (!total) {
      return `<svg viewBox="0 0 ${size} ${size}" role="img" aria-label="No data yet">
        <circle cx="${c}" cy="${c}" r="${r}" fill="none" stroke="#eef3fb" stroke-width="${stroke}"/>
        <text x="${c}" y="${c + 4}" text-anchor="middle" fill="#9aa9bd" font-size="12"
          font-family="Inter, sans-serif">no data</text></svg>`;
    }

    const circ = 2 * Math.PI * r;
    let offset = 0;
    const arcs = slices
      .map((s, i) => {
        const frac = s.count / total;
        const dash = `${(frac * circ).toFixed(2)} ${(circ - frac * circ).toFixed(2)}`;
        const el = `<circle cx="${c}" cy="${c}" r="${r}" fill="none" stroke="${PALETTE[i % PALETTE.length]}"
          stroke-width="${stroke}" stroke-dasharray="${dash}" stroke-dashoffset="${(-offset * circ).toFixed(2)}"
          transform="rotate(-90 ${c} ${c})"><title>${esc(s.label)}: ${s.count}</title></circle>`;
        offset += frac;
        return el;
      })
      .join("");

    const top = slices[0];
    return `<svg viewBox="0 0 ${size} ${size}" role="img" aria-label="Errors by type">
      <circle cx="${c}" cy="${c}" r="${r}" fill="none" stroke="#f2f7fe" stroke-width="${stroke}"/>
      ${arcs}
      <text x="${c}" y="${c - 2}" text-anchor="middle" fill="#14263d" font-size="22" font-weight="600"
        font-family="Space Grotesk, sans-serif">${Math.round((top.count / total) * 100)}%</text>
      <text x="${c}" y="${c + 15}" text-anchor="middle" fill="#7386a0" font-size="10"
        font-family="Inter, sans-serif">${esc(top.label.slice(0, 18))}</text>
    </svg>`;
  }

  /* --------------------------------------------------------------- metrics */
  function severityClass(sev) {
    return ["critical", "major", "minor", "info"].includes(sev) ? sev : "info";
  }

  function feedRow(item, full) {
    const conf = `<div class="bar"><div class="bar-track"><div class="bar-fill" style="width:${pct(item.confidence)}"></div></div><span class="bar-num">${pct(item.confidence)}</span></div>`;
    const review =
      item.review === "APPROVED"
        ? '<span class="pill pill-good">approved</span>'
        : item.review === "REJECTED"
        ? '<span class="pill pill-bad">rejected</span>'
        : '<span class="pill pill-ghost">n/a</span>';
    const status = `<span class="status ${severityClass(item.severity)}">${esc(item.severity)}</span>`;

    if (!full) {
      return `<tr><td class="id">#${esc(item.id)}</td><td>${status}</td>
        <td>${esc(item.error_type)}</td><td>${conf}</td><td>${review}</td></tr>`;
    }
    return `<tr><td class="id">#${esc(item.id)}</td>
      <td><span class="status ${item.status === "completed" ? "done" : "major"}">${esc(item.status)}</span></td>
      <td>${esc(item.error_type)}<div class="source-url">${esc(item.root_cause.slice(0, 90))}</div></td>
      <td>${status}</td><td>${conf}</td><td>${review}</td><td class="bar-num">${ms(item.duration_ms)}</td></tr>`;
  }

  async function loadMetrics() {
    let data;
    try {
      data = await api("/dashboard/metrics");
    } catch (err) {
      toast("Could not reach the API");
      return;
    }
    state.config = data.config;

    $("#kpi-active").textContent = data.active;
    $("#kpi-rate").textContent = pct(data.resolution_rate);
    $("#kpi-total").textContent = data.total;
    $("#kpi-conf").textContent = data.total ? pct(data.avg_confidence) : "—";
    $("#kpi-time").textContent = data.total ? ms(data.avg_duration_ms) : "—";
    $("#kpi-kb-rate").textContent = pct(data.kb_hit_rate || 0);

    $("#chart-line").innerHTML = lineChart(data.timeline || []);
    $("#chart-donut").innerHTML = donutChart(data.by_error_type || []);

    const total = (data.by_error_type || []).reduce((s, x) => s + x.count, 0);
    $("#donut-note").textContent = total ? `${total} classified` : "no data yet";
    $("#donut-legend").innerHTML =
      (data.by_error_type || [])
        .map(
          (s, i) =>
            `<li><span class="dot" style="background:${PALETTE[i % PALETTE.length]}"></span>
             ${esc(s.label)}<span class="count">${s.count}</span></li>`
        )
        .join("") || '<li class="muted">Nothing classified yet.</li>';

    const feed = data.feed || [];
    $("#feed-body").innerHTML = feed.length
      ? feed.slice(0, 6).map((i) => feedRow(i, false)).join("")
      : '<tr class="empty-row"><td colspan="5">No investigations yet. Run one to populate the feed.</td></tr>';
    $("#feed-full").innerHTML = feed.length
      ? feed.map((i) => feedRow(i, true)).join("")
      : '<tr class="empty-row"><td colspan="7">Nothing here yet.</td></tr>';

    renderConfig(data.config);
  }

  function renderConfig(config) {
    if (!config) return;
    $("#side-model").textContent = config.model;
    const mode = $("#side-mode");
    mode.textContent = config.demo_mode ? "heuristic mode" : "model connected";
    mode.className = `pill ${config.demo_mode ? "pill-warn" : "pill-good"}`;
    $("#chip-env").textContent = config.demo_mode ? "no API key" : "live";
    $("#gate-threshold").textContent = `threshold ${pct(config.confidence_threshold)}`;
    $("#gauge-mark").style.left = pct(config.confidence_threshold);

    $("#config-kv").innerHTML = `
      <dt>Model</dt><dd>${esc(config.model)}</dd>
      <dt>Mode</dt><dd>${config.demo_mode ? "heuristic (no OPENROUTER_API_KEY)" : "model-backed"}</dd>
      <dt>Confidence gate</dt><dd>${pct(config.confidence_threshold)}</dd>
      <dt>Max research loops</dt><dd>${config.max_research_iterations}</dd>
      <dt>Max fix retries</dt><dd>${config.max_fix_retries}</dd>`;
  }

  /* ----------------------------------------------------------------- rail */
  function resetRail() {
    $("#rail").innerHTML = STAGES.map(
      (s, i) => `<li class="rail-step" data-node="${s.node}">
        <span class="rail-node">${i + 1}</span>
        <span class="rail-title">${s.label}</span>
        <p class="rail-detail" hidden></p>
      </li>`
    ).join("");
    $("#gauge-fill").style.width = "0%";
    $("#gate-value").textContent = "—";
    $("#rail-status").textContent = "idle";
  }

  function markSkipped(node) {
    const step = $(`.rail-step[data-node="${node}"]`);
    if (!step) return;
    step.classList.remove("is-running", "is-done", "is-looped");
    step.classList.add("is-skipped");
    const p = $(".rail-detail", step);
    p.textContent = "Skipped — served from the knowledge base.";
    p.hidden = false;
  }

  function markStage(node, detail, confidence) {
    const step = $(`.rail-step[data-node="${node}"]`);
    if (!step) return;

    // A revisited node means the graph looped back through a conditional edge.
    if (step.classList.contains("is-done")) step.classList.add("is-looped");
    step.classList.remove("is-running", "is-skipped");
    step.classList.add("is-done");

    if (detail) {
      const p = $(".rail-detail", step);
      p.textContent = detail;
      p.hidden = false;
    }

    const isKbHit = node === "knowledge_base_agent" && /matched/i.test(detail || "");
    if (isKbHit) {
      SKIPPED_ON_KB_HIT.forEach(markSkipped);
      const validation = $('.rail-step[data-node="validation_agent"]');
      if (validation && !validation.classList.contains("is-done")) {
        validation.classList.add("is-running");
      }
    } else {
      const index = STAGES.findIndex((s) => s.node === node);
      const next = STAGES[index + 1];
      if (next) {
        const nextStep = $(`.rail-step[data-node="${next.node}"]`);
        if (nextStep && !nextStep.classList.contains("is-done") && !nextStep.classList.contains("is-skipped")) {
          nextStep.classList.add("is-running");
        }
      }
    }

    if (typeof confidence === "number" && confidence > 0) {
      $("#gauge-fill").style.width = pct(confidence);
      $("#gate-value").textContent = `confidence ${pct(confidence)}`;
    }
  }

  /* ------------------------------------------------------------- markdown */
  function markdown(src) {
    const blocks = [];
    let text = String(src || "").replace(/```(\w*)\n([\s\S]*?)```/g, (_, lang, code) => {
      const highlighted = esc(code.replace(/\n$/, ""))
        .split("\n")
        .map((line) => {
          if (/^\+(?!\+\+)/.test(line)) return `<span class="add">${line}</span>`;
          if (/^-(?!--)/.test(line)) return `<span class="del">${line}</span>`;
          if (/^(@@|---|\+\+\+|diff )/.test(line)) return `<span class="meta">${line}</span>`;
          return line;
        })
        .join("\n");
      blocks.push(`<pre><code class="lang-${esc(lang)}">${highlighted}</code></pre>`);
      return `\u0000BLOCK${blocks.length - 1}\u0000`;
    });

    text = esc(text)
      .replace(/^### (.*)$/gm, "<h3>$1</h3>")
      .replace(/^## (.*)$/gm, "<h2>$1</h2>")
      .replace(/^# (.*)$/gm, "<h1>$1</h1>")
      .replace(/^---$/gm, "<hr>")
      .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
      .replace(/(^|[^*])\*(?!\s)([^*]+?)\*/g, "$1<em>$2</em>")
      .replace(/_([^_\n]+)_/g, "<em>$1</em>")
      .replace(/`([^`\n]+)`/g, "<code>$1</code>")
      .replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>');

    const lines = text.split("\n");
    const html = [];
    let list = null;

    for (const line of lines) {
      const ul = line.match(/^\s*-\s+(.*)$/);
      const ol = line.match(/^\s*(\d+)\.\s+(.*)$/);
      if (ul) {
        if (list !== "ul") { if (list) html.push(`</${list}>`); html.push("<ul>"); list = "ul"; }
        html.push(`<li>${ul[1]}</li>`);
        continue;
      }
      if (ol) {
        if (list !== "ol") { if (list) html.push(`</${list}>`); html.push("<ol>"); list = "ol"; }
        html.push(`<li>${ol[2]}</li>`);
        continue;
      }
      if (list) { html.push(`</${list}>`); list = null; }
      if (!line.trim()) continue;
      if (/^<(h1|h2|h3|hr)/.test(line)) html.push(line);
      else html.push(`<p>${line}</p>`);
    }
    if (list) html.push(`</${list}>`);

    return html.join("\n").replace(/\u0000BLOCK(\d+)\u0000/g, (_, i) => blocks[Number(i)]);
  }

  /* -------------------------------------------------------------- results */
  function renderResult(result) {
    state.lastResult = result;

    $("#report-card").hidden = false;
    $("#report").innerHTML = markdown(result.final_response);

    const approved = result.review?.decision === "APPROVED";
    const badge = $("#report-status");
    if (result.kb_hit) {
      badge.textContent = `${result.status} · from knowledge base`;
      badge.className = "pill pill-good";
    } else {
      badge.textContent = `${result.status} · ${approved ? "approved" : "not approved"}`;
      badge.className = `pill ${approved ? "pill-good" : "pill-warn"}`;
    }

    $("#rail-status").textContent = result.kb_hit
      ? `${ms(result.duration_ms)} · served from cache, no model call`
      : `${ms(result.duration_ms)} · ${result.trace?.length || 0} stages`;

    const sources = result.citations || [];
    $("#evidence-body").innerHTML = sources.length
      ? sources
          .map(
            (c) => `<div class="source-item">
              <span class="source-index">${c.index}</span>
              <div>
                <a class="source-title" href="${esc(c.url)}" target="_blank" rel="noopener noreferrer">${esc(c.title)}</a>
                <div class="source-url">${esc(c.url)}</div>
                <div class="source-meta"><span class="pill pill-soft">${esc(c.source_type)}</span></div>
              </div>
            </div>`
          )
          .join("")
      : '<p class="muted">No external sources were reachable for this investigation.</p>';

    const notes = [];
    if (result.root_cause) {
      notes.push({ tag: `Root cause · ${pct(result.confidence)}`, body: result.root_cause });
    }
    if (result.review?.summary) {
      notes.push({ tag: `Review · ${result.review.decision}`, body: result.review.summary });
    }
    (result.warnings || []).slice(0, 2).forEach((w) => notes.push({ tag: "Note", body: w }));
    if (notes.length) {
      $("#suggestions").innerHTML = notes
        .map(
          (n) => `<div class="note"><span class="note-tag">${esc(n.tag)}</span>
            <p class="note-body">${esc(n.body)}</p></div>`
        )
        .join("");
    }
    loadMetrics();
  }

  /* ------------------------------------------------------------- run flow */
  function collectRequest() {
    const val = (id) => $(id).value.trim();
    return {
      error_message: val("#in-error"),
      stack_trace: val("#in-trace") || null,
      logs: val("#in-logs") || null,
      source_code: val("#in-code") || null,
      language: val("#in-language") || null,
      framework: val("#in-framework") || null,
      repository_url: val("#in-repo") || null,
      dependencies: val("#in-deps")
        ? val("#in-deps").split(/[,\n]/).map((d) => d.trim()).filter(Boolean)
        : [],
    };
  }

  async function runInvestigation() {
    if (state.running) return;
    const payload = collectRequest();
    if (!payload.error_message) {
      toast("Add an error message first");
      $("#in-error").focus();
      return;
    }

    state.running = true;
    const btn = $("#btn-run");
    btn.disabled = true;
    btn.textContent = "Investigating…";
    resetRail();
    $("#rail-status").textContent = "running";
    $("#report-card").hidden = true;
    $(".rail-step")?.classList.add("is-running");

    try {
      const res = await fetch(`${API}/investigate/stream`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!res.ok || !res.body) throw new Error(`${res.status} ${res.statusText}`);

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        const chunks = buffer.split("\n\n");
        buffer = chunks.pop() || "";
        for (const chunk of chunks) {
          const line = chunk.split("\n").find((l) => l.startsWith("data: "));
          if (!line) continue;
          let event;
          try {
            event = JSON.parse(line.slice(6));
          } catch {
            continue;
          }
          if (event.type === "stage") markStage(event.node, event.detail, event.confidence);
          else if (event.type === "result") renderResult(event.result);
          else if (event.type === "error") toast(`Investigation failed: ${event.message}`);
        }
      }
      $$(".rail-step").forEach((s) => s.classList.remove("is-running"));
    } catch (err) {
      toast(`Could not run the investigation: ${err.message}`);
      $("#rail-status").textContent = "failed";
    } finally {
      state.running = false;
      btn.disabled = false;
      btn.textContent = "Investigate bug";
    }
  }

  $("#btn-run").addEventListener("click", runInvestigation);

  $("#btn-copy").addEventListener("click", async () => {
    if (!state.lastResult) return;
    try {
      await navigator.clipboard.writeText(state.lastResult.final_response);
      toast("Report copied");
    } catch {
      toast("Copying is blocked in this browser");
    }
  });

  /* ---------------------------------------------------------- free models */
  async function loadFreeModels() {
    const box = $("#models-body");
    box.innerHTML = '<p class="muted">Checking OpenRouter…</p>';
    let data;
    try {
      data = await api("/models/free");
    } catch {
      box.innerHTML = '<p class="muted">Could not reach the model catalog.</p>';
      return;
    }

    const configured = data.configured || {};
    const live = new Set((data.models || []).map((m) => m.id));
    const dead = [configured.primary, ...(configured.fallbacks || [])].filter(
      (id) => id && !live.has(id)
    );

    if (!data.count) {
      box.innerHTML =
        '<p class="muted">OpenRouter reported no free models. Check openrouter.ai/models.</p>';
      return;
    }

    box.innerHTML = `
      ${
        dead.length
          ? `<div class="note"><span class="note-tag">Configured but not live</span>
             <p class="note-body">${dead.map(esc).join(", ")} — the app falls back to the
             models below automatically. Set <code>OPENROUTER_MODEL</code> to one of them
             to skip the failed attempts.</p></div>`
          : ""
      }
      <ul class="legend" style="margin-top:12px">
        ${(data.models || [])
          .slice(0, 8)
          .map(
            (m) => `<li>
              <span class="dot" style="background:${
                m.id === configured.primary ? "#1668e3" : "#b9d6fa"
              }"></span>
              <span style="font-family:var(--font-mono);font-size:11.5px">${esc(m.id)}</span>
              <span class="count">${Math.round(m.context_length / 1000)}k ctx</span>
            </li>`
          )
          .join("")}
      </ul>
      <p class="muted" style="margin-top:12px;font-size:12px">
        ${data.count} free models live. Free IDs rotate, so this list is fetched from
        OpenRouter rather than hard-coded.</p>`;
  }

  $("#btn-models").addEventListener("click", loadFreeModels);

  /* ------------------------------------------------------- knowledge base */
  async function loadKnowledgeBase() {
    let data;
    try {
      data = await api("/knowledge-base/stats");
    } catch {
      toast("Could not reach the knowledge base");
      return;
    }
    $("#kb-seed-count").textContent = data.seed_count;
    $("#kb-learned-count").textContent = data.learned_count;
    $("#kb-threshold").textContent = pct(data.match_threshold);

    const byFw = Object.entries(data.by_framework || {}).sort((a, b) => b[1] - a[1]);
    $("#kb-framework-legend").innerHTML =
      byFw
        .map(
          ([fw, count], i) =>
            `<li><span class="dot" style="background:${PALETTE[i % PALETTE.length]}"></span>
             ${esc(fw)}<span class="count">${count}</span></li>`
        )
        .join("") || '<li class="muted">No entries loaded.</li>';
  }

  async function searchKnowledgeBase() {
    const query = $("#kb-search-input").value.trim();
    const box = $("#kb-search-result");
    if (!query) {
      toast("Type an error message first");
      return;
    }
    box.innerHTML = '<p class="muted">Searching…</p>';
    let data;
    try {
      data = await api(`/knowledge-base/search?q=${encodeURIComponent(query)}`);
    } catch {
      box.innerHTML = '<p class="muted">Search failed.</p>';
      return;
    }
    if (!data.match) {
      box.innerHTML =
        '<div class="note"><span class="note-tag">No match</span>' +
        '<p class="note-body">Nothing in the knowledge base is similar enough. ' +
        "This would run the full agent pipeline instead of skipping it.</p></div>";
      return;
    }
    const m = data.match;
    box.innerHTML = `
      <div class="note">
        <span class="note-tag">Match: ${esc(m.entry.title)} (${pct(m.score)} similarity, ${esc(m.entry.source)})</span>
        <p class="note-body"><b>Root cause:</b> ${esc(m.entry.root_cause)}</p>
        <p class="note-body"><b>Fix:</b> ${esc(m.entry.fix)}</p>
        <p class="note-body" style="color:var(--faint)">
          This error would skip the LLM entirely and be answered from the cache.</p>
      </div>`;
  }

  $("#btn-kb-search")?.addEventListener("click", searchKnowledgeBase);
  $("#kb-search-input")?.addEventListener("keydown", (e) => {
    if (e.key === "Enter") searchKnowledgeBase();
  });

  /* -------------------------------------------------------------- samples */
  async function loadSamples() {
    let data;
    try {
      data = await api("/samples");
    } catch {
      return;
    }
    const select = $("#sample-select");
    data.samples.forEach((s) => {
      const option = document.createElement("option");
      option.value = s.id;
      option.textContent = s.label;
      select.appendChild(option);
    });
    select.addEventListener("change", () => {
      const sample = data.samples.find((s) => s.id === select.value);
      if (!sample) return;
      $("#in-error").value = sample.error_message || "";
      $("#in-trace").value = sample.stack_trace || "";
      $("#in-code").value = sample.source_code || "";
      $("#in-logs").value = sample.logs || "";
      $("#in-language").value = sample.language || "";
      $("#in-framework").value = sample.framework || "";
      $("#in-repo").value = sample.repository_url || "";
      $("#in-deps").value = (sample.dependencies || []).join(", ");
      toast(`Loaded: ${sample.label}`);
    });
  }

  /* -------------------------------------------------------- graph diagram */
  function renderGraph() {
    const box = (x, y, w, h, label, sub, fill) => `
      <rect x="${x}" y="${y}" width="${w}" height="${h}" rx="10" fill="${fill}" stroke="#d3dfef"/>
      <text x="${x + w / 2}" y="${y + (sub ? 22 : h / 2 + 4)}" text-anchor="middle" fill="#14263d"
        font-family="Space Grotesk, sans-serif" font-size="12.5" font-weight="600">${label}</text>
      ${sub ? `<text x="${x + w / 2}" y="${y + 38}" text-anchor="middle" fill="#7386a0"
        font-family="JetBrains Mono, monospace" font-size="9.5">${sub}</text>` : ""}`;

    const arrow = (x1, y1, x2, y2, dashed) =>
      `<path d="M${x1},${y1} L${x2},${y2}" stroke="#a9bdd8" stroke-width="1.6"
        ${dashed ? 'stroke-dasharray="4 4"' : ""} marker-end="url(#arw)"/>`;

    $("#graph-diagram").innerHTML = `
    <svg viewBox="0 0 760 520" role="img" aria-label="LangGraph agent pipeline" style="width:100%;height:auto">
      <defs>
        <marker id="arw" markerWidth="8" markerHeight="8" refX="7" refY="3" orient="auto">
          <path d="M0,0 L7,3 L0,6 Z" fill="#a9bdd8"/>
        </marker>
      </defs>

      ${box(300, 10, 160, 34, "START", "", "#eef3fb")}
      ${arrow(380, 44, 380, 62)}
      ${box(280, 62, 200, 50, "validate_input", "SSRF + size guards", "#fff")}
      ${arrow(380, 112, 380, 130)}
      ${box(280, 130, 200, 50, "knowledge_base_agent", "local TF-IDF over known errors", "#eef3fb")}

      <path d="M380,180 L380,196" stroke="#a9bdd8" stroke-width="1.6"/>
      <polygon points="380,196 452,216 380,236 308,216" fill="#e3eefc" stroke="#1668e3" stroke-width="1.2"/>
      <text x="380" y="220" text-anchor="middle" fill="#0b3c7e" font-family="JetBrains Mono, monospace"
        font-size="9.5">known pattern?</text>

      <path d="M452,216 L610,216 L610,240" stroke="#17b26a" stroke-width="1.6"
        stroke-dasharray="5 4" marker-end="url(#arw)"/>
      <text x="520" y="208" fill="#0f8a51" font-family="JetBrains Mono, monospace"
        font-size="9.5">HIT → skip everything, no model call</text>

      <path d="M380,236 L380,252" stroke="#a9bdd8" stroke-width="1.6" marker-end="url(#arw)"/>
      <text x="386" y="248" fill="#7386a0" font-family="JetBrains Mono, monospace" font-size="9.5">MISS</text>

      ${box(280, 252, 200, 50, "debug_agent", "error_type, file, hypotheses", "#fff")}
      ${arrow(380, 302, 380, 320)}
      ${box(280, 320, 200, 50, "research_agent", "web + GitHub + registries", "#fff")}
      ${arrow(380, 370, 380, 388)}
      ${box(280, 388, 200, 50, "root_cause_agent", "cause + confidence", "#fff")}

      <path d="M380,438 L380,454" stroke="#a9bdd8" stroke-width="1.6"/>
      <polygon points="380,454 452,474 380,494 308,474" fill="#e3eefc" stroke="#1668e3" stroke-width="1.2"/>
      <text x="380" y="478" text-anchor="middle" fill="#0b3c7e" font-family="JetBrains Mono, monospace"
        font-size="10">confidence gate</text>

      <path d="M308,474 L150,474 L150,345" stroke="#f2a93b" stroke-width="1.6" stroke-dasharray="5 4" marker-end="url(#arw)"/>
      <text x="152" y="420" fill="#b4761a" font-family="JetBrains Mono, monospace" font-size="9.5">LOW → research (max 2)</text>
      <path d="M150,345 L280,345" stroke="#f2a93b" stroke-width="1.6" stroke-dasharray="5 4" marker-end="url(#arw)"/>

      <path d="M452,474 L610,474 L610,120" stroke="#1668e3" stroke-width="1.6" marker-end="url(#arw)"/>
      <text x="470" y="466" fill="#1250b0" font-family="JetBrains Mono, monospace" font-size="9.5">HIGH</text>
      ${box(530, 70, 170, 50, "fix_agent", "grounded unified diff", "#fff")}
      ${arrow(615, 120, 615, 150)}
      ${box(530, 150, 170, 50, "code_reviewer", "independent, adversarial", "#fff")}

      <path d="M700,175 L730,175 L730,60 L615,60 L615,70" stroke="#e5484d" stroke-width="1.6"
        stroke-dasharray="5 4" marker-end="url(#arw)"/>
      <text x="640" y="52" fill="#c93438" font-family="JetBrains Mono, monospace" font-size="9.5">REJECTED → retry (max 2)</text>

      <path d="M615,200 L615,240" stroke="#17b26a" stroke-width="1.6" marker-end="url(#arw)"/>
      <text x="622" y="222" fill="#0f8a51" font-family="JetBrains Mono, monospace" font-size="9.5">APPROVED</text>
      ${box(530, 240, 170, 50, "validation_agent", "static only, no execution", "#fff")}
      ${arrow(615, 290, 615, 400)}
      ${box(530, 400, 170, 44, "compose_report", "report + citations + learning", "#eef3fb")}
    </svg>
    <p class="muted" style="margin-top:14px">
      The knowledge base is checked first: a strong match against
      <code>error_knowledge_base.pdf</code> or a previously learned case skips straight to
      validation with zero model calls. Otherwise three conditional edges carry the
      intelligence: the confidence gate can send a case back for more research, a rejected
      review sends the fix back for another attempt, and an approved, high-confidence fresh
      diagnosis is saved back into the knowledge base for next time. All loops are capped, so
      the graph always terminates.
    </p>`;
  }

  /* ----------------------------------------------------------------- init */
  resetRail();
  renderGraph();
  loadSamples();
  loadMetrics();
})();
