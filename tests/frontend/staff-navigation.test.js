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
  getAttribute(name) { return this[name] ?? null; }
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
    ["Administrator", "/dashboard/admin", [
      "#staff-orders-link", "#payments-link", "#deliveries-link", "#admin-dashboard-link",
      "#inventory-dashboard-link", "#support-dashboard-link",
    ]],
    ["System Manager", "/dashboard/admin", [
      "#staff-orders-link", "#payments-link", "#deliveries-link", "#admin-dashboard-link",
      "#inventory-dashboard-link", "#support-dashboard-link",
    ]],
    ["Business Admin", "/dashboard/admin", [
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
    ["Delivery Staff", "/dashboard/rider", ["#deliveries-link"]],
    ["Customer", "/account", []],
  ]) {
    const nodes = new Map();
    const document = {
      querySelector(selector) {
        if (["[data-route-reference]", "#smarto-sidebar"].includes(selector)) return null;
        if (!nodes.has(selector)) {
          const link = new Element();
          const paths = {
            "#smarto-workspace-link": "/account",
            "#smarto-staff-entry-link": "/account",
            "#staff-orders-link": "/dashboard/orders",
            "#payments-link": "/store#payment-dashboard",
            "#deliveries-link": "/dashboard/delivery",
            "#staff-rider-link": "/dashboard/rider",
            "#admin-dashboard-link": "/store#admin-dashboard",
            "#inventory-dashboard-link": "/dashboard/inventory",
            "#support-dashboard-link": "/dashboard/support",
            "#staff-delivery-areas-link": "/dashboard/delivery-areas",
            "#staff-products-link": "/dashboard/products",
            "#staff-accounts-link": "/dashboard/accounts",
          };
          if (paths[selector]) link.href = paths[selector];
          nodes.set(selector, link);
        }
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
      json: async () => ({ message: {
        user: role === "Administrator" ? "Administrator" : "test@example.test",
        roles: role === "Administrator" ? [] : [role],
      } }),
    }));
    await import(`../../intelligent_ordering/public/js/site.js?role=${encodeURIComponent(role)}`);
    await new Promise((resolve) => setTimeout(resolve, 0));
    assert.equal(nodes.get("#smarto-workspace-link").href, destination);
    assert.equal(nodes.get("#smarto-staff-entry-link").href, destination);
    assert.equal(nodes.get("#smarto-workspace-link").hidden,
      ["/account", "/dashboard/orders", "/dashboard/inventory", "/dashboard/delivery", "/dashboard/rider", "/dashboard/support"]
        .includes(destination));
    for (const selector of [
      "#staff-orders-link", "#payments-link", "#deliveries-link",
      "#admin-dashboard-link", "#inventory-dashboard-link", "#support-dashboard-link",
    ]) {
      assert.equal(nodes.get(selector).hidden, !visible.includes(selector), `${role}: ${selector}`);
    }
    const admin = ["Administrator", "System Manager"].includes(role);
    for (const selector of [
      "#staff-accounts-link", "#staff-users-link", "#staff-roles-link",
      "#staff-permissions-link", "#staff-settings-link",
    ]) assert.equal(nodes.get(selector).hidden, !admin, `${role}: ${selector}`);
    for (const selector of ["#staff-setup-link", "#staff-reports-link"]) {
      assert.equal(nodes.get(selector).hidden, !(admin || role === "Business Admin"), `${role}: ${selector}`);
    }
    assert.equal(nodes.get("#staff-delivery-areas-link").hidden,
      !["Administrator", "System Manager", "Business Admin", "Store Manager", "Order Manager", "Delivery Manager"]
        .includes(role), `${role}: delivery areas`);
    assert.equal(nodes.get("#staff-products-link").hidden,
      !["Administrator", "System Manager", "Business Admin", "Store Manager", "Order Manager", "Inventory Manager"]
        .includes(role), `${role}: products`);
    assert.equal(nodes.get("#staff-rider-link").hidden, role !== "Delivery Staff", `${role}: rider workspace`);
    assert.equal(nodes.get("#staff-audit-link").hidden,
      !["Administrator", "System Manager", "Business Admin"].includes(role), `${role}: Desk audit logs`);
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
      if (["[data-route-reference]", "#smarto-sidebar"].includes(selector)) return null;
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

test("logout failures are visibly reported with an operation and HTTP status", async (t) => {
  const original = Object.fromEntries(["document", "window"].map((key) =>
    [key, Object.getOwnPropertyDescriptor(globalThis, key)]));
  t.after(() => {
    for (const [key, descriptor] of Object.entries(original)) {
      if (descriptor) Object.defineProperty(globalThis, key, descriptor);
      else delete globalThis[key];
    }
  });
  const nodes = new Map();
  const document = {
    querySelector(selector) {
      if (["[data-route-reference]", "#smarto-sidebar"].includes(selector)) return null;
      if (!nodes.has(selector)) nodes.set(selector, new Element());
      return nodes.get(selector);
    },
    querySelectorAll: () => [],
    addEventListener() {},
  };
  Object.defineProperty(globalThis, "document", { value: document, configurable: true });
  Object.defineProperty(globalThis, "window", {
    value: { location: { pathname: "/store", hash: "#payment-dashboard" }, frappe: {} }, configurable: true,
  });
  t.mock.method(globalThis, "fetch", async (url) => url.includes("current_user")
    ? { ok: true, json: async () => ({ message: { user: "test@example.test", roles: ["Customer"] } }) }
    : { ok: false, status: 500 });
  await import(`../../intelligent_ordering/public/js/site.js?logout-failure=${Date.now()}`);
  const link = nodes.get("#smarto-logout-link");
  link.href = "/api/method/logout";
  await link.listeners.click({ preventDefault() {}, currentTarget: link });
  assert.equal(nodes.get("#smarto-session-error").hidden, false);
  assert.match(nodes.get("#smarto-session-error").textContent, /authentication\.logout, HTTP 500/);
  assert.equal(link["aria-disabled"], undefined);
});
