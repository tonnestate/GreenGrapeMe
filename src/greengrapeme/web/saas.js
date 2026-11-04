"use strict";

// OIDC Authorization Code + PKCE. No client secret and no persistent
// storage of access/refresh/ID tokens. All business data is escaped via
// textContent; token/tenant claims never bypass backend authorization.
const $ = (id) => document.getElementById(id);
const state = { config: null, token: null, expiresAt: 0, tenant: "",
                role: "", companyOffset: 0, companyTotal: 0 };
const LOGIN_TRANSACTION = "gg-oidc-pkce-transaction";
const PAGE_SIZE = 40;

function say(message, login = false) {
  const target = $(login ? "login-feedback" : "app-feedback");
  target.textContent = String(message || "");
}
function value(id) { return $(id).value.trim(); }
function base64url(bytes) {
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/g, "");
}
function randomSecret(size = 32) {
  return base64url(crypto.getRandomValues(new Uint8Array(size)));
}
async function digestS256(text) {
  return base64url(new Uint8Array(await crypto.subtle.digest(
    "SHA-256", new TextEncoder().encode(text))));
}
function expired() {
  return !state.token || Date.now() >= state.expiresAt;
}
function headers(write = false) {
  if (expired()) throw new Error("Die Anmeldung ist abgelaufen. Bitte erneut anmelden.");
  if (!state.tenant) throw new Error("Bitte zuerst einen Mandanten öffnen.");
  const result = {
    "Authorization": "Bearer " + state.token,
    "X-Green-Grape-Tenant": state.tenant,
  };
  if (write) result["Content-Type"] = "application/json";
  return result;
}
async function api(path, { method = "GET", body = null } = {}) {
  const response = await fetch(path, {
    method, headers: headers(method !== "GET"),
    ...(body !== null ? { body: JSON.stringify(body) } : {}),
    cache: "no-store", credentials: "omit", redirect: "error",
  });
  const result = await response.json().catch(() => ({}));
  if (response.status === 401) {
    state.token = null;
    state.expiresAt = 0;
    $("workspace").hidden = true;
    $("login").hidden = false;
    $("tenant-form").hidden = true;
    $("login-button").hidden = false;
    throw new Error("Sitzung abgelaufen. Bitte neu anmelden.");
  }
  if (!response.ok) {
    const known = { 400: "Ungültige Eingabe oder widersprüchlicher Datensatz.",
      403: "Keine Berechtigung für diesen Mandanten oder Vorgang.",
      404: "Datensatz nicht vorhanden.", 409: "Datensatzkonflikt.",
      500: "Interner Fehler; der Vorgang wurde nicht bestätigt." };
    throw new Error(known[response.status] || "Anfrage fehlgeschlagen (" + response.status + ").");
  }
  return result;
}
async function loadConfig() {
  const response = await fetch("/public/config", {
    cache: "no-store", credentials: "omit",
  });
  if (!response.ok) throw new Error("OIDC-Anmeldung ist nicht konfiguriert.");
  const config = await response.json();
  for (const field of ["authorization_endpoint", "token_endpoint",
                       "client_id", "redirect_uri", "scope"]) {
    if (typeof config[field] !== "string" || !config[field]) {
      throw new Error("Ungültige OIDC-Konfiguration.");
    }
  }
  if (new URL(config.redirect_uri).origin !== window.location.origin) {
    throw new Error("OIDC-Rücksprungadresse passt nicht zum SaaS-Host.");
  }
  state.config = config;
}
async function beginLogin() {
  try {
    if (!state.config) await loadConfig();
    const verifier = randomSecret(32);
    const challenge = await digestS256(verifier);
    const oidcState = randomSecret(32);
    const nonce = randomSecret(32);
    sessionStorage.setItem(LOGIN_TRANSACTION, JSON.stringify({
      verifier, state: oidcState, nonce, createdAt: Date.now(),
    }));
    const target = new URL(state.config.authorization_endpoint);
    target.searchParams.set("client_id", state.config.client_id);
    target.searchParams.set("response_type", "code");
    target.searchParams.set("redirect_uri", state.config.redirect_uri);
    target.searchParams.set("scope", state.config.scope);
    target.searchParams.set("state", oidcState);
    target.searchParams.set("nonce", nonce);
    target.searchParams.set("code_challenge", challenge);
    target.searchParams.set("code_challenge_method", "S256");
    window.location.assign(target.toString());
  } catch (error) {
    say(error.message, true);
  }
}
async function receiveAuthorizationCode() {
  const target = new URL(window.location.href);
  const code = target.searchParams.get("code");
  const returnedState = target.searchParams.get("state");
  const failure = target.searchParams.get("error");
  if (!code && !failure && !returnedState) return;
  // Remove all callback parameters from browser history before parsing them.
  window.history.replaceState(null, "", target.pathname);
  // Ambiguous callback parameters must never be resolved by taking the first
  // value. A replayed or malformed response also consumes the transaction.
  const counts = ["code", "state", "error"].map(
    (name) => target.searchParams.getAll(name).length);
  const stored = sessionStorage.getItem(LOGIN_TRANSACTION);
  sessionStorage.removeItem(LOGIN_TRANSACTION);
  if (counts.some((count) => count > 1) ||
      (code && failure) || !returnedState || !code && !failure) {
    throw new Error("Ungültiger OIDC-Anmelderücksprung.");
  }
  if (failure) throw new Error("Anmeldung vom Identitätsanbieter abgelehnt.");
  let txn;
  try { txn = JSON.parse(stored || "null"); } catch (_) { txn = null; }
  if (!txn || typeof txn.verifier !== "string" ||
      returnedState !== txn.state || !Number.isFinite(txn.createdAt) ||
      Date.now() - txn.createdAt > 10 * 60 * 1000 ||
      txn.createdAt > Date.now() + 30000) {
    throw new Error("Ungültiger oder abgelaufener Anmeldeversuch.");
  }
  const form = new URLSearchParams();
  form.set("grant_type", "authorization_code");
  form.set("client_id", state.config.client_id);
  form.set("code", code);
  form.set("redirect_uri", state.config.redirect_uri);
  form.set("code_verifier", txn.verifier);
  const response = await fetch(state.config.token_endpoint, {
    method: "POST", body: form,
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    cache: "no-store", credentials: "omit", mode: "cors", redirect: "error",
  });
  if (!response.ok) throw new Error("OIDC-Codetausch fehlgeschlagen.");
  const tokens = await response.json();
  if (typeof tokens.access_token !== "string" ||
      tokens.access_token.length < 16 ||
      String(tokens.token_type || "").toLowerCase() !== "bearer" ||
      !Number.isFinite(Number(tokens.expires_in)) ||
      Number(tokens.expires_in) <= 0) {
    throw new Error("Identitätsanbieter lieferte kein gültiges Zugriffstoken.");
  }
  // Access token exists only in JS memory; refresh and ID tokens are
  // deliberately ignored. Server verifies the JWT independently.
  state.token = tokens.access_token;
  state.expiresAt = Date.now() + Math.max(0, Number(tokens.expires_in) - 30) * 1000;
  $("login-button").hidden = true;
  $("tenant-form").hidden = false;
  $("tenant-id").focus();
  $("auth-status").textContent = "Angemeldet, Mandant auswählen";
  say("Anmeldung erfolgreich. Bitte Mandantenkennung eingeben.", true);
}
function td(row, text) {
  const cell = document.createElement("td");
  cell.textContent = String(text ?? "–");
  row.appendChild(cell);
  return cell;
}
function emptyRow(tbody, columns, message) {
  const row = document.createElement("tr");
  const cell = td(row, message);
  cell.colSpan = columns;
  tbody.appendChild(row);
}
function euro(cents) {
  // Missing financial evidence is not a verified zero amount.
  if (typeof cents !== "number" || !Number.isSafeInteger(cents)) return "–";
  return new Intl.NumberFormat("de-DE", {
    style: "currency", currency: "EUR",
  }).format(cents / 100);
}
function renderView(id) {
  const views = ["companies-view", "discovery-view", "pilots-view",
                 "sales-view", "finance-view"];
  for (const item of views) $(item).hidden = item !== id;
  document.querySelectorAll('nav[aria-label="Produktbereiche"] button')
    .forEach((button) => {
      if (button.dataset.view === id) button.setAttribute("aria-current", "page");
      else button.removeAttribute("aria-current");
    });
}
async function overview() {
  const [report, pilots] = await Promise.all([
    api("/api/overview"), api("/api/pilots"),
  ]);
  $("metric-companies").textContent = report.opportunities ?? "–";
  $("metric-work").textContent = report.work_items ?? "–";
  $("metric-missions").textContent = report.missions ?? "–";
  $("metric-pilots").textContent = pilots.items?.length ?? "–";
}
async function companies() {
  const query = value("company-query");
  const params = new URLSearchParams({
    q: query, limit: String(PAGE_SIZE),
    offset: String(state.companyOffset),
  });
  const report = await api("/api/companies?" + params.toString());
  state.companyTotal = report.total || 0;
  const out = $("companies-list");
  out.replaceChildren();
  for (const item of (report.items || [])) {
    const tr = document.createElement("tr");
    td(tr, item.company_name);
    td(tr, item.offer_id);
    td(tr, item.qualification);
    td(tr, item.suppressed ? (item.suppression_reason || "Gesperrt") : "Keine lokale Sperre");
    const cell = document.createElement("td");
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = "Öffnen";
    button.addEventListener("click", async () => {
      try {
        const detail = await api("/api/company?id=" + encodeURIComponent(item.opportunity_id));
        const target = $("company-details");
        target.replaceChildren();
        const heading = document.createElement("h3");
        heading.textContent = detail.company_name || item.company_name;
        const text = document.createElement("pre");
        text.textContent = JSON.stringify(detail, null, 2);
        text.style.whiteSpace = "pre-wrap";
        text.style.overflowWrap = "anywhere";
        target.append(heading, text);
        target.hidden = false;
      } catch (error) { say(error.message); }
    });
    cell.appendChild(button);
    tr.appendChild(cell);
    out.appendChild(tr);
  }
  if (!report.items?.length) emptyRow(out, 5, "Keine passenden Unternehmen.");
  $("companies-count").textContent = state.companyTotal + " Unternehmen";
  $("companies-page").textContent =
    (state.companyOffset + 1) + "–" +
    Math.min(state.companyOffset + PAGE_SIZE, state.companyTotal) +
    " / " + state.companyTotal;
  $("companies-prev").disabled = state.companyOffset === 0;
  $("companies-next").disabled = state.companyOffset + PAGE_SIZE >= state.companyTotal;
}
async function discovery() {
  const result = await api("/api/discovery-jobs");
  const out = $("discovery-list");
  out.replaceChildren();
  for (const item of result.items || []) {
    const row = document.createElement("tr");
    for (const value of [
      item.request_id, item.offer_id, item.state, item.error_kind || "–"
    ]) td(row, value);
    out.appendChild(row);
  }
  if (!result.items?.length) emptyRow(out, 4, "Noch keine Discovery-Aufträge.");
}
async function pilots() {
  const result = await api("/api/pilots");
  const out = $("pilots-list");
  out.replaceChildren();
  for (const item of result.items || []) {
    const proof = item.commercial_reconciliation || {};
    const row = document.createElement("tr");
    for (const value of [
      item.label || item.pilot_id,
      euro(item.planned_monthly_fee_cents),
      euro(item.platform_payment_confirmed_cents),
      euro(item.client_payment_confirmed_cents),
      proof.independently_confirmed_contract_accounts ?? "0",
      proof.gap_total ?? "0",
    ]) td(row, value);
    out.appendChild(row);
  }
  if (!result.items?.length) emptyRow(out, 6, "Noch keine Pilotprojekte.");
}
async function crmWorklist() {
  const pilot = value("crm-pilot-id");
  if (!pilot) throw new Error("Bitte eine Pilot-ID eingeben.");
  const filter = "?pilot=" + encodeURIComponent(pilot);
  // Never retain a different pilot's cases after a failed request.
  $("crm-case-list").replaceChildren();
  $("crm-followup-list").replaceChildren();
  $("crm-case-count").textContent = "";
  $("crm-followup-count").textContent = "";
  // The API checks the current OIDC subject and tenant membership on each read.
  // Neither a queued follow-up nor a reported case grants contact authority.
  const [cases, due] = await Promise.all([
    api("/api/pilot-cases" + filter),
    api("/api/pilot-followups" + filter),
  ]);
  const casesBody = $("crm-case-list");
  const dueBody = $("crm-followup-list");
  // Publish both lists only after both tenant-scoped requests succeed.
  const caseRows = document.createDocumentFragment();
  for (const item of cases.items || []) {
    const row = document.createElement("tr");
    for (const field of [item.case_id, item.company_name, item.state,
      item.next_followup_at || "–",
      item.suppressed ? "Gesperrt" : "Keine lokale Sperre"]) td(row, field);
    caseRows.appendChild(row);
  }
  const dueRows = document.createDocumentFragment();
  for (const item of due.items || []) {
    const row = document.createElement("tr");
    for (const field of [item.case_id, item.company_name,
      item.next_followup_at || "–", item.review_state]) td(row, field);
    dueRows.appendChild(row);
  }
  casesBody.replaceChildren(caseRows);
  dueBody.replaceChildren(dueRows);
  if (!cases.items?.length) emptyRow(casesBody, 5, "Keine CRM-Vorgänge.");
  if (!due.items?.length) emptyRow(dueBody, 4, "Keine fälligen Wiedervorlagen.");
  $("crm-case-count").textContent =
    String(cases.total ?? 0) + " Vorgänge (maximal 100 angezeigt)";
  $("crm-followup-count").textContent =
    String(due.total ?? 0) + " fällige Wiedervorlagen (maximal 100 angezeigt; kein Kontaktauftrag)";
}
function clearCrmWorklist() {
  $("crm-pilot-id").value = "";
  $("crm-case-list").replaceChildren();
  $("crm-followup-list").replaceChildren();
  $("crm-case-count").textContent = "";
  $("crm-followup-count").textContent = "";
}

async function openTenant(event) {
  event.preventDefault();
  try {
    if (expired()) throw new Error("Bitte erneut anmelden.");
    const proposed = value("tenant-id");
    if (!/^[A-Za-z0-9][A-Za-z0-9_.-]{1,79}$/.test(proposed)) {
      throw new Error("Ungültige Mandantenkennung.");
    }
    state.tenant = proposed;
    const me = await api("/api/me");
    state.role = me.role || "";
    clearCrmWorklist();
    // Do not expose the workspace until initial tenant-scoped queries pass.
    // An authorization failure must leave the previous tenant's view closed.
    $("workspace").hidden = true;
    $("auth-status").textContent = "Mandant wird geprüft: " + proposed;
    $("workspace-info").textContent =
      "Mandant: " + proposed + " | Rolle: " + state.role +
      " | Geschützte API mit aktuellen Berechtigungen";
    const operates = ["operator", "admin"].includes(state.role);
    const finance = ["finance", "admin"].includes(state.role);
    $("discovery-form").hidden = !operates;
    $("inbound-form").hidden = !operates;
    $("sales-step-form").hidden = !operates;
    $("pilot-form").hidden = !finance;
    $("payment-form").hidden = !finance;
    renderView("companies-view");
    await Promise.all([overview(), companies()]);
    $("login").hidden = true;
    $("workspace").hidden = false;
    $("auth-status").textContent = "Mandant: " + proposed;
    say("");
  } catch (error) {
    state.tenant = "";
    state.role = "";
    $("workspace").hidden = true;
    $("login").hidden = false;
    $("company-details").hidden = true;
    clearCrmWorklist();
    $("auth-status").textContent = "Mandant nicht geöffnet";
    say(error.message, true);
  }
}
function onForm(id, operation) {
  $(id).addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      const message = await operation();
      say(message || "Vorgang gespeichert.");
      await overview();
    } catch (error) { say(error.message); }
  });
}
function integers(id) {
  const n = Number(value(id));
  if (!Number.isSafeInteger(n)) throw new Error("Ungültiger Cent-Betrag.");
  return n;
}
function logout() {
  state.token = null;
  state.expiresAt = 0;
  state.tenant = "";
  state.role = "";
  $("workspace").hidden = true;
  $("login").hidden = false;
  $("tenant-form").hidden = true;
  $("login-button").hidden = false;
  $("auth-status").textContent = "Nicht angemeldet";
  $("company-details").hidden = true;
  clearCrmWorklist();
  say("Lokale Sitzung beendet; eine IdP-Sitzung muss ggf. separat beendet werden.", true);
}
async function main() {
  $("login-button").addEventListener("click", beginLogin);
  $("tenant-form").addEventListener("submit", openTenant);
  $("crm-case-filter").addEventListener("submit", async (event) => {
    event.preventDefault();
    try { await crmWorklist(); say(""); }
    catch (error) { say(error.message); }
  });
  $("logout-button").addEventListener("click", logout);
  document.querySelectorAll('nav[aria-label="Produktbereiche"] button')
    .forEach((button) => button.addEventListener("click", async () => {
      renderView(button.dataset.view);
      try {
        if (button.dataset.view === "companies-view") await companies();
        if (button.dataset.view === "discovery-view") await discovery();
        if (button.dataset.view === "pilots-view") await pilots();
      } catch (error) { say(error.message); }
    }));
  $("company-search").addEventListener("submit", async (event) => {
    event.preventDefault();
    state.companyOffset = 0;
    try { await companies(); } catch (error) { say(error.message); }
  });
  $("companies-prev").addEventListener("click", async () => {
    state.companyOffset = Math.max(0, state.companyOffset - PAGE_SIZE);
    try { await companies(); } catch (error) { say(error.message); }
  });
  $("companies-next").addEventListener("click", async () => {
    if (state.companyOffset + PAGE_SIZE >= state.companyTotal) return;
    state.companyOffset += PAGE_SIZE;
    try { await companies(); } catch (error) { say(error.message); }
  });
  $("disc-mode").addEventListener("change", () => {
    const creating = value("disc-mode") === "new";
    $("disc-existing-fields").hidden = creating;
    $("disc-new-fields").hidden = !creating;
    $("disc-job").required = !creating;
    $("disc-nace").required = creating;
    for (const id of ["disc-south", "disc-west", "disc-north", "disc-east"]) {
      $(id).required = creating;
    }
  });
  onForm("discovery-form", async () => {
    const mode = value("disc-mode");
    const spec = {
      mode, offer_id: value("disc-offer"),
      objective: value("disc-objective"), icp: value("disc-icp"),
    };
    if (mode === "existing") {
      spec.job_id = value("disc-job");
    } else if (mode === "new") {
      if (!$("disc-rights").checked) {
        throw new Error("Bitte die Datenquellen-Nutzungsrechte ausdrücklich bestätigen.");
      }
      const number = (id) => {
        const raw = value(id);
        if (!raw) throw new Error("Geografische Angaben dürfen nicht fehlen.");
        const n = Number(raw);
        if (!Number.isFinite(n)) throw new Error("Ungültige geografische Angabe.");
        return n;
      };
      const south = number("disc-south"), west = number("disc-west");
      const north = number("disc-north"), east = number("disc-east");
      const seed_km = number("disc-seed-km"), max_searches = number("disc-searches");
      if (!(south >= 45 && south < north && north <= 56 &&
            west >= 5 && west < east && east <= 16 &&
            seed_km >= 1 && seed_km <= 50 &&
            Number.isSafeInteger(max_searches) && max_searches >= 1 && max_searches <= 10)) {
        throw new Error("Discovery-Grenzen sind ungültig.");
      }
      const search_terms = value("disc-terms").split(/\\r?\\n/)
        .map((term) => term.trim()).filter(Boolean);
      if (search_terms.length > 8 || search_terms.some((term) => term.length > 100)) {
        throw new Error("Maximal acht Suchbegriffe mit jeweils höchstens 100 Zeichen.");
      }
      Object.assign(spec, {
        nace: value("disc-nace"), south, west, north, east,
        seed_km, max_searches, search_terms,
        source_rights_acknowledged: true,
      });
    } else {
      throw new Error("Unbekannter Discovery-Modus.");
    }
    await api("/api/discovery-jobs", {
      method: "POST", body: { request_id: crypto.randomUUID(), spec },
    });
    await discovery();
    return "Discovery-Auftrag in Queue aufgenommen (Host-Freigabe für externe Ausführung bleibt erforderlich).";
  });
  onForm("inbound-form", async () => {
    const result = await api("/api/pilot-inbound", {
      method: "POST", body: {
        pilot_id: value("inbound-pilot"), case_id: value("inbound-case"),
        company_name: value("inbound-company"),
        channel: value("inbound-channel"),
        evidence_ref: value("inbound-evidence"),
      },
    });
    return "Eingang dokumentiert: " + result.state;
  });
  onForm("sales-step-form", async () => {
    const result = await api("/api/pilot-step", {
      method: "POST", body: {
        pilot_id: value("step-pilot"), case_id: value("step-case"),
        step_id: value("step-id"), expected_state: value("step-from"),
        to_state: value("step-to"), evidence_ref: value("step-evidence"),
        followup_at: value("step-followup"),
      },
    });
    return "CRM-Status dokumentiert: " + result.state;
  });
  onForm("pilot-form", async () => {
    await api("/api/pilots", {method: "POST", body: {
      pilot_id: value("pilot-id"), offer_id: value("pilot-offer"),
      label: value("pilot-label"),
      monthly_fee_cents: integers("pilot-monthly"),
      setup_fee_cents: integers("pilot-setup"),
    }});
    await pilots();
    return "Pilotbedingungen erfasst (noch kein Umsatz).";
  });
  onForm("payment-form", async () => {
    const result = await api("/api/pilot-record", {method: "POST", body: {
      pilot_id: value("payment-pilot"), event_id: value("payment-id"),
      kind: value("payment-kind"),
      opportunity_id: value("payment-account"),
      amount_cents: integers("payment-cents"),
      evidence_ref: value("payment-evidence"), occurred_at: null,
    }});
    await pilots();
    return "Finanzereignis gespeichert als " + result.state +
      " (keine unabhängige Zahlungsbestätigung).";
  });
  try {
    await loadConfig();
    await receiveAuthorizationCode();
  } catch (error) {
    say(error.message, true);
  }
}
main();
