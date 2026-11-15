import assert from "node:assert/strict";
import test from "node:test";

class Element {
  constructor() {
    this.children = [];
    this.dataset = {};
    this.listeners = {};
    this.disabled = false;
    this._text = "";
  }
  get textContent() {
    return this._text + this.children.map((child) => child.textContent).join("");
  }
  set textContent(value) {
    this._text = String(value ?? "");
    this.children = [];
  }
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren(...nodes) { this.children = [...nodes]; }
  addEventListener(name, callback) { this.listeners[name] = callback; }
  setAttribute(name, value) { this[name] = value; }
}

function install(t, role) {
  const selectors = [
    "role-dashboard-status", "role-dashboard-error", "role-dashboard-refresh",
    "role-dashboard-metrics", "role-dashboard-daily", "role-dashboard-monthly",
    "role-dashboard-products",
  ];
  const nodes = new Map(selectors.map((id) => [`#${id}`, new Element()]));
  const page = new Element();
  page.dataset.roleDashboard = role;
  const original = Object.fromEntries(["document", "window", "Node"].map((key) =>
    [key, Object.getOwnPropertyDescriptor(globalThis, key)]));
  Object.defineProperty(globalThis, "document", {
    value: {
      querySelector: (selector) => selector === "[data-role-dashboard]"
        ? page : nodes.get(selector),
      createElement: () => new Element(),
    },
    configurable: true,
  });
  Object.defineProperty(globalThis, "window", { value: {}, configurable: true });
  Object.defineProperty(globalThis, "Node", { value: Element, configurable: true });
  t.after(() => {
    for (const [key, descriptor] of Object.entries(original)) {
      if (descriptor) Object.defineProperty(globalThis, key, descriptor);
      else delete globalThis[key];
    }
  });
  return nodes;
}

const response = (message) => ({ ok: true, json: async () => ({ message }) });
const tick = () => new Promise((resolve) => setTimeout(resolve, 0));

for (const [role, expectedMetrics] of [["owner", 8], ["sales", 5]]) {
  test(`${role} dashboard renders real role-appropriate metrics and sales trends`, async (t) => {
    const nodes = install(t, role);
    const calls = [];
    t.mock.method(globalThis, "fetch", async (url) => {
      calls.push(String(url));
      if (url.includes("administration.dashboard")) return response({
        business: {
          total_sales: 1320, successful_payments: 3, pending_payments: 2,
          total_orders: 7, pending_orders: 4, completed_orders: 2,
          total_customers: 5, total_products: 9,
        },
      });
      if (url.includes("administration.sales_analytics")) return response({
        daily: [{ period: "2026-11-15", sales: 1200 }],
        monthly: [{ period: "2026-11", sales: 1200 }],
        by_product: [{ product_name: "Coffee", item_sales: 1200 }],
      });
      throw new Error(`Unexpected request: ${url}`);
    });
    await import(`../../intelligent_ordering/public/js/role-dashboard.js?${role}=${Date.now()}`);
    await tick();
    assert.equal(calls.length, 2);
    assert.equal(nodes.get("#role-dashboard-metrics").children.length, expectedMetrics);
    assert.match(nodes.get("#role-dashboard-metrics").textContent, /Verified sales.*KES\s1,320\.00/);
    assert.match(nodes.get("#role-dashboard-daily").textContent, /2026-11-15.*KES\s1,200\.00/);
    assert.match(nodes.get("#role-dashboard-products").textContent, /Coffee.*KES\s1,200\.00/);
    assert.match(nodes.get("#role-dashboard-status").textContent, /live SmartO records/);
  });
}

