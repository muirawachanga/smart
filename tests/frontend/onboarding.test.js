import assert from "node:assert/strict";
import test from "node:test";

class Element {
  constructor() {
    this.children = [];
    this.listeners = {};
    this.value = "";
    this.disabled = false;
    this._text = "";
  }
  get textContent() { return this._text + this.children.map((child) => child.textContent).join(""); }
  set textContent(value) { this._text = String(value); this.children = []; }
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren(...nodes) { this._text = ""; this.children = nodes; }
  addEventListener(name, callback) { this.listeners[name] = callback; }
  querySelector() { return this.submit; }
  reportValidity() { return true; }
}

function install(t, writable = true) {
  const nodes = new Map([
    "setup-business-form", "setup-business-fields", "setup-status", "setup-error",
    "setup-refresh", "setup-checks", "setup-optional", "setup-manual",
  ].map((id) => [`#${id}`, new Element()]));
  const form = nodes.get("#setup-business-form");
  form.submit = writable ? new Element() : null;
  const inputs = new Map(["name", "email", "phone", "address"].map((key) => [key, new Element()]));
  form.elements = { namedItem: (key) => inputs.get(key) };
  for (const [name, value] of Object.entries({
    document: { querySelector: (selector) => nodes.get(selector), createElement: () => new Element() },
    window: { frappe: { csrf_token: "csrf" } },
  })) {
    const old = Object.getOwnPropertyDescriptor(globalThis, name);
    Object.defineProperty(globalThis, name, { value, writable: true, configurable: true });
    t.after(() => old ? Object.defineProperty(globalThis, name, old) : delete globalThis[name]);
  }
  return { nodes, form, inputs };
}

const tick = () => new Promise((resolve) => setTimeout(resolve, 0));
const response = (message) => ({ ok: true, json: async () => ({ message }) });
const report = {
  business: { name: "<Shop>", email: "help@example.test", phone: "", address: "" },
  blocking_count: 1, notice: "Configuration checks only; not production certification.",
  checks: [{ title: "Catalog", status: "blocked", detail: "Create products.", link: "/app/product" }],
  optional: [{ title: "Gemini", status: "disabled or unconfigured" }],
  manual_checks: [{ title: "Restore backup", detail: "Test a restore.", status: "not_verified" }],
};

test("setup renders honest checks and saves only public identity fields", async (t) => {
  const { nodes, form, inputs } = install(t);
  const calls = [];
  t.mock.method(globalThis, "fetch", async (url, options) => {
    calls.push({ url: String(url), options });
    return response(url.includes("save_business") ? { business: report.business } : report);
  });
  await import(`../../intelligent_ordering/public/js/onboarding.js?save=${Date.now()}`);
  await tick();
  assert.equal(inputs.get("name").value, "<Shop>");
  assert.match(nodes.get("#setup-status").textContent, /1 configuration blockers/);
  assert.match(nodes.get("#setup-manual").textContent, /not verified/);
  assert.equal(nodes.get("#setup-business-fields").disabled, false);
  inputs.get("name").value = "Updated Shop";
  await form.listeners.submit({ preventDefault() {} });
  const save = calls.find((call) => call.url.includes("save_business"));
  assert.equal(save.options.method, "POST");
  assert.equal(save.options.headers["X-Frappe-CSRF-Token"], "csrf");
  assert.deepEqual([...save.options.body.keys()], ["name", "email", "phone", "address"]);
  assert.equal(save.options.body.get("name"), "Updated Shop");
  assert.match(nodes.get("#setup-status").textContent, /Business details saved/);
});

test("setup is read-only for business admins and failed refresh removes stale results", async (t) => {
  const { nodes, form } = install(t, false);
  let failing = false;
  t.mock.method(globalThis, "fetch", async () => {
    if (failing) throw new Error("offline");
    return response(report);
  });
  await import(`../../intelligent_ordering/public/js/onboarding.js?read=${Date.now()}`);
  await tick();
  assert.equal(nodes.get("#setup-business-fields").disabled, true);
  await form.listeners.submit({ preventDefault() {} });
  failing = true;
  await nodes.get("#setup-refresh").listeners.click();
  assert.equal(nodes.get("#setup-checks").children.length, 0);
  assert.equal(nodes.get("#setup-manual").children.length, 0);
  assert.match(nodes.get("#setup-status").textContent, /unknown/);
  assert.match(nodes.get("#setup-error").textContent, /Could not connect/);
});

test("a failed save never displays success and allows correction", async (t) => {
  const { nodes, form } = install(t);
  t.mock.method(globalThis, "fetch", async (url) => {
    if (url.includes("save_business")) return { ok: false, status: 403, json: async () => ({}) };
    return response(report);
  });
  await import(`../../intelligent_ordering/public/js/onboarding.js?failure=${Date.now()}`);
  await tick();
  await form.listeners.submit({ preventDefault() {} });
  assert.match(nodes.get("#setup-status").textContent, /not confirmed saved/);
  assert.match(nodes.get("#setup-error").textContent, /permission/);
  assert.equal(nodes.get("#setup-business-fields").disabled, false);
});

test("refresh recovers the actual business details after a failed initial load", async (t) => {
  const { nodes, inputs } = install(t);
  let failing = true;
  t.mock.method(globalThis, "fetch", async () => {
    if (failing) throw new Error("offline");
    return response(report);
  });
  await import(`../../intelligent_ordering/public/js/onboarding.js?recover=${Date.now()}`);
  await tick();
  assert.equal(nodes.get("#setup-business-fields").disabled, true);
  failing = false;
  await nodes.get("#setup-refresh").listeners.click();
  assert.equal(inputs.get("name").value, "<Shop>");
  assert.equal(nodes.get("#setup-business-fields").disabled, false);
});

test("a successful save with failed checks is not reported as a failed save", async (t) => {
  const { nodes, form } = install(t);
  let saved = false;
  t.mock.method(globalThis, "fetch", async (url) => {
    if (url.includes("save_business")) {
      saved = true;
      return response({ business: report.business });
    }
    if (saved) throw new Error("offline");
    return response(report);
  });
  await import(`../../intelligent_ordering/public/js/onboarding.js?refresh-failure=${Date.now()}`);
  await tick();
  await form.listeners.submit({ preventDefault() {} });
  assert.match(nodes.get("#setup-status").textContent, /Business details saved.*unknown/);
  assert.match(nodes.get("#setup-error").textContent, /Could not connect/);
  assert.equal(nodes.get("#setup-business-fields").disabled, true);
});
