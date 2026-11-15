import assert from "node:assert/strict";
import test from "node:test";

class Element {
  constructor() {
    this.hidden = true;
    this.href = "";
    this.listeners = {};
    this.dataset = {};
    this.classList = { toggle() {} };
  }
  addEventListener(name, handler) { this.listeners[name] = handler; }
  setAttribute(name, value) { this[name] = value; }
  removeAttribute(name) { delete this[name]; }
}

test("each staff role sees only authorized navigation and its own workspace", async (t) => {
  const original = Object.fromEntries(["document", "window"].map((key) =>
    [key, Object.getOwnPropertyDescriptor(globalThis, key)]));
  t.after(() => {
    for (const [key, descriptor] of Object.entries(original)) {
      if (descriptor) Object.defineProperty(globalThis, key, descriptor);
      else delete globalThis[key];
    }
  });

  for (const [role, destination, visible] of [
    ["System Manager", "/dashboard/admin", [
      "#staff-orders-link", "#payments-link", "#deliveries-link", "#admin-dashboard-link",
      "#inventory-dashboard-link", "#support-dashboard-link",
    ]],
    ["Store Manager", "/dashboard/owner", [
      "#staff-orders-link", "#payments-link", "#deliveries-link", "#admin-dashboard-link",
      "#support-dashboard-link",
    ]],
    ["Order Manager", "/dashboard/orders", [
      "#staff-orders-link", "#payments-link", "#deliveries-link", "#admin-dashboard-link",
    ]],
    ["Customer Support", "/dashboard/support", ["#support-dashboard-link"]],
    ["Inventory Manager", "/dashboard/inventory", ["#inventory-dashboard-link", "#admin-dashboard-link"]],
    ["Delivery Manager", "/dashboard/delivery", ["#deliveries-link", "#admin-dashboard-link"]],
    ["Finance Manager", "/dashboard/sales", ["#payments-link", "#admin-dashboard-link"]],
    ["Delivery Staff", "/dashboard/delivery", ["#deliveries-link"]],
  ]) {
    const nodes = new Map();
    const document = {
      querySelector(selector) {
        if (selector === "[data-route-reference]") return null;
        if (!nodes.has(selector)) nodes.set(selector, new Element());
        return nodes.get(selector);
      },
      querySelectorAll: () => [],
      addEventListener() {},
    };
    Object.defineProperty(globalThis, "document", { value: document, configurable: true });
    Object.defineProperty(globalThis, "window", {
      value: { location: { pathname: "/store" } }, configurable: true,
    });
    t.mock.method(globalThis, "fetch", async () => ({
      ok: true,
      json: async () => ({ message: { user: "test@example.test", roles: [role] } }),
    }));
    await import(`../../intelligent_ordering/public/js/site.js?role=${encodeURIComponent(role)}`);
    await new Promise((resolve) => setTimeout(resolve, 0));
    assert.equal(nodes.get("#smarto-workspace-link").href, destination);
    for (const selector of [
      "#staff-orders-link", "#payments-link", "#deliveries-link",
      "#admin-dashboard-link", "#inventory-dashboard-link", "#support-dashboard-link",
    ]) {
      assert.equal(nodes.get(selector).hidden, !visible.includes(selector), `${role}: ${selector}`);
    }
    t.mock.restoreAll();
  }
});

test("customer account navigation marks only the current account section", async (t) => {
  const original = Object.fromEntries(["document", "window"].map((key) =>
    [key, Object.getOwnPropertyDescriptor(globalThis, key)]));
  t.after(() => {
    for (const [key, descriptor] of Object.entries(original)) {
      if (descriptor) Object.defineProperty(globalThis, key, descriptor);
      else delete globalThis[key];
    }
  });
  const links = ["/account", "/account/profile", "/account/addresses", "/account/payments", "/account/notifications"]
    .map((path) => {
      const link = new Element();
      link.dataset.accountPath = path;
      return link;
    });
  const nodes = new Map();
  const document = {
    querySelector(selector) {
      if (selector === "[data-route-reference]") return null;
      if (!nodes.has(selector)) nodes.set(selector, new Element());
      return nodes.get(selector);
    },
    querySelectorAll(selector) {
      return selector === "[data-account-path]" ? links : [];
    },
    addEventListener() {},
  };
  Object.defineProperty(globalThis, "document", { value: document, configurable: true });
  Object.defineProperty(globalThis, "window", {
    value: { location: { pathname: "/account/payments", search: "" } }, configurable: true,
  });
  t.mock.method(globalThis, "fetch", async () => ({
    ok: true, json: async () => ({ message: { user: "customer@example.test", roles: ["Customer"] } }),
  }));
  await import(`../../intelligent_ordering/public/js/site.js?account-navigation=${Date.now()}`);
  await new Promise((resolve) => setTimeout(resolve, 0));
  assert.equal(links.find((link) => link.dataset.accountPath === "/account/payments")["aria-current"], "page");
  assert.ok(links.filter((link) => link.dataset.accountPath !== "/account/payments")
    .every((link) => !("aria-current" in link)));
});
