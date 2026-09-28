"use strict";
/*
 * IHI dashboard front end (no framework, no build step).
 *
 * Every number shown here comes from the Python engine through /api/*.
 * Parameter lists, thresholds, weights and health bands are read from
 * /api/config (i.e. config/*.yaml), never written into this file.
 */

const state = {
  config: null,     // /api/config, loaded once at start-up
  filter: null,     // health-class label selected on the fleet page (null = all)
  search: "",       // fleet page search text
};

// ---------------------------------------------------------------------------
// Formatting helpers (French conventions: decimal comma, "−" minus sign)
// ---------------------------------------------------------------------------
const MINUS = "−";
const DASH = "—";

function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (c) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]
  ));
}

function num(value, digits = 1) {
  if (value === null || value === undefined) return DASH;
  return value
    .toLocaleString("fr-FR", { minimumFractionDigits: digits, maximumFractionDigits: digits })
    .replace("-", MINUS);
}

/** Up to `max` decimals, trailing zeros dropped: for measured values and thresholds. */
function numAuto(value, max = 3) {
  if (value === null || value === undefined) return DASH;
  return value.toLocaleString("fr-FR", { maximumFractionDigits: max }).replace("-", MINUS);
}

function signed(value, digits = 1) {
  const sign = value > 0 ? "+" : value < 0 ? MINUS : "";
  return sign + num(Math.abs(value), digits);
}

function fmtDate(iso) {
  if (!iso) return DASH;
  return new Date(iso).toLocaleDateString("fr-FR", { day: "numeric", month: "short", year: "numeric" });
}

/** Display name for a parameter: chemical formulas get subscripts (C2H4 -> C₂H₄). */
function prettyParam(name) {
  if (/^(?:[A-Z][a-z]?\d*)+$/.test(name) && /\d/.test(name)) {
    return name.replace(/\d/g, (d) => "₀₁₂₃₄₅₆₇₈₉"[d]);
  }
  return name.replace(/_/g, " ");
}

function unitLabel(unit) {
  return { degC: "°C", percent: "%", Mohm: "MΩ", years: "ans", ratio: "" }[unit] ?? unit ?? "";
}

// ---------------------------------------------------------------------------
// Health bands (from config/classification.yaml)
// ---------------------------------------------------------------------------
function levelFor(percent) {
  for (const band of state.config.bands) {
    if (percent >= band.lower) return band.level;
  }
  return state.config.bands.at(-1).level;
}

const pill = (c) => `<span class="pill lvl-${c.level}">${esc(c.label)}</span>`;

function meter(fraction, level, wide = false) {
  const width = Math.max(0, Math.min(1, fraction)) * 100;
  return `<div class="meter${wide ? " wide" : ""}"><span class="fill lvl-${level}" style="width:${width}%"></span></div>`;
}

// ---------------------------------------------------------------------------
// API
// ---------------------------------------------------------------------------
async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const body = await response.json().catch(() => null);
  if (!response.ok) {
    const error = new Error(`HTTP ${response.status}`);
    error.status = response.status;
    error.errors = errorList(body);
    throw error;
  }
  return body;
}

/** Normalize the different error shapes the API can return into [{field, message}]. */
function errorList(body) {
  const detail = body?.detail;
  if (!detail) return [{ field: null, message: "Erreur inattendue du serveur." }];
  if (typeof detail === "string") return [{ field: null, message: detail }];
  if (Array.isArray(detail.errors)) return detail.errors;
  if (Array.isArray(detail)) {  // FastAPI's own request-body validation
    return detail.map((e) => ({ field: e.loc?.at(-1) ?? null, message: e.msg }));
  }
  return [{ field: null, message: JSON.stringify(detail) }];
}

async function refreshAlertBadge(count) {
  if (count === undefined) count = (await api("/api/fleet")).alert_count;
  const badge = document.getElementById("alert-badge");
  badge.textContent = count;
  badge.hidden = count === 0;
}

// ---------------------------------------------------------------------------
// Layout
// ---------------------------------------------------------------------------
const view = () => document.getElementById("view");

function setTopbar(title, actions = "") {
  document.getElementById("topbar").innerHTML =
    `<h1>${title}</h1><div class="spacer"></div>${actions}`;
}

const newMeasureButton = (id) =>
  `<a class="btn primary" href="#/mesure${id ? "/" + encodeURIComponent(id) : ""}">+ Nouvelle mesure</a>`;

// ---------------------------------------------------------------------------
// Page: fleet ("Parc")
// ---------------------------------------------------------------------------
async function renderFleet() {
  setTopbar(
    "Parc de transformateurs",
    `<label class="search">
       <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/></svg>
       <input id="search" placeholder="Transformateur ou poste" value="${esc(state.search)}">
     </label>
     ${newMeasureButton()}`,
  );

  const fleet = await api("/api/fleet");
  refreshAlertBadge(fleet.alert_count);

  const draw = () => {
    view().innerHTML = fleetSummary(fleet) + fleetChips() + fleetTable(fleet.transformers);
    bindFleetEvents(draw);
  };
  draw();

  document.getElementById("search").addEventListener("input", (event) => {
    state.search = event.target.value;
    draw();
  });
}

function fleetSummary(fleet) {
  const bands = state.config.bands;
  const total = fleet.transformers.length;
  const segments = bands
    .filter((b) => fleet.distribution[b.label] > 0)
    .map((b) => `<span class="lvl-${b.level}" style="flex:${fleet.distribution[b.label]}" title="${esc(b.label)}"></span>`)
    .join("");
  const legend = bands.map((b) => `
      <div class="legend-item">
        <span class="dot lvl-${b.level}"></span>${esc(b.label)}
        <span class="count">${fleet.distribution[b.label] ?? 0}</span>
      </div>`).join("");

  return `
    <div class="card">
      <div class="card-head">
        <h2>État du parc · ${total} transformateur${total > 1 ? "s" : ""}</h2>
        <span class="muted">IHI moyen <span class="mono" style="color:var(--ink);font-weight:600">${fleet.mean_ihi_percent === null ? DASH : num(fleet.mean_ihi_percent) + " %"}</span></span>
      </div>
      <div class="stack">${segments}</div>
      <div class="legend">${legend}</div>
    </div>`;
}

function fleetChips() {
  const chip = (label, value) =>
    `<button class="chip${state.filter === value ? " active" : ""}" data-filter="${esc(value ?? "")}">${esc(label)}</button>`;
  return `<div class="chips">${chip("Tous", null)}${state.config.bands.map((b) => chip(b.label, b.label)).join("")}</div>`;
}

function trendCell(trend) {
  if (!trend) return `<span class="muted">${DASH}</span>`;
  const arrow = trend.delta_pt < 0 ? "↓" : trend.delta_pt > 0 ? "↑" : "→";
  const title = `${signed(trend.delta_pt)} pt en ${num(trend.days, 0)} jours, soit ${signed(trend.rate_pt_per_year)} pt/an`;
  return `<span class="trend" title="${esc(title)}">${arrow} ${signed(trend.delta_pt)} pt${trend.accelerated ? '<span class="tag">Accélérée</span>' : ""}</span>`;
}

function fleetTable(transformers) {
  const query = state.search.trim().toLowerCase();
  const rows = transformers.filter((t) =>
    (!state.filter || t.classification?.label === state.filter) &&
    (!query || t.id.toLowerCase().includes(query) || (t.substation || "").toLowerCase().includes(query)),
  );

  if (!rows.length) {
    return `<div class="empty">Aucun transformateur ne correspond à ce filtre.</div>`;
  }

  const body = rows.map((t) => {
    const c = t.classification;
    return `
      <tr class="clickable" data-id="${esc(t.id)}">
        <td><div class="tid">${esc(t.id)}</div><div class="sub">${esc(t.substation || DASH)}</div></td>
        <td class="muted">${t.age_years == null ? DASH : Math.floor(t.age_years) + " ans"}</td>
        <td>${c ? `<div class="ihi-cell"><span class="mono">${num(t.ihi_percent)} %</span>${meter(t.ihi_percent / 100, c.level)}</div>` : '<span class="muted">Aucune mesure</span>'}</td>
        <td>${c ? pill(c) : DASH}</td>
        <td>${trendCell(t.trend)}</td>
        <td class="muted">${fmtDate(t.last_evaluation)}</td>
        <td>${c ? esc(c.action) : DASH}</td>
      </tr>`;
  }).join("");

  return `
    <div class="table-wrap">
      <table>
        <thead><tr>
          <th>Transformateur</th><th>Âge</th><th>IHI</th><th>Classe</th>
          <th>Évolution</th><th>Dernière évaluation</th><th>Action proposée</th>
        </tr></thead>
        <tbody>${body}</tbody>
      </table>
    </div>`;
}

function bindFleetEvents(redraw) {
  view().querySelectorAll("[data-filter]").forEach((button) => {
    button.addEventListener("click", () => {
      state.filter = button.dataset.filter || null;
      redraw();
    });
  });
  view().querySelectorAll("tr[data-id]").forEach((row) => {
    row.addEventListener("click", () => {
      location.hash = `#/transformateur/${encodeURIComponent(row.dataset.id)}`;
    });
  });
}

// ---------------------------------------------------------------------------
// Page: one transformer
// ---------------------------------------------------------------------------
async function renderDetail(id) {
  const t = await api(`/api/transformers/${encodeURIComponent(id)}`);
  setTopbar(
    `<span class="mono">${esc(t.id)}</span> <span class="muted" style="font-weight:400;font-size:16px">· ${esc(t.substation || "")}${t.age_years == null ? "" : " · " + Math.floor(t.age_years) + " ans"}</span>`,
    newMeasureButton(t.id),
  );

  const back = `<a class="back" href="#/parc">← Parc</a>`;
  if (!t.latest) {
    view().innerHTML = `${back}<div class="card empty">Aucune mesure enregistrée pour ce transformateur.<br><br>${newMeasureButton(t.id)}</div>`;
    return;
  }

  view().innerHTML = `
    ${back}
    ${alertBox(t.alerts)}
    <div class="grid cols-3">
      ${scoreCard(t.latest, `Dernière évaluation · ${fmtDate(t.last_evaluation)} · ${t.evaluations} évaluation${t.evaluations > 1 ? "s" : ""}`)}
      ${trendCard(t.trend)}
      <div class="card"><h2>Historique de l'IHI</h2>${historyChart(t.history)}</div>
    </div>
    ${evaluationDetails(t.latest)}`;
}

function alertBox(reasons) {
  if (!reasons?.length) return "";
  return `<div class="alert-box"><strong>Alerte</strong><ul>${reasons.map((r) => `<li>${esc(r)}</li>`).join("")}</ul></div>`;
}

function scoreCard(ev, caption) {
  const c = ev.classification;
  return `
    <div class="card">
      <h2>Indice de santé</h2>
      <div class="big-ihi">${num(ev.ihi_percent)} %</div>
      <div style="margin-top:10px">${pill(c)}</div>
      <dl class="kv">
        <dt>Action</dt><dd>${esc(c.action)}</dd>
        <dt>Bande</dt><dd class="mono">${esc(c.band)}</dd>
      </dl>
      <p class="note">${esc(caption)}</p>
    </div>`;
}

function trendCard(trend) {
  const threshold = state.config.alerts.accelerated_decline_pt_per_year;
  if (!trend) {
    return `<div class="card"><h2>Évolution</h2><p class="muted">Une seule évaluation : il en faut deux pour calculer une tendance.</p></div>`;
  }
  return `
    <div class="card">
      <h2>Évolution</h2>
      <div class="big-ihi" style="font-size:28px">${signed(trend.delta_pt)} pt</div>
      <dl class="kv">
        <dt>Intervalle</dt><dd>${num(trend.days, 0)} jours</dd>
        <dt>Vitesse</dt><dd class="mono">${signed(trend.rate_pt_per_year)} pt/an</dd>
        <dt>État</dt><dd>${trend.accelerated ? '<span class="tag">Dégradation accélérée</span>' : trend.delta_pt < 0 ? "Dégradation progressive" : "Stable ou en amélioration"}</dd>
      </dl>
      <p class="note">Seuil « accélérée » : ${MINUS}${num(threshold)} pt/an (config/alerts.yaml)</p>
    </div>`;
}

/** Line chart of IHI over time, drawn over the health bands. */
function historyChart(history) {
  const W = 640, H = 210, left = 34, right = 14, top = 10, bottom = 26;
  const plotW = W - left - right, plotH = H - top - bottom;
  const y = (v) => top + (100 - v) / 100 * plotH;

  const times = history.map((h) => new Date(h.timestamp).getTime());
  const t0 = Math.min(...times), t1 = Math.max(...times);
  const x = (t) => (t1 === t0 ? left + plotW / 2 : left + (t - t0) / (t1 - t0) * plotW);

  const bands = state.config.bands.map((b) =>
    `<rect x="${left}" y="${y(b.upper)}" width="${plotW}" height="${y(b.lower) - y(b.upper)}" style="fill:var(--lvl-${b.level}-soft)"/>`,
  ).join("");
  const grid = state.config.bands.map((b) =>
    `<text x="${left - 6}" y="${y(b.lower) + 4}" text-anchor="end">${b.lower}</text>`,
  ).join("") + `<text x="${left - 6}" y="${y(100) + 4}" text-anchor="end">100</text>`;

  const points = history.map((h, i) => [x(times[i]), y(h.ihi_percent), h]);
  const line = points.map(([px, py]) => `${px.toFixed(1)},${py.toFixed(1)}`).join(" ");
  const dots = points.map(([px, py, h]) =>
    `<circle cx="${px}" cy="${py}" r="4.5" style="fill:var(--lvl-${h.level});stroke:#fff;stroke-width:2"><title>${fmtDate(h.timestamp)} : ${num(h.ihi_percent)} %</title></circle>`,
  ).join("");
  const labels = [points[0], points.at(-1)]
    .filter((p, i, arr) => i === 0 || p !== arr[0])
    .map(([px, , h], i) =>
      `<text x="${px}" y="${H - 6}" text-anchor="${history.length === 1 ? "middle" : i === 0 ? "start" : "end"}">${fmtDate(h.timestamp)}</text>`,
    ).join("");

  return `
    <svg class="chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="Historique de l'IHI">
      ${bands}${grid}
      <polyline points="${line}" fill="none" stroke="#111827" stroke-width="2"/>
      ${dots}${labels}
    </svg>`;
}

/** Everything below the headline: family breakdown, drivers, parameters, DGA. */
function evaluationDetails(ev) {
  return `
    <div class="grid cols-2">
      ${familiesCard(ev)}
      ${driversCard(ev)}
    </div>
    ${parametersCard(ev)}
    ${dgaCard(ev.dga)}`;
}

function familiesCard(ev) {
  const rows = ev.families.map((f) => {
    if (f.index === null) {
      return `
        <div class="fam-row">
          <div>${esc(f.label)}</div>
          <div class="missing span-2">pas de données : poids redistribué</div>
          <div class="small muted mono nowrap">poids ${num(f.weight_nominal, 2)}</div><div></div>
        </div>`;
    }
    return `
      <div class="fam-row">
        <div>${esc(f.label)}</div>
        ${meter(f.index, levelFor(f.index * 100), true)}
        <div class="mono">${num(f.index, 3)}</div>
        <div class="small muted mono nowrap" title="poids nominal → poids effectif">poids ${num(f.weight_nominal, 2)} → ${num(f.weight_effective, 3)}</div>
        <div class="small mono nowrap" title="contribution à l'IHI">+${num(f.contribution, 3)}</div>
      </div>`;
  }).join("");
  return `<div class="card"><h2>Indices par famille</h2>${rows}</div>`;
}

function driversCard(ev) {
  const drivers = ev.drivers.map((d) => {
    const [family, param] = d.parameter.split(".");
    return `
      <div class="fam-row" style="grid-template-columns:1fr 1fr 60px">
        <div><strong>${esc(prettyParam(param))}</strong> <span class="muted small">${esc(family)}</span></div>
        ${meter(d.sub_index, levelFor(d.sub_index * 100), true)}
        <div class="mono">${num(d.sub_index, 3)}</div>
      </div>`;
  }).join("");
  const notes = ev.notes.map((n) => `<p class="note">ⓘ ${esc(n)}</p>`).join("");
  return `
    <div class="card">
      <h2>Paramètres qui pèsent le plus sur l'IHI</h2>
      ${drivers || '<p class="muted">Aucun paramètre mesuré.</p>'}
      ${notes}
    </div>`;
}

function parametersCard(ev) {
  const rows = ev.families.filter((f) => f.parameters.length).map((f) => {
    const header = `<tr><th colspan="5" style="padding-top:18px">${esc(f.label)}</th></tr>`;
    const params = f.parameters.map((p) => {
      const unit = unitLabel(p.unit);
      const value = p.value === null || p.value === undefined
        ? '<span class="missing">non mesuré</span>'
        : `<span class="mono">${numAuto(p.value)}</span> <span class="muted">${esc(unit)}</span>`;
      const si = p.sub_index === null
        ? `<span class="muted">${DASH}</span>`
        : `<div class="ihi-cell">${meter(p.sub_index, levelFor(p.sub_index * 100))}<span class="mono">${num(p.sub_index, 2)}</span></div>`;
      return `
        <tr>
          <td>${esc(prettyParam(p.name))}</td>
          <td>${value}</td>
          <td class="mono muted">${numAuto(p.normal)}</td>
          <td class="mono muted">${numAuto(p.critical)}</td>
          <td>${si}</td>
        </tr>`;
    }).join("");
    return header + params;
  }).join("");

  return `
    <div class="card">
      <details class="params" open>
        <summary>Mesures et sous-indices</summary>
        <div class="table-wrap">
          <table class="param-table">
            <thead><tr><th>Paramètre</th><th>Valeur</th><th>Normal</th><th>Critique</th><th>Sous-indice</th></tr></thead>
            <tbody>${rows}</tbody>
          </table>
        </div>
      </details>
    </div>`;
}

function dgaCard(dga) {
  const sources = Object.fromEntries(state.config.dga_ratios.map((r) => [r.key, r]));
  const ratios = Object.entries(dga.ratios).map(([key, value]) => `
      <tr>
        <td class="mono">${esc(sources[key]?.label.replace(/[A-Z][a-z]?\d*/g, (g) => prettyParam(g)) ?? key)}</td>
        <td class="mono">${value === null ? `<span class="muted">${DASH}</span>` : num(value, 3)}</td>
        <td class="small muted">${esc(sources[key]?.source ?? "")}</td>
      </tr>`).join("");

  const duvalValues = Object.entries(dga.duval);
  const duval = duvalValues.every(([, v]) => v === null)
    ? '<p class="muted">Indisponible : CH₄, C₂H₄ et C₂H₂ sont nécessaires (et leur somme non nulle).</p>'
    : duvalValues.map(([key, value]) => `
        <div class="fam-row" style="grid-template-columns:60px 1fr 70px">
          <div class="mono">${esc(prettyParam(key.replace("duval_pct_", "")))}</div>
          <div class="meter wide"><span class="fill" style="width:${value}%;background:var(--accent)"></span></div>
          <div class="mono">${num(value)} %</div>
        </div>`).join("");

  let rates;
  if (!dga.rates) {
    rates = '<p class="muted">Indisponible : il faut une mesure antérieure du même transformateur.</p>';
  } else {
    rates = `
      <p class="note" style="margin:0 0 8px">Depuis la mesure du ${fmtDate(dga.rates_since)}</p>
      <table class="param-table"><tbody>${Object.entries(dga.rates).map(([key, value]) => `
        <tr>
          <td class="mono">${esc(prettyParam(key.replace(/^rate_|_ppm_per_day$/g, "")))}</td>
          <td class="mono">${value === null ? `<span class="muted">${DASH}</span>` : signed(value, 2)}</td>
          <td class="small muted">ppm/j</td>
        </tr>`).join("")}</tbody></table>`;
  }

  return `
    <div class="card">
      <h2>Analyse DGA : caractéristiques de diagnostic</h2>
      <p class="note" style="margin:-8px 0 14px">Signaux supplémentaires pour le niveau ML. Ils ne modifient pas l'IHI.</p>
      <div class="grid" style="grid-template-columns:1.4fr 1fr 1fr">
        <div><h2>Rapports de gaz</h2><table class="param-table"><tbody>${ratios}</tbody></table></div>
        <div><h2>Triangle de Duval 1</h2>${duval}</div>
        <div><h2>Vitesse d'évolution</h2>${rates}</div>
      </div>
    </div>`;
}

// ---------------------------------------------------------------------------
// Page: new measurement
// ---------------------------------------------------------------------------
const NEW_TRANSFORMER = "__new__";

function nowForInput() {
  const d = new Date();
  d.setMinutes(d.getMinutes() - d.getTimezoneOffset());   // datetime-local wants local time
  return d.toISOString().slice(0, 16);
}

async function renderMeasure(preselectId) {
  setTopbar("Nouvelle mesure");
  const fleet = await api("/api/fleet");
  const ids = fleet.transformers.map((t) => t.id).sort();
  const selected = preselectId && ids.includes(preselectId) ? preselectId : ids[0] ?? NEW_TRANSFORMER;

  const options = ids.map((id) => `<option value="${esc(id)}"${id === selected ? " selected" : ""}>${esc(id)}</option>`).join("")
    + `<option value="${NEW_TRANSFORMER}"${selected === NEW_TRANSFORMER ? " selected" : ""}>+ Nouveau transformateur</option>`;

  const familyFieldsets = state.config.families.map((f) => {
    if (!f.parameters.length) {
      return `<fieldset><legend>${esc(f.label)} <span class="muted small">· poids ${num(f.weight, 2)}</span></legend>
        <p class="muted" style="margin:0">Aucun paramètre défini dans config/thresholds.yaml : cette famille est ignorée et son poids redistribué.</p></fieldset>`;
    }
    const fields = f.parameters.map((p) => {
      const unit = unitLabel(p.unit);
      const lowGood = p.polarity === "low_good";
      const hint = lowGood
        ? `normal ≤ ${numAuto(p.normal)} · critique ≥ ${numAuto(p.critical)}`
        : `normal ≥ ${numAuto(p.normal)} · critique ≤ ${numAuto(p.critical)}`;
      return `
        <div class="field" data-field="${esc(p.name)}">
          <label for="p-${esc(p.name)}">${esc(prettyParam(p.name))}${unit ? ` <span class="muted">(${esc(unit)})</span>` : ""}</label>
          <input id="p-${esc(p.name)}" data-param="${esc(p.name)}" inputmode="decimal" autocomplete="off">
          <div class="hint">${hint}</div>
        </div>`;
    }).join("");
    return `<fieldset><legend>${esc(f.label)} <span class="muted small">· poids ${num(f.weight, 2)}</span></legend><div class="form-grid">${fields}</div></fieldset>`;
  }).join("");

  view().innerHTML = `
    <form id="measure-form" novalidate>
      <fieldset>
        <legend>Transformateur et date</legend>
        <div class="form-grid">
          <div class="field" data-field="transformer">
            <label for="tid">Transformateur</label>
            <select id="tid">${options}</select>
          </div>
          <div class="field new-only" data-field="id"><label for="new-id">Identifiant</label><input id="new-id" placeholder="TR-09"></div>
          <div class="field new-only" data-field="substation"><label for="new-sub">Poste</label><input id="new-sub" placeholder="Poste 5"></div>
          <div class="field" data-field="timestamp">
            <label for="timestamp">Date de mesure</label>
            <input id="timestamp" type="datetime-local" value="${nowForInput()}">
          </div>
        </div>
        <div class="form-actions" style="margin-bottom:0;margin-top:14px">
          <button type="button" class="btn" id="prefill">Reprendre la dernière mesure</button>
          <span class="note" style="margin:0">Pré-remplit le formulaire : modifiez une valeur puis « Calculer » pour voir son effet.</span>
        </div>
      </fieldset>
      <p class="note" style="margin:0 0 12px">Laissez vide un paramètre non mesuré. La virgule décimale est acceptée.</p>
      ${familyFieldsets}
      <div id="form-messages"></div>
      <div class="form-actions">
        <button type="submit" class="btn">Calculer (sans enregistrer)</button>
        <button type="button" class="btn primary" id="save">Enregistrer la mesure</button>
        <button type="button" class="btn" id="clear">Effacer les valeurs</button>
      </div>
    </form>
    <div id="result"></div>`;

  bindMeasureForm();
}

function bindMeasureForm() {
  const form = document.getElementById("measure-form");
  const select = document.getElementById("tid");

  const toggleNew = () => {
    const isNew = select.value === NEW_TRANSFORMER;
    form.querySelectorAll(".new-only").forEach((el) => { el.hidden = !isNew; });
    document.getElementById("prefill").disabled = isNew;
  };
  select.addEventListener("change", toggleNew);
  toggleNew();

  document.getElementById("prefill").addEventListener("click", async () => {
    const t = await api(`/api/transformers/${encodeURIComponent(select.value)}`);
    clearValues();
    for (const f of t.latest?.families ?? []) {
      for (const p of f.parameters) {
        const input = form.querySelector(`[data-param="${CSS.escape(p.name)}"]`);
        if (input && p.value !== null && p.value !== undefined) input.value = String(p.value).replace(".", ",");
      }
    }
    document.getElementById("timestamp").value = nowForInput();
  });

  document.getElementById("clear").addEventListener("click", () => {
    clearValues();
    document.getElementById("result").innerHTML = "";
  });

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    await submitMeasure(false);
  });
  document.getElementById("save").addEventListener("click", () => submitMeasure(true));
}

function clearValues() {
  document.querySelectorAll("[data-param]").forEach((input) => { input.value = ""; });
  clearErrors();
}

function collectMeasure() {
  const values = {};
  document.querySelectorAll("[data-param]").forEach((input) => {
    const raw = input.value.trim();
    // Send as text: the server-side schema parses and validates numbers, and
    // reports non-numeric input against the right field.
    if (raw) values[input.dataset.param] = raw.replace(",", ".");
  });
  const stamp = document.getElementById("timestamp").value;
  return { values, timestamp: stamp || null };
}

function clearErrors() {
  document.querySelectorAll(".field.invalid").forEach((field) => {
    field.classList.remove("invalid");
    field.querySelector(".error")?.remove();
  });
  document.getElementById("form-messages").innerHTML = "";
}

function showErrors(errors) {
  const general = [];
  for (const e of errors) {
    const field = e.field && document.querySelector(`.field[data-field="${CSS.escape(e.field)}"]`);
    if (field) {
      field.classList.add("invalid");
      field.insertAdjacentHTML("beforeend", `<div class="error">${esc(e.message)}</div>`);
    } else {
      general.push(e.message);
    }
  }
  if (general.length) {
    document.getElementById("form-messages").innerHTML =
      `<div class="alert-box">${general.map(esc).join("<br>")}</div>`;
  }
  document.querySelector(".field.invalid input, .alert-box")?.scrollIntoView({ behavior: "smooth", block: "center" });
}

async function submitMeasure(save) {
  clearErrors();
  const select = document.getElementById("tid");
  const isNew = select.value === NEW_TRANSFORMER;
  const buttons = document.querySelectorAll("#measure-form button");
  buttons.forEach((b) => { b.disabled = true; });

  try {
    const { values, timestamp } = collectMeasure();
    // Always validate + score first, so nothing is created or saved if the reading is invalid.
    const preview = await api("/api/evaluate", {
      method: "POST",
      body: JSON.stringify({ values, timestamp, transformer_id: isNew ? null : select.value }),
    });

    if (!save) {
      showPreview(preview);
      return;
    }

    let id = select.value;
    if (isNew) {
      id = document.getElementById("new-id").value.trim();
      if (!id) {
        showErrors([{ field: "id", message: "Identifiant obligatoire." }]);
        return;
      }
      await api("/api/transformers", {
        method: "POST",
        body: JSON.stringify({ id, substation: document.getElementById("new-sub").value.trim() }),
      });
    }

    await api(`/api/transformers/${encodeURIComponent(id)}/measurements`, {
      method: "POST",
      body: JSON.stringify({ values, timestamp }),
    });
    refreshAlertBadge();
    location.hash = `#/transformateur/${encodeURIComponent(id)}`;
  } catch (error) {
    if (!error.errors) throw error;
    showErrors(error.errors);
  } finally {
    // The form is gone if we navigated away after saving.
    buttons.forEach((b) => { b.disabled = false; });
    const prefill = document.getElementById("prefill");
    if (prefill) prefill.disabled = isNew;
  }
}

function showPreview(ev) {
  const warnings = ev.warnings?.length
    ? `<div class="warn-box">${ev.warnings.map(esc).join("<br>")}</div>` : "";
  const result = document.getElementById("result");
  result.innerHTML = `
    <div class="card-head" style="margin-top:8px"><h2 style="font-size:18px">Résultat du calcul <span class="muted" style="font-weight:400">(non enregistré)</span></h2></div>
    ${warnings}
    <div class="grid cols-2">
      ${scoreCard(ev, `Mesure du ${fmtDate(ev.timestamp)}`)}
      <div class="card">
        <h2>Ce qu'il faut vérifier</h2>
        <p class="muted" style="margin:0">Chaque sous-indice suit la fonction linéaire par morceaux entre les seuils normal et critique. L'indice de famille est leur moyenne, et l'IHI la somme pondérée des familles disponibles.</p>
      </div>
    </div>
    ${evaluationDetails(ev)}`;
  result.scrollIntoView({ behavior: "smooth", block: "start" });
}

// ---------------------------------------------------------------------------
// Page: alerts
// ---------------------------------------------------------------------------
async function renderAlerts() {
  setTopbar("Alertes");
  const alerts = await api("/api/alerts");
  refreshAlertBadge(alerts.length);
  const rules = state.config.alerts;

  const intro = `<p class="note" style="margin:0 0 16px">Règles (config/alerts.yaml) : classe ${rules.alert_classes.map(esc).join(" ou ")}, ou baisse d'au moins ${num(rules.accelerated_decline_pt_per_year)} pt/an entre les deux dernières évaluations.</p>`;
  if (!alerts.length) {
    view().innerHTML = intro + `<div class="card empty">Aucune alerte en cours.</div>`;
    return;
  }

  view().innerHTML = intro + `
    <div class="table-wrap"><table>
      <thead><tr><th>Transformateur</th><th>IHI</th><th>Classe</th><th>Motifs</th><th>Action proposée</th></tr></thead>
      <tbody>${alerts.map((t) => `
        <tr class="clickable" data-id="${esc(t.id)}">
          <td><div class="tid">${esc(t.id)}</div><div class="sub">${esc(t.substation)}</div></td>
          <td class="mono">${num(t.ihi_percent)} %</td>
          <td>${pill(t.classification)}</td>
          <td>${t.alerts.map((a) => `<div>${esc(a)}</div>`).join("")}</td>
          <td>${esc(t.classification.action)}</td>
        </tr>`).join("")}
      </tbody>
    </table></div>`;

  view().querySelectorAll("tr[data-id]").forEach((row) => {
    row.addEventListener("click", () => { location.hash = `#/transformateur/${encodeURIComponent(row.dataset.id)}`; });
  });
}

// ---------------------------------------------------------------------------
// Page: settings (read-only view of config/)
// ---------------------------------------------------------------------------
async function renderSettings() {
  setTopbar("Paramètres");
  const cfg = state.config;

  const weights = cfg.families.map((f) => `
    <tr><td>${esc(f.label)}</td><td class="mono muted">${esc(f.name)}</td>
        <td class="mono">${num(f.weight, 2)}</td><td class="mono">${f.parameters.length}</td></tr>`).join("");
  const totalWeight = cfg.families.reduce((sum, f) => sum + f.weight, 0);

  const thresholds = cfg.families.filter((f) => f.parameters.length).map((f) => `
    <tr><th colspan="6" style="padding-top:18px">${esc(f.label)}</th></tr>
    ${f.parameters.map((p) => `
      <tr>
        <td>${esc(prettyParam(p.name))}</td>
        <td class="mono muted">${esc(p.name)}</td>
        <td>${p.polarity === "low_good" ? "faible = bon" : "élevé = bon"}</td>
        <td class="mono">${numAuto(p.normal)}</td>
        <td class="mono">${numAuto(p.critical)}</td>
        <td class="muted">${esc(unitLabel(p.unit))}${p.allow_negative ? " · négatif autorisé" : ""}</td>
      </tr>`).join("")}`).join("");

  const bands = cfg.bands.map((b) => `
    <tr><td>${pill(b)}</td><td class="mono">${esc(b.band)}</td><td>${esc(b.action)}</td></tr>`).join("");

  const standards = Object.entries(cfg.standards).map(([family, s]) => `
    <tr><td class="mono">${esc(family)}</td><td>${(s.standards || []).map(esc).join(", ")}</td><td class="small muted">${esc(s.note || "")}</td></tr>`).join("");

  view().innerHTML = `
    <div class="warn-box">Lecture seule. Ces valeurs viennent de <code>config/*.yaml</code>. Modifiez les fichiers puis redémarrez le serveur. Les seuils et poids actuels sont des valeurs de départ issues du document de proposition, pas encore validées.</div>
    <div class="grid cols-2">
      <div class="card"><h2>Poids des familles <span class="muted small">(weights.yaml, somme ${num(totalWeight, 2)})</span></h2>
        <table class="param-table"><thead><tr><th>Famille</th><th>Clé</th><th>Poids</th><th>Paramètres</th></tr></thead><tbody>${weights}</tbody></table></div>
      <div class="card"><h2>Classes de santé <span class="muted small">(classification.yaml)</span></h2>
        <table class="param-table"><thead><tr><th>Classe</th><th>IHI</th><th>Action</th></tr></thead><tbody>${bands}</tbody></table>
        <h2 style="margin-top:20px">Alertes <span class="muted small">(alerts.yaml)</span></h2>
        <dl class="kv">
          <dt>Classes en alerte</dt><dd>${cfg.alerts.alert_classes.map(esc).join(", ")}</dd>
          <dt>Baisse accélérée</dt><dd class="mono">≥ ${num(cfg.alerts.accelerated_decline_pt_per_year)} pt/an</dd>
        </dl></div>
    </div>
    <div class="card"><h2>Seuils par paramètre <span class="muted small">(thresholds.yaml)</span></h2>
      <div class="table-wrap"><table class="param-table">
        <thead><tr><th>Paramètre</th><th>Clé</th><th>Polarité</th><th>Normal</th><th>Critique</th><th>Unité</th></tr></thead>
        <tbody>${thresholds}</tbody></table></div></div>
    <div class="card"><h2>Traçabilité normative <span class="muted small">(standards_map.yaml)</span></h2>
      <div class="table-wrap"><table class="param-table">
        <thead><tr><th>Famille</th><th>Normes</th><th>Note</th></tr></thead><tbody>${standards}</tbody></table></div></div>`;
}

// ---------------------------------------------------------------------------
// Page: methodology
// ---------------------------------------------------------------------------
async function renderMethod() {
  setTopbar("Méthodologie");
  const weights = state.config.families
    .map((f) => `${num(f.weight, 2)}·I<sub>${esc(f.name)}</sub>`).join(" + ");

  view().innerHTML = `
    <div class="prose">
      <p>L'IHI suit la chaîne de ARCHITECTURE_IHI (§9) :</p>
      <span class="formula">Mesures brutes → Normalisation → Sous-indices → Poids → IHI → Classe de santé</span>

      <h2>1. Sous-indice par paramètre</h2>
      <p>Chaque mesure est ramenée entre 0 (critique) et 1 (sain) par une fonction linéaire par morceaux entre le seuil normal et le seuil critique.</p>
      <span class="formula">Valeur faible = bon :  I = 1 si X ≤ Xn ;  (Xc − X)/(Xc − Xn) entre les deux ;  0 si X ≥ Xc
Valeur élevée = bon : I = 1 si X ≥ Xn ;  (X − Xc)/(Xn − Xc) entre les deux ;  0 si X ≤ Xc</span>
      <p>Exemple du document : Xn = 100 ppm, Xc = 500 ppm, X = 300 ppm → I = 0,50.</p>

      <h2>2. Indice de famille</h2>
      <p>Moyenne des sous-indices <em>mesurés</em> de la famille. Les pondérations internes (w<sub>j</sub>) seront ajoutées plus tard. Un paramètre non mesuré est ignoré, jamais compté comme sain ni comme nul.</p>

      <h2>3. IHI</h2>
      <span class="formula">IHI = ${weights}</span>
      <p>Si une famille n'a aucune mesure (aujourd'hui : électrique, sans seuils définis), elle est retirée et les poids restants sont renormalisés pour que leur somme reste 1. Le détail de chaque transformateur l'indique.</p>

      <h2>4. Classe et action</h2>
      <p>Le pourcentage est classé selon les bandes de <code>config/classification.yaml</code>, qui donnent aussi l'action proposée.</p>

      <h2>5. Tendance</h2>
      <p>La variation entre les deux dernières évaluations est ramenée à une vitesse en points par an. Une baisse plus rapide que le seuil de <code>config/alerts.yaml</code> est signalée comme « dégradation accélérée » (dIHI/dt ≪ 0, §H du document).</p>

      <h2>6. Caractéristiques DGA</h2>
      <p>Les rapports IEC 60599 / Rogers, les coordonnées du triangle de Duval et les vitesses d'évolution des gaz (ppm/jour) sont calculés pour chaque mesure. Ils ne modifient pas encore l'IHI : ce sont les entrées du futur niveau ML (Tier 2), qui restera borné par ce calcul déterministe.</p>

      <p class="note">Les seuils et poids actuels viennent du document de proposition. Ils doivent être validés par rapport aux normes (voir Paramètres → Traçabilité normative) et aux données du parc.</p>
    </div>`;
}

// ---------------------------------------------------------------------------
// Router
// ---------------------------------------------------------------------------
const ROUTES = [
  [/^#\/parc$/, "parc", renderFleet],
  [/^#\/transformateur\/(.+)$/, "parc", renderDetail],
  [/^#\/mesure(?:\/(.+))?$/, "mesure", renderMeasure],
  [/^#\/alertes$/, "alertes", renderAlerts],
  [/^#\/parametres$/, "parametres", renderSettings],
  [/^#\/methodologie$/, "methodologie", renderMethod],
];

async function router() {
  const hash = location.hash || "#/parc";
  const match = ROUTES.map(([re, nav, render]) => [hash.match(re), nav, render]).find(([m]) => m);
  if (!match) {
    location.hash = "#/parc";
    return;
  }
  const [m, nav, render] = match;

  document.querySelectorAll("#nav a").forEach((a) => a.classList.toggle("active", a.dataset.route === nav));
  view().innerHTML = '<div class="loading">Chargement…</div>';
  window.scrollTo(0, 0);

  try {
    await render(...m.slice(1).map((part) => (part === undefined ? undefined : decodeURIComponent(part))));
  } catch (error) {
    const message = error.errors ? error.errors.map((e) => e.message).join(" ") : error.message;
    view().innerHTML = `<div class="alert-box"><strong>Impossible d'afficher la page.</strong><br>${esc(message)}</div>`;
    console.error(error);
  }
}

async function start() {
  try {
    state.config = await api("/api/config");
  } catch (error) {
    view().innerHTML = `<div class="alert-box">Le serveur IHI ne répond pas. Lancez <code>python run_dashboard.py</code>.</div>`;
    return;
  }
  window.addEventListener("hashchange", router);
  await router();
  refreshAlertBadge();   // the sidebar badge is visible on every page
}

start();
