import assert from "node:assert/strict";
import test from "node:test";

class Element {
  constructor(tag = "div") {
    this.tag = tag;
    this.children = [];
    this.dataset = {};
    this.listeners = {};
    this.value = "";
    this.hidden = false;
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

function install(t) {
  const selectors = [
    "admin-dashboard-status", "admin-dashboard-error", "admin-dashboard-refresh",
    "admin-dashboard-metrics", "admin-dashboard-daily", "admin-dashboard-monthly",
    "admin-dashboard-products", "admin-dashboard-orders", "admin-dashboard-payments",
    "admin-dashboard-stock",
  ];
  const nodes = new Map(selectors.map((id) => [`#${id}`, new Element()]));
  const original = Object.fromEntries(["document", "window", "Node"].map((key) =>
    [key, Object.getOwnPropertyDescriptor(globalThis, key)]));
  Object.defineProperty(globalThis, "document", {
    value: {
      querySelector: (selector) => selector === "[data-admin-dashboard]"
        ? new Element("main") : nodes.get(selector),
      createElement: (tag) => new Element(tag),
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

test("admin dashboard displays live metrics, verified sales and operational records", async (t) => {
  const nodes = install(t);
  const calls = [];
  t.mock.method(globalThis, "fetch", async (url) => {
    calls.push(String(url));
    if (url.includes("administration.dashboard")) return response({
      business: {
        total_sales: 1000, total_orders: 8, total_customers: 4, total_products: 6,
        successful_payments: 5, pending_payments: 2, pending_orders: 3, completed_orders: 4,
      },
      inventory: { low_stock_products: 1, out_of_stock_products: 1 },
      delivery: { pending_deliveries: 2, dispatched_deliveries: 1 },
    });
    if (url.includes("administration.sales_analytics")) return response({
      daily: [{ period: "2026-11-15", sales: 800 }],
      monthly: [{ period: "2026-11", sales: 800 }],
      by_product: [{ product_name: "Milk", item_sales: 800 }],
    });
    if (url.includes("orders.list_orders")) return response({ orders: [{
      name: "SO-1", customer_name_snapshot: "Customer", status: "Pending", total: 800, currency: "KES",
    }] });
    if (url.includes("payments.list_transactions")) return response({ transactions: [{
      order: "SO-1", transaction_date: "2026-11-15", status: "Successful", amount: 800,
    }] });
    if (url.includes("inventory.list_stock")) {
      const outOfStock = String(url).includes("out_of_stock");
      return response({ stock: [{
        product_name: outOfStock ? "Tea" : "Coffee",
        sku: outOfStock ? "TEA" : "COF",
        warehouse_name: "Main",
        available_quantity: outOfStock ? 0 : 2,
      }] });
    }
    throw new Error(`Unexpected request: ${url}`);
  });
  await import(`../../intelligent_ordering/public/js/admin-dashboard.js?success=${Date.now()}`);
  await tick();
  assert.equal(calls.length, 6);
  assert.equal(nodes.get("#admin-dashboard-metrics").children.length, 12);
  assert.match(nodes.get("#admin-dashboard-metrics").textContent, /KES\s1,000\.00/);
  assert.match(nodes.get("#admin-dashboard-daily").textContent, /KES\s800\.00/);
  assert.match(nodes.get("#admin-dashboard-products").textContent, /Milk/);
  assert.match(nodes.get("#admin-dashboard-orders").textContent, /SO-1.*Customer.*Pending/);
  assert.match(nodes.get("#admin-dashboard-payments").textContent, /Successful.*KES\s800\.00/);
  assert.match(nodes.get("#admin-dashboard-stock").textContent, /Tea.*Out of stock.*0 available/);
  assert.match(nodes.get("#admin-dashboard-stock").textContent, /Coffee.*Low stock.*2 available/);
  assert.match(nodes.get("#admin-dashboard-status").textContent, /live SmartO records/);
});

test("admin dashboard reports failed data requests instead of claiming a refresh succeeded", async (t) => {
  const nodes = install(t);
  t.mock.method(globalThis, "fetch", async (url) => {
    if (url.includes("administration.dashboard")) return response({ business: {}, inventory: {}, delivery: {} });
    if (url.includes("administration.sales_analytics")) {
      return { ok: false, status: 403, json: async () => ({ message: "Not authorized." }) };
    }
    return response({ orders: [], transactions: [], stock: [] });
  });
  await import(`../../intelligent_ordering/public/js/admin-dashboard.js?failure=${Date.now()}`);
  await tick();
  assert.match(nodes.get("#admin-dashboard-status").textContent, /could not be refreshed/);
  assert.match(nodes.get("#admin-dashboard-error").textContent, /permission.*administration\.sales_analytics, HTTP 403/);
});

test("admin dashboard shows honest empty states when the APIs return no records", async (t) => {
  const nodes = install(t);
  t.mock.method(globalThis, "fetch", async (url) => {
    if (url.includes("administration.dashboard")) {
      return response({ business: { total_orders: 0 }, inventory: {}, delivery: {} });
    }
    if (url.includes("administration.sales_analytics")) {
      return response({ daily: [], monthly: [], by_product: [] });
    }
    if (url.includes("orders.list_orders")) return response({ orders: [] });
    if (url.includes("payments.list_transactions")) return response({ transactions: [] });
    if (url.includes("inventory.list_stock")) return response({ stock: [] });
    throw new Error(`Unexpected request: ${url}`);
  });
  await import(`../../intelligent_ordering/public/js/admin-dashboard.js?empty=${Date.now()}`);
  await tick();
  assert.equal(nodes.get("#admin-dashboard-metrics").children.length, 1);
  assert.equal(nodes.get("#admin-dashboard-daily").textContent, "No records for this period.");
  assert.equal(nodes.get("#admin-dashboard-orders").textContent, "No orders have been placed.");
  assert.equal(nodes.get("#admin-dashboard-payments").textContent, "No payment transactions are recorded.");
  assert.equal(nodes.get("#admin-dashboard-stock").textContent, "No low or out-of-stock products.");
});
