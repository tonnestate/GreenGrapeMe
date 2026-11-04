"use strict";

// Dependency-free runtime regression for tenant DOM confidentiality.
// The real production script is evaluated; only browser primitives and
// HTTP responses are simulated. No IdP, messages or external effects.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { webcrypto } = require("node:crypto");

class Element {
  constructor(name = "") {
    this.name = name;
    this.value = "";
    this.textContent = "";
    this.hidden = false;
    this.disabled = false;
    this.required = false;
    this.children = [];
    this.listeners = {};
    this.style = {};
    this.dataset = {};
  }
  replaceChildren(...values) { this.children = values; }
  appendChild(node) { this.children.push(node); }
  append(...values) { this.children.push(...values); }
  addEventListener(type, callback) { this.listeners[type] = callback; }
  setAttribute() {}
  removeAttribute() {}
  focus() {}
  reset() { this.value = ""; }
}

const elements = new Map();
function element(id) {
  if (!elements.has(id)) elements.set(id, new Element(id));
  return elements.get(id);
}
const mockForm = {
  reset() {
    element("disc-mode").value = "existing";
    element("disc-nace").value = "";
    element("disc-south").value = "";
  },
};
const document = {
  getElementById: element,
  createElement: (type) => new Element(type),
  createDocumentFragment: () => new Element("fragment"),
  querySelectorAll: (query) => query === "#workspace form" ? [mockForm] : [],
};
const sessionStorage = {
  removed: [],
  blocked: false,
  removeItem(key) {
    if (this.blocked) throw new Error("Browser storage refused access");
    this.removed.push(key);
  },
  getItem() { return null; },
};
const response = (body, status = 200) => ({
  ok: status >= 200 && status < 300,
  status,
  json: async () => body,
});
let held = null;
const fetch = (url, options) => {
  const tenant = options.headers["X-Green-Grape-Tenant"];
  if (held && tenant === held.tenant && url.startsWith(held.path)) {
    return new Promise((resolve) => {
      held.release = (body, status) => resolve(response(body, status));
      held.started();
    });
  }
  if (url === "/api/me") return Promise.resolve(response({ role: "admin", tenant }));
  if (url === "/api/overview") {
    return Promise.resolve(response({ opportunities: 1, work_items: 1, missions: 1 }));
  }
  if (url === "/api/pilots") return Promise.resolve(response({ items: [] }));
  if (url.startsWith("/api/companies?")) {
    return Promise.resolve(response({
      total: 1,
      items: [{
        company_name: tenant + " company",
        opportunity_id: "company-id", offer_id: "offer", qualification: "LEAD",
        suppressed: false,
      }],
    }));
  }
  if (url.startsWith("/api/company?")) {
    return Promise.resolve(response({ company_name: tenant + " company" }));
  }
  throw new Error("Unexpected HTTP route " + url);
};
function holdRequest(tenant, urlPrefix) {
  let started;
  const ready = new Promise((resolve) => { started = resolve; });
  held = { tenant, path: urlPrefix, started, release: null };
  const ref = held;
  return {
    ready,
    release(body, status = 200) {
      assert.equal(typeof ref.release, "function", "held request never started");
      ref.release(body, status);
      if (held === ref) held = null;
    },
  };
}

const scriptPath = path.resolve(__dirname, "../src/greengrapeme/web/saas.js");
const source = fs.readFileSync(scriptPath, "utf8");
assert.match(source, /\nmain\(\);\s*$/, "expected SaaS script entrypoint");
const sourceWithoutMain = source.replace(
  /\nmain\(\);\s*$/, "\nglobalThis.__gg = { state, api, openTenant, logout, companies };\n"
);
const runtime = {
  document, fetch, sessionStorage, URLSearchParams, URL, crypto: webcrypto,
  TextEncoder, btoa, window: { location: { origin: "https://app.example" } },
};
vm.runInNewContext(sourceWithoutMain, runtime, { filename: scriptPath });
const { state, api, openTenant, logout, companies } = runtime.__gg;

async function admit(tenant) {
  element("tenant-id").value = tenant;
  await openTenant({ preventDefault() {} });
  assert.equal(state.tenant, tenant);
  assert.equal(element("workspace").hidden, false);
}

async function run() {
  state.token = "fake-token-for-isolation-test";
  state.expiresAt = Date.now() + 10 * 60_000;
  await admit("tenant-a");

  // Confidential details from A must disappear before the first B await.
  element("company-details").children = [new Element("A-secret")];
  element("company-details").hidden = false;
  const oldA = holdRequest("tenant-a", "/api/company?id=late");
  const pendingA = api("/api/company?id=late");
  await oldA.ready;
  element("tenant-id").value = "tenant-b";
  const toB = openTenant({ preventDefault() {} });
  assert.equal(element("company-details").hidden, true);
  assert.equal(element("company-details").children.length, 0);
  oldA.release({ company_name: "Sensitive A" });
  const staleA = await pendingA.then(() => null, (error) => error);
  assert.match(String(staleA), /Veraltete Sitzung/);
  await toB;
  assert.equal(state.tenant, "tenant-b");

  // An old A/B request's HTTP 401 must not log out the newer session.
  const stale401 = holdRequest("tenant-b", "/api/company?id=old-401");
  const pending401 = api("/api/company?id=old-401");
  await stale401.ready;
  const toC = openTenant({ preventDefault() {} });
  stale401.release({ error: "unauthorized" }, 401);
  const oldError = await pending401.then(() => null, (error) => error);
  assert.match(String(oldError), /Veraltete Sitzung/);
  await toC;
  assert.equal(state.tenant, "tenant-b");
  assert.notEqual(state.token, null);

  // Multiple simultaneous admissions cannot let the older failure wipe
  // the newer successful tenant session.
  const heldAdmission = holdRequest("tenant-slow", "/api/me");
  element("tenant-id").value = "tenant-slow";
  const slow = openTenant({ preventDefault() {} });
  await heldAdmission.ready;
  element("tenant-id").value = "tenant-fast";
  const fast = openTenant({ preventDefault() {} });
  heldAdmission.release({ role: "admin", tenant: "tenant-slow" });
  await Promise.all([slow, fast]);
  assert.equal(state.tenant, "tenant-fast");

  // Out-of-order searches cannot overwrite the latest result within a tenant.
  const oldSearch = holdRequest("tenant-fast", "/api/companies?q=old");
  element("company-query").value = "old";
  const first = companies();
  await oldSearch.ready;
  element("company-query").value = "new";
  await companies();
  oldSearch.release({
    total: 1, items: [{
      company_name: "STALE COMPANY", opportunity_id: "old",
      offer_id: "offer", qualification: "LEAD", suppressed: false,
    }],
  });
  await first;
  assert.equal(element("companies-list").children[0].children[0].textContent,
    "tenant-fast company");

  // Details opened before a new company query cannot reappear afterwards.
  const button = element("companies-list").children[0].children[4].children[0];
  const oldDetail = holdRequest("tenant-fast", "/api/company?id=company-id");
  const pendingDetail = button.listeners.click();
  await oldDetail.ready;
  element("company-query").value = "newer";
  await companies();
  oldDetail.release({ company_name: "STALE DETAILS" });
  await pendingDetail;
  assert.equal(element("company-details").hidden, true);
  assert.equal(element("company-details").children.length, 0);

  // Reset must restore fields whose visibility/requiredness is controlled
  // by change handlers (form.reset never dispatches change).
  element("disc-mode").value = "new";
  element("disc-new-fields").hidden = false;
  element("disc-existing-fields").hidden = true;
  await admit("tenant-next");
  assert.equal(element("disc-mode").value, "existing");
  assert.equal(element("disc-new-fields").hidden, true);
  assert.equal(element("disc-existing-fields").hidden, false);
  assert.equal(element("disc-job").required, true);

  // A live 401 destroys the active session and its confidential DOM.
  element("company-details").children = [new Element("last-secret")];
  const active401 = holdRequest("tenant-next", "/api/company?id=active-401");
  const failed = api("/api/company?id=active-401");
  await active401.ready;
  active401.release({ error: "unauthorized" }, 401);
  const authError = await failed.then(() => null, (error) => error);
  assert.match(String(authError), /Sitzung abgelaufen/);
  assert.equal(state.token, null);
  assert.equal(state.tenant, "");
  assert.equal(element("workspace").hidden, true);
  assert.equal(element("company-details").children.length, 0);
  assert.ok(sessionStorage.removed.includes("gg-oidc-pkce-transaction"));

  // Browser storage failures must not interrupt the security-critical purge.
  state.token = "stale-token";
  state.tenant = "tenant-next";
  element("company-details").children = [new Element("private-detail")];
  sessionStorage.blocked = true;
  logout();
  assert.equal(state.token, null);
  assert.equal(state.tenant, "");
  assert.equal(element("company-details").hidden, true);
  assert.equal(element("company-details").children.length, 0);
  console.log("PASS GreenGrapeMe SaaS client tenant-isolation regression");
}

run().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
