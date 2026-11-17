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
  replaceChildren(...nodes) { this.children = nodes; this._text = ""; }
  addEventListener(name, callback) { this.listeners[name] = callback; }
  setAttribute(name, value) { this[name] = value; }
  reportValidity() { return true; }
}

function install(t) {
  const nodes = new Map([
    "create", "role", "list", "status", "error", "create-feedback", "search", "previous", "next", "page",
  ].map((id) => [`#accounts-${id}`, new Element()]));
  const submit = new Element();
  const create = nodes.get("#accounts-create");
  create.querySelector = () => submit;
  create.reset = () => {};
  nodes.get("#accounts-search").elements = { search: new Element() };
  const globals = {
    document: { querySelector: (selector) => nodes.get(selector), createElement: () => new Element() },
    window: { frappe: { csrf_token: "csrf" }, confirm: () => true },
    Option: class extends Element {
      constructor(label, value) { super(); this.textContent = label; this.value = value; }
    },
    FormData: class {
      *[Symbol.iterator]() {
        yield ["email", "person@example.test"];
        yield ["full_name", "Test Person"];
        yield ["phone", "+254712345678"];
        yield ["role", "Inventory Manager"];
      }
    },
  };
  for (const [name, value] of Object.entries(globals)) {
    const old = Object.getOwnPropertyDescriptor(globalThis, name);
    Object.defineProperty(globalThis, name, { value, writable: true, configurable: true });
    t.after(() => old ? Object.defineProperty(globalThis, name, old) : delete globalThis[name]);
  }
  return { nodes, submit, create };
}
const response = (message) => ({ ok: true, json: async () => ({ message }) });
const tick = () => new Promise((resolve) => setTimeout(resolve, 0));
const listing = {
  roles: ["Customer", "Order Manager", "Inventory Manager", "Delivery Staff"],
  accounts: [
    { name: "person@example.test", email: "person@example.test", full_name: "Test Person", enabled: 1,
      roles: ["Inventory Manager"], modified: "2026-11-17 11:00:00", can_manage: true },
    { name: "admin@example.test", email: "admin@example.test", full_name: "Protected Admin", enabled: 1,
      roles: ["System Manager"], can_manage: false },
  ], has_more: false,
};

test("admin creates an account without entering or displaying a password", async (t) => {
  const { nodes, create } = install(t);
  let created;
  t.mock.method(globalThis, "fetch", async (url, options) => {
    if (url.includes("create_account")) {
      created = options;
      return response({ message: "Account created and setup email queued." });
    }
    return response(listing);
  });
  await import(`../../intelligent_ordering/public/js/accounts-management.js?create=${Date.now()}`);
  await tick();
  await create.listeners.submit({ preventDefault() {} });
  assert.equal(created.method, "POST");
  assert.equal(created.headers["X-Frappe-CSRF-Token"], "csrf");
  assert.equal(created.body.get("role"), "Inventory Manager");
  assert.equal(created.body.has("password"), false);
  assert.match(nodes.get("#accounts-create-feedback").textContent, /queued/);
  const protectedCard = nodes.get("#accounts-list").children[1];
  assert.match(protectedCard.textContent, /Protected or advanced/);
  assert.equal(protectedCard.children.some((child) => child.type === "submit"), false);
});

test("access updates send only intended role, enabled state and loaded version", async (t) => {
  const { nodes } = install(t);
  let changed;
  t.mock.method(globalThis, "fetch", async (url, options) => {
    if (url.includes("update_access")) {
      changed = options.body;
      return response({ message: "Access updated. Existing sessions were revoked." });
    }
    return response(listing);
  });
  await import(`../../intelligent_ordering/public/js/accounts-management.js?update=${Date.now()}`);
  await tick();
  const form = nodes.get("#accounts-list").children[0].children[2];
  form.children[0].children[0].value = "Order Manager";
  form.children[1].children[0].value = "0";
  await form.listeners.submit({ preventDefault() {} });
  assert.equal(changed.get("role"), "Order Manager");
  assert.equal(changed.get("enabled"), "0");
  assert.equal(changed.get("modified"), listing.accounts[0].modified);
  assert.match(nodes.get("#accounts-status").textContent, /sessions were revoked/);
});

test("mail failures and denied account administration never display success", async (t) => {
  const { nodes, submit, create } = install(t);
  let denied = false;
  t.mock.method(globalThis, "fetch", async (url) => {
    if (denied || url.includes("create_account")) return {
      ok: false, status: 403, json: async () => ({}),
    };
    return response(listing);
  });
  await import(`../../intelligent_ordering/public/js/accounts-management.js?fail=${Date.now()}`);
  await tick();
  await create.listeners.submit({ preventDefault() {} });
  assert.match(nodes.get("#accounts-create-feedback").textContent, /Creation not confirmed/);
  denied = true;
  nodes.get("#accounts-search").listeners.submit({ preventDefault() {} });
  await tick();
  assert.equal(nodes.get("#accounts-list").children.length, 0);
  assert.equal(submit.disabled, true);
  assert.match(nodes.get("#accounts-error").textContent, /permission/);
});
