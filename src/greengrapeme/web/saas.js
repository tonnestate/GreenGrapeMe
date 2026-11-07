"use strict";

// OIDC Authorization Code + PKCE. No client secret and no persistent
// storage of access/refresh/ID tokens. All business data is escaped via
// textContent; token/tenant claims never bypass backend authorization.
const $ = (id) => document.getElementById(id);
const state = { config: null, token: null, expiresAt: 0, tenant: "",
                role: "", companyOffset: 0, companyTotal: 0, generation: 0,
                companyQueryRevision: 0, crmQueryRevision: 0,
                caseReviewRevision: 0, caseReview: null, caseStepDraft: null,
                publicInquiryRevision: 0, publicInboxEnabled: false,
                journeyQueryRevision: 0, companyDetailRevision: 0,
                discoveryDraft: null };
const LOGIN_TRANSACTION = "gg-oidc-pkce-transaction";
const PAGE_SIZE = 40;

function say(message, login = false) {
  const target = $(login ? "login-feedback" : "app-feedback");
  target.textContent = String(message || "");
}
function value(id) { return $(id).value.trim(); }
// An old tenant's response must never mutate a newer tenant's DOM.
class StaleContextError extends Error {
  constructor() { super("Veraltete Sitzung oder Mandantenanfrage verworfen."); }
}
function assertGeneration(generation) {
  if (generation !== state.generation) throw new StaleContextError();
}
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
  if (expired()) {
    logout();
    throw new Error("Die Anmeldung ist abgelaufen. Bitte erneut anmelden.");
  }
  if (!state.tenant) throw new Error("Bitte zuerst einen Mandanten öffnen.");
  const result = {
    "Authorization": "Bearer " + state.token,
    "X-Green-Grape-Tenant": state.tenant,
  };
  if (write) result["Content-Type"] = "application/json";
  return result;
}
async function api(path, { method = "GET", body = null } = {}) {
  const requestHeaders = headers(method !== "GET");
  const generation = state.generation;
  const tenant = state.tenant;
  const token = state.token;
  const response = await fetch(path, {
    method, headers: requestHeaders,
    ...(body !== null ? { body: JSON.stringify(body) } : {}),
    cache: "no-store", credentials: "omit", redirect: "error",
  });
  assertGeneration(generation);
  const result = await response.json().catch(() => ({}));
  assertGeneration(generation);
  if (state.tenant !== tenant || state.token !== token) {
    throw new StaleContextError();
  }
  if (response.status === 401) {
    logout();
    say("Sitzung abgelaufen. Bitte neu anmelden.", true);
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
  const loginGeneration = state.generation;
  const response = await fetch(state.config.token_endpoint, {
    method: "POST", body: form,
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    cache: "no-store", credentials: "omit", mode: "cors", redirect: "error",
  });
  if (!response.ok) throw new Error("OIDC-Codetausch fehlgeschlagen.");
  const tokens = await response.json();
  assertGeneration(loginGeneration);
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
  const generation = state.generation;
  const [report, pilots] = await Promise.all([
    api("/api/overview"), api("/api/pilots"),
  ]);
  assertGeneration(generation);
  $("metric-companies").textContent = report.opportunities ?? "–";
  $("metric-work").textContent = report.work_items ?? "–";
  $("metric-missions").textContent = report.missions ?? "–";
  $("metric-pilots").textContent = pilots.items?.length ?? "–";
}
async function companies() {
  const generation = state.generation;
  const revision = ++state.companyQueryRevision;
  // Detail view must represent the currently visible company result set.
  state.companyDetailRevision += 1;
  $("company-details").replaceChildren();
  $("company-details").hidden = true;
  const query = value("company-query");
  const params = new URLSearchParams({
    q: query, limit: String(PAGE_SIZE),
    offset: String(state.companyOffset),
  });
  const report = await api("/api/companies?" + params.toString());
  assertGeneration(generation);
  if (revision !== state.companyQueryRevision) return;
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
      const detailRevision = ++state.companyDetailRevision;
      try {
        assertGeneration(generation);
        const detail = await api("/api/company?id=" + encodeURIComponent(item.opportunity_id));
        assertGeneration(generation);
        if (detailRevision !== state.companyDetailRevision ||
            revision !== state.companyQueryRevision) return;
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
      } catch (error) {
        if (generation === state.generation && !(error instanceof StaleContextError)) {
          say(error.message);
        }
      }
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
  const generation = state.generation;
  const result = await api("/api/discovery-jobs");
  assertGeneration(generation);
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
  const generation = state.generation;
  const result = await api("/api/pilots");
  assertGeneration(generation);
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
function clearJourney() {
  state.journeyQueryRevision += 1;
  $("journey-list").replaceChildren();
  $("journey-summary").textContent = "";
  $("journey-financials").textContent = "";
}
async function customerJourney() {
  const generation = state.generation;
  const revision = ++state.journeyQueryRevision;
  const pilot = value("crm-pilot-id");
  const caseId = value("journey-case");
  if (!pilot || !caseId) throw new Error("Pilot-ID und CRM-Vorgangs-ID sind erforderlich.");
  $("journey-list").replaceChildren();
  $("journey-summary").textContent = "";
  $("journey-financials").textContent = "";
  const result = await api("/api/pilot-journey?pilot=" +
    encodeURIComponent(pilot) + "&case=" + encodeURIComponent(caseId));
  assertGeneration(generation);
  if (revision !== state.journeyQueryRevision) return;
  const rows = document.createDocumentFragment();
  for (const item of result.milestones || []) {
    const row = document.createElement("tr");
    td(row, item.name);
    td(row, item.state);
    rows.appendChild(row);
  }
  $("journey-list").replaceChildren(rows);
  $("journey-summary").textContent = result.company_name +
    " | CRM: " + result.crm_state +
    " | Nächste Prüfung: " + result.next_action +
    " | Kontaktberechtigung: " + result.contact_authority +
    " | Sperren: " + (result.blocking_reasons || []).join(", ");
  const financial = result.financials;
  $("journey-financials").textContent =
    "Bestätigte Kunden-Zahlungseingänge netto: " +
    euro(financial.confirmed_customer_net_cash_cents) +
    " | Offene bestätigte Forderungen: " +
    euro(financial.confirmed_outstanding_cents) +
    " | Zu klärende Rückerstattungen: " +
    euro(financial.refund_due_cents) +
    " | Kein Nachweis für Plattformumsatz oder verursachten Mehrumsatz.";
}

function clearPublicInquiries() {
  state.publicInquiryRevision += 1;
  $("public-inquiry-list").replaceChildren();
  $("public-inquiry-count").textContent = "";
  for (const id of ["inquiry-review-id", "inquiry-review-pilot"]) $(id).value = "";
}

async function publicInquiries() {
  const generation=state.generation;
  const revision=++state.publicInquiryRevision;
  $("public-inquiry-list").replaceChildren();
  $("public-inquiry-count").textContent = "";
  if (!state.publicInboxEnabled) return;
  const data=await api("/api/public-pilot-inquiries");
  assertGeneration(generation);
  if (revision !== state.publicInquiryRevision) return;
  const fragment=document.createDocumentFragment();
  for (const item of data.items || []) {
    const row=document.createElement("tr");
    for (const field of [item.inquiry_id, item.company_name,
      item.contact_email, item.message, item.submitted_at, item.state,
      item.case_id ? (item.pilot_id + " / " + item.case_id) : "–"]) td(row, field);
    const action=td(row,"");
    const button=document.createElement("button");
    button.type="button";
    if (item.state==="ADOPTED" && item.pilot_id && item.case_id) {
      button.textContent="CRM öffnen";
      button.addEventListener("click",async () => {
        try {
          $("crm-pilot-id").value=item.pilot_id;
          await crmWorklist();
          await openCrmCase(item.pilot_id,item.case_id);
          await customerJourney();
          say("");
        } catch (error) {
          if (!(error instanceof StaleContextError)) say(error.message);
        }
      });
    } else {
      button.textContent="Anfrage prüfen";
      button.addEventListener("click",() => {
        $("inquiry-review-id").value=item.inquiry_id;
        $("inquiry-review-pilot").focus();
      });
    }
    action.replaceChildren(button);
    fragment.appendChild(row);
  }
  $("public-inquiry-list").replaceChildren(fragment);
  if (!data.items?.length) {
    emptyRow($("public-inquiry-list"),8,"Keine öffentlichen Pilotanfragen.");
  }
  $("public-inquiry-count").textContent =
    String(data.pending ?? 0) + " neue oder in Übernahme befindliche Anfragen; " +
    String(data.total ?? 0) + " insgesamt sichtbar (maximal 50).";
}

const CRM_NEXT_LABELS = {
  QUALIFIED_REPORTED: "Als qualifiziert gemeldet",
  FOLLOWUP_SCHEDULED: "Wiedervorlage planen",
  FOLLOWUP_RECORDED: "Wiedervorlage als bearbeitet melden",
  MEETING_HELD_REPORTED: "Gespräch als durchgeführt melden",
  PROPOSAL_DELIVERED_REPORTED: "Angebot als übergeben melden",
  DEAL_SIGNED_REPORTED: "Abschluss nur als gemeldet dokumentieren",
  CLOSED_LOST: "Vorgang ohne Abschluss schließen",
};
function clearCaseReview() {
  state.caseReviewRevision += 1;
  state.caseReview = null;
  state.caseStepDraft = null;
  $("crm-review-section").hidden = true;
  $("crm-review-summary").textContent = "";
  $("crm-review-evidence").textContent = "";
  $("crm-review-history").replaceChildren();
  $("crm-review-history-count").textContent = "";
  $("sales-step-form").hidden = true;
  $("step-to").replaceChildren();
  for (const id of ["step-pilot","step-case","step-from",
    "step-evidence","step-followup"]) $(id).value = "";
}
async function openCrmCase(pilot, caseId) {
  const generation=state.generation;
  clearCaseReview();
  const revision=state.caseReviewRevision;
  const review=await api("/api/pilot-case-review?pilot=" +
    encodeURIComponent(pilot) + "&case=" + encodeURIComponent(caseId));
  assertGeneration(generation);
  if (revision !== state.caseReviewRevision) return;
  state.caseReview={
    pilot,caseId,current:review.state,
    transitions:[...(review.available_transitions || [])],
  };
  $("crm-review-section").hidden = false;
  $("crm-review-summary").textContent = review.company_name +
    " | Eingang: " + review.reported_channel + " | Status: " + review.state +
    " | Fälligkeit: " + (review.next_followup_at || "keine");
  $("crm-review-evidence").textContent =
    "Quelle: " + review.source_ref +
    " | Quelle aktuell: " + (review.source_current ? "ja" : "NEIN") +
    " | Kontaktsperre: " + (review.suppressed ? "JA" : "nein") +
    " | Kontaktfreigabe: KEINE";
  const history=document.createDocumentFragment();
  for (const item of review.step_history || []) {
    const row=document.createElement("tr");
    td(row,item.from_state + " → " + item.to_state);
    td(row,item.evidence_ref);
    td(row,item.occurred_at);
    history.appendChild(row);
  }
  $("crm-review-history").replaceChildren(history);
  if (!(review.step_history || []).length) {
    emptyRow($("crm-review-history"),3,"Noch keine manuellen CRM-Schritte.");
  }
  $("crm-review-history-count").textContent =
    String(review.step_history_total || 0) +
    " dokumentierte Schritte" + (review.history_truncated
      ? " (nur 100 jüngste angezeigt)." : ".");
  $("journey-case").value = caseId;
  $("appointment-pilot").value = pilot;
  $("appointment-case").value = caseId;
  const authorized=["operator","admin"].includes(state.role);
  $("sales-step-form").hidden = !authorized || !review.can_record_manual_step;
  $("step-pilot").value = pilot;
  $("step-case").value = caseId;
  $("step-from").value = review.state;
  const options=document.createDocumentFragment();
  for (const action of review.available_transitions || []) {
    const option=document.createElement("option");
    option.value=action;
    option.textContent=CRM_NEXT_LABELS[action] || action;
    options.appendChild(option);
  }
  $("step-to").replaceChildren(options);
  $("step-evidence").value = "";
  $("step-followup").value = "";
  $("step-followup").required = value("step-to") === "FOLLOWUP_SCHEDULED";
}

async function crmWorklist() {
  const generation = state.generation;
  const revision = ++state.crmQueryRevision;
  clearJourney();
  clearCaseReview();
  const pilot = value("crm-pilot-id");
  if (!pilot) throw new Error("Bitte eine Pilot-ID eingeben.");
  const filter = "?pilot=" + encodeURIComponent(pilot);
  // Never retain a different pilot's cases after a failed request.
  $("crm-case-list").replaceChildren();
  $("crm-followup-list").replaceChildren();
  $("crm-appointments-list").replaceChildren();
  $("crm-case-count").textContent = "";
  $("crm-followup-count").textContent = "";
  $("crm-appointments-count").textContent = "";
  // The API checks the current OIDC subject and tenant membership on each read.
  // Neither a queued follow-up nor a reported case grants contact authority.
  const [cases, due, appointments] = await Promise.all([
    api("/api/pilot-cases" + filter),
    api("/api/pilot-followups" + filter),
    api("/api/pilot-appointments" + filter),
  ]);
  assertGeneration(generation);
  if (revision !== state.crmQueryRevision) return;
  const casesBody = $("crm-case-list");
  const dueBody = $("crm-followup-list");
  const appointmentBody = $("crm-appointments-list");
  // Publish only after every tenant-scoped request succeeds.
  const caseRows = document.createDocumentFragment();
  for (const item of cases.items || []) {
    const row = document.createElement("tr");
    for (const field of [item.case_id, item.company_name, item.state,
      item.next_followup_at || "–",
      item.suppressed ? "Gesperrt" : "Keine lokale Sperre"]) td(row, field);
    const actionCell=td(row,"");
    if (["operator","admin"].includes(state.role)) {
      const open=document.createElement("button");
      open.type="button";
      open.textContent="Bearbeiten";
      open.addEventListener("click",async () => {
        try {
          await openCrmCase(pilot,item.case_id);
          await customerJourney();
          say("");
        } catch (error) {
          if (!(error instanceof StaleContextError)) say(error.message);
        }
      });
      actionCell.replaceChildren(open);
    } else {
      actionCell.textContent="Nur Leserecht";
    }
    caseRows.appendChild(row);
  }
  const dueRows = document.createDocumentFragment();
  for (const item of due.items || []) {
    const row = document.createElement("tr");
    for (const field of [item.case_id, item.company_name,
      item.next_followup_at || "–", item.review_state]) td(row, field);
    dueRows.appendChild(row);
  }
  const appointmentRows = document.createDocumentFragment();
  for (const item of appointments.items || []) {
    const row = document.createElement("tr");
    for (const field of [item.case_id, item.slot_start_at,
      item.slot_end_at, item.state, item.calendar_ref]) td(row, field);
    appointmentRows.appendChild(row);
  }
  casesBody.replaceChildren(caseRows);
  dueBody.replaceChildren(dueRows);
  appointmentBody.replaceChildren(appointmentRows);
  if (!cases.items?.length) emptyRow(casesBody, 6, "Keine CRM-Vorgänge.");
  if (!due.items?.length) emptyRow(dueBody, 4, "Keine fälligen Wiedervorlagen.");
  if (!appointments.items?.length) emptyRow(appointmentBody, 5, "Keine Kalendertermine erfasst.");
  $("crm-case-count").textContent =
    String(cases.total ?? 0) + " Vorgänge (maximal 100 angezeigt)";
  $("crm-followup-count").textContent =
    String(due.total ?? 0) + " fällige Wiedervorlagen (maximal 100 angezeigt; kein Kontaktauftrag)";
  $("crm-appointments-count").textContent =
    String(appointments.total ?? 0) + " Kalendertermine (maximal 100 angezeigt; Buchung nur nach unabhängiger Providerbestätigung)";
}
function clearCrmWorklist() {
  state.crmQueryRevision += 1;
  clearJourney();
  clearCaseReview();
  $("journey-case").value = "";
  $("crm-pilot-id").value = "";
  $("crm-case-list").replaceChildren();
  $("crm-followup-list").replaceChildren();
  $("crm-appointments-list").replaceChildren();
  $("crm-case-count").textContent = "";
  $("crm-followup-count").textContent = "";
  $("crm-appointments-count").textContent = "";
  for (const id of ["appointment-pilot", "appointment-case",
                    "appointment-id", "appointment-calendar",
                    "appointment-start", "appointment-end"]) $(id).value = "";
}

// Destroy all tenant-derived DOM and draft form values before another
// identity is admitted. Hidden views are not a safe data isolation boundary.
function clearTenantWorkspace() {
  state.companyOffset = 0;
  state.companyTotal = 0;
  state.companyQueryRevision += 1;
  state.companyDetailRevision += 1;
  state.discoveryDraft = null;
  for (const id of ["metric-companies", "metric-work",
                    "metric-missions", "metric-pilots"]) $(id).textContent = "–";
  for (const id of ["companies-list", "discovery-list", "pilots-list"]) {
    $(id).replaceChildren();
  }
  $("companies-count").textContent = "";
  $("companies-page").textContent = "";
  $("companies-prev").disabled = true;
  $("companies-next").disabled = true;
  $("company-details").replaceChildren();
  $("company-details").hidden = true;
  clearCrmWorklist();
  clearPublicInquiries();
  state.publicInboxEnabled = false;
  $("public-inquiry-section").hidden = true;
  $("public-inquiry-review-form").hidden = true;
  for (const form of document.querySelectorAll("#workspace form")) form.reset();
  $("inquiry-review-pilot").required = true;
  // A reset() does not fire "change". Restore the dependent Discovery fields.
  const creating = value("disc-mode") === "new";
  $("disc-existing-fields").hidden = creating;
  $("disc-new-fields").hidden = !creating;
  $("disc-job").required = !creating;
  $("disc-nace").required = creating;
  for (const id of ["disc-south", "disc-west", "disc-north", "disc-east"]) {
    $(id).required = creating;
  }
  $("app-feedback").textContent = "";
  $("workspace-info").textContent = "";
}

async function openTenant(event) {
  event.preventDefault();
  const proposed = value("tenant-id");
  const attempt = ++state.generation;
  // Fence previous async reads before the first await or any new authorization.
  $("workspace").hidden = true;
  $("login").hidden = false;
  clearTenantWorkspace();
  state.tenant = "";
  state.role = "";
  try {
    if (expired()) throw new Error("Bitte erneut anmelden.");
    if (!/^[A-Za-z0-9][A-Za-z0-9_.-]{1,79}$/.test(proposed)) {
      throw new Error("Ungültige Mandantenkennung.");
    }
    state.tenant = proposed;
    const me = await api("/api/me");
    assertGeneration(attempt);
    state.role = me.role || "";
    state.publicInboxEnabled = me.public_inquiry_enabled === true;
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
    $("source-case-form").hidden = !operates;
    $("appointment-form").hidden = !operates;
    $("sales-step-form").hidden = true;
    $("public-inquiry-section").hidden = !operates || !state.publicInboxEnabled;
    $("public-inquiry-review-form").hidden = !operates || !state.publicInboxEnabled;
    $("pilot-form").hidden = !finance;
    $("payment-form").hidden = !finance;
    renderView("companies-view");
    await Promise.all([overview(), companies()]);
    assertGeneration(attempt);
    $("login").hidden = true;
    $("workspace").hidden = false;
    $("auth-status").textContent = "Mandant: " + proposed;
    say("");
  } catch (error) {
    // Another login or logout may already own the DOM. Do not undo it.
    if (attempt !== state.generation) return;
    state.generation += 1;
    state.tenant = "";
    state.role = "";
    $("workspace").hidden = true;
    $("login").hidden = false;
    $("company-details").hidden = true;
    clearTenantWorkspace();
    $("auth-status").textContent = "Mandant nicht geöffnet";
    say(error.message, true);
  }
}
function onForm(id, operation) {
  $(id).addEventListener("submit", async (event) => {
    event.preventDefault();
    const generation = state.generation;
    try {
      const message = await operation();
      assertGeneration(generation);
      const confirmed=message || "Vorgang gespeichert.";
      say(confirmed);
      // A successful mutation must not become a false failure just because
      // the subsequent, independent dashboard refresh cannot be fetched.
      try { await overview(); }
      catch (refreshError) {
        if (refreshError instanceof StaleContextError) throw refreshError;
        if (generation === state.generation) {
          say(confirmed + " Die Übersicht konnte nicht aktualisiert werden.");
        }
      }
    } catch (error) {
      if (generation === state.generation && !(error instanceof StaleContextError)) {
        say(error.message);
      }
    }
  });
}
// A lost HTTP response is not proof that a create operation failed.
// Reuse the same idempotency key for an identical draft until the server
// confirms acceptance. The server enforces immutable (tenant, request_id).
async function queueDiscovery(spec) {
  const generation = state.generation;
  const specJson = JSON.stringify(spec);
  const prior = state.discoveryDraft;
  const draft = prior && prior.generation === generation &&
                prior.specJson === specJson
    ? prior : { generation, specJson, requestId: crypto.randomUUID() };
  state.discoveryDraft = draft;
  const result = await api("/api/discovery-jobs", {
    method: "POST", body: { request_id: draft.requestId, spec },
  });
  assertGeneration(generation);
  if (state.discoveryDraft === draft) state.discoveryDraft = null;
  return result;
}
// The appointment inputs are free-text ISO timestamps, not datetime-local.
// Reject missing offsets and impossible dates before calling the durable API.
function appointmentInstant(id) {
  const raw = value(id);
  const match = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})(?::(\d{2})(?:\.(\d{1,3}))?)?(Z|[+-]\d{2}:\d{2})$/.exec(raw);
  if (!match) throw new Error("Terminzeit benötigt ISO-Datum und Zeitzone (z. B. +01:00).");
  const [, yearRaw, monthRaw, dayRaw, hourRaw, minuteRaw, secondRaw, milliRaw, zone] = match;
  const year = Number(yearRaw), month = Number(monthRaw), day = Number(dayRaw);
  const hour = Number(hourRaw), minute = Number(minuteRaw), second = Number(secondRaw || "0");
  const millis = Number((milliRaw || "0").padEnd(3, "0"));
  let offset = 0;
  if (zone !== "Z") {
    const hours = Number(zone.slice(1, 3)), minutes = Number(zone.slice(4, 6));
    if (hours > 14 || minutes > 59 || (hours === 14 && minutes !== 0)) {
      throw new Error("Ungültiger Zeitzonenversatz.");
    }
    offset = (zone[0] === "+" ? 1 : -1) * (hours * 60 + minutes);
  }
  const local = Date.UTC(year, month - 1, day, hour, minute, second, millis);
  const verify = new Date(local);
  if (!Number.isFinite(local) ||
      verify.getUTCFullYear() !== year || verify.getUTCMonth() !== month - 1 ||
      verify.getUTCDate() !== day || verify.getUTCHours() !== hour ||
      verify.getUTCMinutes() !== minute || verify.getUTCSeconds() !== second) {
    throw new Error("Terminzeit enthält ein ungültiges Kalenderdatum.");
  }
  return new Date(local - offset * 60000).toISOString();
}
function appointmentWindow() {
  const slot_start_at = appointmentInstant("appointment-start");
  const slot_end_at = appointmentInstant("appointment-end");
  const start = Date.parse(slot_start_at), end = Date.parse(slot_end_at);
  const duration = end - start, now = Date.now();
  if (duration < 15 * 60000 || duration > 480 * 60000) {
    throw new Error("Termindauer muss zwischen 15 und 480 Minuten liegen.");
  }
  if (start <= now || start > now + 365 * 24 * 60 * 60000) {
    throw new Error("Terminbeginn muss innerhalb der nächsten 365 Tage liegen.");
  }
  return { slot_start_at, slot_end_at };
}
function integers(id) {
  const n = Number(value(id));
  if (!Number.isSafeInteger(n)) throw new Error("Ungültiger Cent-Betrag.");
  return n;
}
function logout() {
  state.generation += 1;
  // Storage may be blocked by the browser; logout must still clear memory/DOM.
  try { sessionStorage.removeItem(LOGIN_TRANSACTION); } catch (_) { /* no token persisted */ }
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
  clearTenantWorkspace();
  say("Lokale Sitzung beendet; eine IdP-Sitzung muss ggf. separat beendet werden.", true);
}
async function main() {
  $("login-button").addEventListener("click", beginLogin);
  $("tenant-form").addEventListener("submit", openTenant);
  $("public-inquiry-refresh").addEventListener("click", async () => {
    try { await publicInquiries(); say(""); }
    catch (error) {
      if (!(error instanceof StaleContextError)) say(error.message);
    }
  });
  $("inquiry-review-decision").addEventListener("change", () => {
    const adopting=value("inquiry-review-decision")==="ADOPT";
    $("inquiry-review-pilot").required=adopting;
    if (!adopting) $("inquiry-review-pilot").value="";
  });
  $("step-to").addEventListener("change", () => {
    $("step-followup").required = value("step-to") === "FOLLOWUP_SCHEDULED";
    if (!$("step-followup").required) $("step-followup").value = "";
  });
  $("crm-case-filter").addEventListener("submit", async (event) => {
    event.preventDefault();
    try { await crmWorklist(); say(""); }
    catch (error) { say(error.message); }
  });
  $("journey-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    try { await customerJourney(); say(""); }
    catch (error) {
      if (!(error instanceof StaleContextError)) say(error.message);
    }
  });
  $("logout-button").addEventListener("click", logout);
  document.querySelectorAll('nav[aria-label="Produktbereiche"] button')
    .forEach((button) => button.addEventListener("click", async () => {
      renderView(button.dataset.view);
      try {
        if (button.dataset.view === "companies-view") await companies();
        if (button.dataset.view === "discovery-view") await discovery();
        if (button.dataset.view === "pilots-view") await pilots();
        if (button.dataset.view === "sales-view" && state.publicInboxEnabled) {
          await publicInquiries();
        }
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
      const search_terms = value("disc-terms").split(/\r?\n/)
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
    const accepted = await queueDiscovery(spec);
    try {
      await discovery();
    } catch (error) {
      if (error instanceof StaleContextError) throw error;
      // An accepted job must never be reported as a failed submission
      // solely because the subsequent list refresh could not be fetched.
      return "Discovery-Auftrag " + accepted.request_id +
        " angenommen. Die Übersicht konnte nicht aktualisiert werden; " +
        "Auftrag nicht erneut absenden. " + error.message;
    }
    return "Discovery-Auftrag " + accepted.request_id +
      " in Queue aufgenommen (Host-Freigabe für externe Ausführung bleibt erforderlich).";
  });
  onForm("appointment-form", async () => {
    const result = await api("/api/pilot-appointment-prepare", {
      method: "POST", body: {
        pilot_id: value("appointment-pilot"),
        case_id: value("appointment-case"),
        booking_id: value("appointment-id"),
        calendar_ref: value("appointment-calendar"),
        ...appointmentWindow(),
      },
    });
    if (value("crm-pilot-id") === value("appointment-pilot")) await crmWorklist();
    return "Lokale Terminabsicht: " + result.state +
      " (kein Kalendertermin erstellt, keine Einladung versandt).";
  });
  onForm("public-inquiry-review-form", async () => {
    const generation=state.generation;
    if (!state.publicInboxEnabled) throw new Error("Pilotanfragen sind nicht freigeschaltet.");
    const decision=value("inquiry-review-decision");
    const pilotId=decision==="ADOPT" ? value("inquiry-review-pilot") : "";
    if (decision==="ADOPT" && !pilotId) throw new Error("Pilot-ID erforderlich.");
    const result=await api("/api/public-pilot-inquiry-review", {
      method:"POST", body:{
        inquiry_id:value("inquiry-review-id"), decision, pilot_id:pilotId,
      },
    });
    assertGeneration(generation);
    let refreshFailed=false;
    try { await publicInquiries(); }
    catch (error) {
      if (error instanceof StaleContextError) throw error;
      refreshFailed=true;
    }
    const suffix=refreshFailed
      ? " Die Liste konnte nicht aktualisiert werden; Speicherung ist bestätigt."
      : "";
    if (result.state==="ADOPTED") {
      $("crm-pilot-id").value=result.pilot_id;
      let crmRefreshFailed=false;
      try {
        await crmWorklist();
        await openCrmCase(result.pilot_id,result.case_id);
      } catch (error) {
        if (error instanceof StaleContextError) throw error;
        crmRefreshFailed=true;
      }
      return "Anfrage als gemeldeter CRM-Vorgang übernommen: " +
        result.case_id + ". Keine automatische Kontaktfreigabe." + suffix +
        (crmRefreshFailed ? " Die Arbeitsakte konnte nicht geöffnet werden." : "");
    }
    return "Pilotanfrage abgelehnt. Kein CRM-Vorgang angelegt." + suffix;
  });
  onForm("source-case-form", async () => {
    const result = await api("/api/pilot-discovery", {
      method: "POST", body: {
        pilot_id: value("source-pilot"), case_id: value("source-case"),
        opportunity_id: value("source-opportunity"),
        evidence_ref: value("source-evidence"),
      },
    });
    if (value("crm-pilot-id") === value("source-pilot")) await crmWorklist();
    return "Discovery-Prospect übernommen: " + result.state +
      " (keine eingegangene Anfrage und keine Kontaktfreigabe).";
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
    const generation=state.generation;
    const selected=state.caseReview;
    if (!selected || !["operator","admin"].includes(state.role) ||
        selected.pilot!==value("step-pilot") ||
        selected.caseId!==value("step-case") ||
        selected.current!==value("step-from") ||
        !selected.transitions.includes(value("step-to"))) {
      throw new Error("Vorgang geändert. Bitte den aktuellen CRM-Vorgang neu öffnen.");
    }
    const next=value("step-to");
    const followup=next==="FOLLOWUP_SCHEDULED"
      ? value("step-followup") : "";
    if (next==="FOLLOWUP_SCHEDULED" && !followup) {
      throw new Error("Eine Wiedervorlage benötigt eine Fälligkeit mit Zeitzone.");
    }
    const spec={
      pilot_id:selected.pilot, case_id:selected.caseId,
      expected_state:selected.current, to_state:next,
      evidence_ref:value("step-evidence"), followup_at:followup,
    };
    // Preserve one step ID for identical retries after a lost HTTP reply.
    // New evidence/transition is a new draft, never a silent retry.
    const serialized=JSON.stringify(spec);
    const old=state.caseStepDraft;
    const draft=old && old.serialized===serialized &&
      old.generation===state.generation ? old : {
        generation:state.generation,serialized,
        step_id:"step-"+crypto.randomUUID(),
      };
    state.caseStepDraft=draft;
    const result=await api("/api/pilot-step", {
      method:"POST",body:{...spec,step_id:draft.step_id},
    });
    assertGeneration(generation);
    state.caseStepDraft=null;
    let refreshFailed=false;
    try {
      $("crm-pilot-id").value=selected.pilot;
      await crmWorklist();
      await openCrmCase(selected.pilot,selected.caseId);
      await customerJourney();
    } catch (error) {
      if (error instanceof StaleContextError) throw error;
      refreshFailed=true;
    }
    return "CRM-Schritt dokumentiert: "+result.state+
      " (gemeldet, keine unabhängige Bestätigung oder Kontaktfreigabe)." +
      (refreshFailed ? " Die Anzeige konnte nicht vollständig aktualisiert werden." : "");
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
