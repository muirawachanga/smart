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
  prepend(...nodes) { this.children.unshift(...nodes); }
  replaceChildren(...nodes) { this.children = [...nodes]; }
  addEventListener(name, callback) { this.listeners[name] = callback; }
  setAttribute(name, value) { this[name] = value; }
}

test("finance overview separates currencies and renders verified periods and outstanding amounts", async (t) => {
  const nodes = install(t, "sales");
  nodes.set("#finance-overview-metrics", new Element());
  nodes.set("#finance-method-report", new Element());
  nodes.set("#role-dashboard-weekly", new Element());
  t.mock.method(globalThis, "fetch", async (url) => {
    if (url.includes("administration.dashboard")) return response({ business: {} });
    if (url.includes("administration.sales_analytics")) return response({
      daily: [], monthly: [], by_product: [], weekly: [{ period: "2026-W46", sales: 100 }],
    });
    if (url.includes("payments.finance_overview")) return response({
      payments: [
        { currency: "KES", collected: 100, pending: 80, failed: 80, reversed: 25,
          daily_revenue: 100, weekly_revenue: 100, monthly_revenue: 100 },
        { currency: "USD", collected: 3, pending: 0, failed: 0, reversed: 0,
          daily_revenue: 0, weekly_revenue: 3, monthly_revenue: 3 },
      ],
      outstanding: [{ currency: "KES", outstanding: 80 }, { currency: "USD", outstanding: 7 }],
      methods: [{ payment_method: "M-Pesa", status: "Successful", currency: "KES", transactions: 1, amount: 100 }],
    });
    throw new Error(`Unexpected request: ${url}`);
  });
  await import(`../../intelligent_ordering/public/js/role-dashboard.js?finance-overview=${Date.now()}`);
  await tick();
  const metrics = nodes.get("#finance-overview-metrics").textContent;
  assert.match(metrics, /verified sales.*KES.*100\.00/);
  assert.match(metrics, /Outstanding order balances.*KES.*80\.00/);
  assert.match(metrics, /Outstanding order balances.*USD.*7\.00/);
  assert.match(nodes.get("#role-dashboard-weekly").textContent, /2026-W46/);
  assert.match(nodes.get("#finance-method-report").textContent, /M-Pesa.*Successful.*KES.*1 transactions/);
});

function addCustomerWorkspace(nodes) {
  for (const selector of [
    "[data-customer-workspace]", "#customer-workspace-search", "#customer-workspace-feedback",
    "#customer-workspace-results", "#customer-workspace-detail", "#customer-workspace-previous",
    "#customer-workspace-next", "#customer-history-previous", "#customer-history-next",
    "#customer-history-pagination",
  ]) nodes.set(selector, new Element());
  nodes.get("#customer-workspace-search").elements = { search: new Element() };
}

test("customer workspace searches profiles and paginates real customer order history", async (t) => {
  const nodes = install(t, "owner");
  addCustomerWorkspace(nodes);
  const calls = [];
  t.mock.method(globalThis, "fetch", async (url) => {
    calls.push(String(url));
    if (url.includes("administration.list_customers")) return response({
      customers: [{ name: "C-1", full_name: "Buyer", phone: "254712345678", email: "buyer@example.test", total_orders: 21 }],
      has_more: false,
    });
    if (url.includes("administration.customer_activity")) return response({
      customer: { name: "C-1", full_name: "Buyer", phone: "254712345678", email: "buyer@example.test", enabled: 1 },
      orders: [{ name: "SO-1", status: "Confirmed", payment_status: "Paid", total: 100, currency: "KES" }],
      has_more: !url.includes("page=2"),
    });
    throw new Error(`Unexpected request: ${url}`);
  });
  await import(`../../intelligent_ordering/public/js/customer-workspace.js?customers=${Date.now()}`);
  await tick();
  assert.match(nodes.get("#customer-workspace-results").textContent, /Buyer/);
  nodes.get("#customer-workspace-search").elements.search.value = "Buyer";
  nodes.get("#customer-workspace-search").listeners.submit({ preventDefault() {} });
  await tick();
  assert.match(calls.at(-1), /search=Buyer/);
  nodes.get("#customer-workspace-results").children[0].children.at(-1).listeners.click();
  await tick();
  assert.match(nodes.get("#customer-workspace-detail").textContent, /SO-1.*Paid/);
  nodes.get("#customer-history-next").listeners.click();
  await tick();
  assert.match(calls.at(-1), /customer=C-1&page=2/);
  assert.equal(nodes.get("#customer-history-next").disabled, true);
});

test("customer workspace clears records and reports denied searches", async (t) => {
  const nodes = install(t, "owner");
  addCustomerWorkspace(nodes);
  t.mock.method(globalThis, "fetch", async () => ({
    ok: false, status: 403, json: async () => ({ message: "Denied" }),
  }));
  await import(`../../intelligent_ordering/public/js/customer-workspace.js?denied=${Date.now()}`);
  await tick();
  assert.equal(nodes.get("#customer-workspace-results").children.length, 0);
  assert.match(nodes.get("#customer-workspace-feedback").textContent, /permission/);
});

test("management workspace displays persisted stock, products, deliveries and staff activity", async (t) => {
  const nodes = install(t, "owner");
  for (const selector of [
    "[data-management-activity]", "#management-activity-feedback", "#management-activity-refresh",
    "#management-inventory-alerts", "#management-product-performance",
    "#management-delivery-performance", "#management-staff-activity",
  ]) nodes.set(selector, new Element());
  t.mock.method(globalThis, "fetch", async (url) => {
    assert.match(String(url), /administration.management_activity/);
    return response({
      inventory_alerts: [{ product_name: "Milk", sku: "MILK", available: 2 }],
      products: [{ product_name: "Milk", units_sold: 4, orders: 2, item_sales: 100, currency: "KES" }],
      delivery: { completion_rate: 75, delayed_deliveries: 1, available_riders: 2,
        personnel_performance: [{ rider: "rider@example.test", completed: 3, failed: 1, total: 4 }] },
      events: [{ event_datetime: "Today", responsible_user: "staff@example.test",
        event_type: "Order status changed", reference_name: "SO-1", details: "Pending -> Confirmed" }],
    });
  });
  await import(`../../intelligent_ordering/public/js/management-activity.js?activity=${Date.now()}`);
  await tick();
  assert.match(nodes.get("#management-inventory-alerts").textContent, /MILK.*2 available/);
  assert.match(nodes.get("#management-product-performance").textContent, /4 units.*2 paid orders/);
  assert.match(nodes.get("#management-delivery-performance").textContent, /75% completed.*3 completed/);
  assert.match(nodes.get("#management-staff-activity").textContent, /staff@example.test.*SO-1/);
});

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

