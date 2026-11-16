import assert from "node:assert/strict";
import test from "node:test";

class Element {
  constructor() {
    this.children = [];
    this.listeners = {};
    this.textContent = "";
    this.value = "";
    this.disabled = false;
    this.hidden = false;
    this.dataset = {};
  }
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren(...nodes) { this.children = nodes; }
  add(node) { this.children.push(node); }
  addEventListener(name, handler) { this.listeners[name] = handler; }
  setAttribute(name, value) { this[name] = value; }
  reportValidity() { return true; }
}

function install(t, mode) {
  const nodes = new Map([
    "orders-status", "orders-list", "order-detail", "orders-pagination",
    "orders-previous", "orders-next", "orders-page", "orders-filters", "orders-login",
  ].map((id) => [`#${id}`, new Element()]));
  nodes.get("#orders-filters").elements = {
    search: new Element(), status: new Element(), payment_status: new Element(),
  };
  const original = {};
  function setGlobal(name, value) {
    original[name] = Object.getOwnPropertyDescriptor(globalThis, name);
    Object.defineProperty(globalThis, name, { value, writable: true, configurable: true });
  }
  setGlobal("document", {
    querySelector: (selector) => selector === "[data-orders-page]"
      ? { dataset: { ordersPage: mode } } : nodes.get(selector),
    createElement: () => new Element(),
  });
  setGlobal("window", { frappe: {}, setInterval: () => 1, clearInterval() {}, confirm: () => true });
  setGlobal("Option", class extends Element {
    constructor(label, value) { super(); this.textContent = label; this.value = value; }
  });
  t.after(() => {
    for (const [name, descriptor] of Object.entries(original)) {
      if (descriptor) Object.defineProperty(globalThis, name, descriptor);
      else delete globalThis[name];
    }
  });
  return nodes;
}

const response = (message) => ({ ok: true, json: async () => ({ message }) });
const failed = (message) => ({ ok: false, json: async () => ({ message }) });
const tick = () => new Promise((resolve) => setTimeout(resolve, 0));
const order = {
  name: "SO-1", status: "Pending", payment_status: "Unpaid",
  customer_name: "Customer", customer_phone: "123", delivery_address: "Address",
  order_datetime: "2026-01-01", currency: "KES", subtotal: 100, delivery_fee: 10, total: 110,
  items: [{ product_name: "Milk", quantity: 1, unit_price: 100, line_total: 100 }],
};

test("customer history uses owner-only detail and shows payment status", async (t) => {
  const nodes = install(t, "customer");
  const calls = [];
  t.mock.method(globalThis, "fetch", async (url) => {
    calls.push(String(url));
    if (url.includes("orders.get_my_orders")) return response({ orders: [order], has_more: false });
    if (url.includes("orders.get_my_order")) return response(order);
    if (url.includes("payments.get_order_payments")) return response([]);
    if (url.includes("customers.track_order")) return response({ order_status: "Pending", payment_status: "Unpaid", timeline: [] });
    throw new Error(`Unexpected request: ${url}`);
  });
  await import(`../../intelligent_ordering/public/js/order-pages.js?customer=${Date.now()}`);
  await tick();
  await nodes.get("#orders-list").children[0].children.at(-1).listeners.click();
  await tick();
  const orderCard = nodes.get("#orders-list").children[0];
  assert.equal(orderCard.children[0].children[1].dataset.status, "pending");
  assert.ok(calls.some((url) => url.includes("orders.get_my_order?")));
  const card = nodes.get("#order-detail").children[0];
  assert.ok(card.children.some((node) => node.textContent === "Payment status: Unpaid"));
});

test("guest sees login and no customer records", async (t) => {
  const nodes = install(t, "customer");
  t.mock.method(globalThis, "fetch", async () => response({ requires_login: true, orders: [] }));
  await import(`../../intelligent_ordering/public/js/order-pages.js?guest=${Date.now()}`);
  await tick();
  assert.equal(nodes.get("#orders-login").hidden, false);
  assert.equal(nodes.get("#orders-list").children.length, 0);
});

test("payment button stays disabled until payment history is loaded", async (t) => {
  const nodes = install(t, "customer");
  let resolvePayments;
  t.mock.method(globalThis, "fetch", async (url) => {
    if (url.includes("orders.get_my_orders")) return response({ orders: [order], has_more: false });
    if (url.includes("orders.get_my_order")) return response(order);
    if (url.includes("customers.track_order")) return response({ order_status: "Pending", payment_status: "Unpaid", timeline: [] });
    if (url.includes("payments.get_order_payments")) {
      return new Promise((resolve) => { resolvePayments = resolve; });
    }
    throw new Error(`Unexpected request: ${url}`);
  });
  await import(`../../intelligent_ordering/public/js/order-pages.js?payments=${Date.now()}`);
  await tick();
  await nodes.get("#orders-list").children[0].children.at(-1).listeners.click();
  const card = nodes.get("#order-detail").children[0];
  const form = card.children.find((child) => child.className === "status-update-form");
  assert.equal(form.children[1].disabled, true);
  resolvePayments(response([{ status: "Pending", amount: 110 }]));
  await tick();
  assert.equal(form.children[1].disabled, true);
});

test("staff can filter and update an order through existing APIs", async (t) => {
  const nodes = install(t, "staff");
  const calls = [];
  let currentStatus = "Pending";
  t.mock.method(globalThis, "fetch", async (url, options) => {
    calls.push({ url: String(url), options });
    if (url.includes("orders.list_orders")) return response({
      orders: [{ ...order, customer_name_snapshot: "Customer", customer_phone_snapshot: "123" }],
      has_more: false,
    });
    if (url.includes("orders.get_order")) return response({ ...order, status: currentStatus });
    if (url.includes("orders.update_order_status")) {
      currentStatus = "Confirmed";
      return response({ ...order, status: currentStatus });
    }
    throw new Error(`Unexpected request: ${url}`);
  });
  await import(`../../intelligent_ordering/public/js/order-pages.js?staff=${Date.now()}`);
  await tick();
  const filters = nodes.get("#orders-filters");
  filters.elements.payment_status.value = "Unpaid";
  filters.listeners.submit({ preventDefault() {} });
  await tick();
  assert.match(calls.filter((call) => call.url.includes("orders.list_orders")).at(-1).url, /payment_status=Unpaid/);
  await nodes.get("#orders-list").children[0].children.at(-1).listeners.click();
  const card = nodes.get("#order-detail").children[0];
  const form = card.children.find((child) => child.className === "smarto-catalog-form");
  form.children[0].children[0].value = "Confirmed";
  await form.listeners.submit({ preventDefault() {} });
  const update = calls.find((call) => call.url.includes("orders.update_order_status"));
  assert.equal(update.options.body.get("status"), "Confirmed");
  assert.ok(nodes.get("#order-detail").children[0].children.some((node) => node.textContent === "Order status: Confirmed"));
});

test("staff API rejection does not display orders", async (t) => {
  const nodes = install(t, "staff");
  t.mock.method(globalThis, "fetch", async () => failed("Not authorized"));
  await import(`../../intelligent_ordering/public/js/order-pages.js?denied=${Date.now()}`);
  await tick();
  assert.equal(nodes.get("#orders-list").children.length, 0);
  assert.match(nodes.get("#orders-status").textContent, /Not authorized/);
});

test("support uses staff read APIs without status or payment controls", async (t) => {
  const nodes = install(t, "support");
  t.mock.method(globalThis, "fetch", async (url) => {
    if (url.includes("orders.list_orders")) return response({ orders: [order], has_more: false });
    if (url.includes("orders.get_order")) return response(order);
    throw new Error(`Unexpected request: ${url}`);
  });

  await import(`../../intelligent_ordering/public/js/order-pages.js?support=${Date.now()}`);
  await tick();
  await nodes.get("#orders-list").children[0].children.at(-1).listeners.click();
  await tick();
  const card = nodes.get("#order-detail").children[0];
  assert.ok(card.children.some((node) => node.textContent === "Read-only customer support view."));
  assert.ok(!card.children.some((node) =>
    node.className === "smarto-catalog-form" || node.className === "status-update-form"));
});

test("customer live tracking refreshes persisted status and requests cancellation without changing totals", async (t) => {
  const nodes = install(t, "customer");
  const calls = [];
  let requested = false;
  let paid = false;
  t.mock.method(globalThis, "fetch", async (url, options) => {
    calls.push({ url, options });
    if (url.includes("orders.get_my_orders")) return response({ orders: [order], has_more: false });
    if (url.includes("orders.get_my_order")) return response(order);
    if (url.includes("payments.get_order_payments")) return response([]);
    if (url.includes("request_cancellation")) requested = true;
    return response({
      order_status: "Confirmed", payment_status: paid ? "Paid" : "Unpaid", delivery: { status: "Assigned" },
      timeline: [{ activity_datetime: "Today", from_status: "Awaiting Assignment", to_status: "Assigned" }],
      cancellation_request_status: requested ? "Requested" : null,
    });
  });
  await import(`../../intelligent_ordering/public/js/order-pages.js?tracking=${Date.now()}`);
  await tick();
  await nodes.get("#orders-list").children[0].children.at(-1).listeners.click();
  await tick();
  const tracking = nodes.get("#order-detail").children[0].children.at(-1);
  assert.match(tracking.children[1].textContent, /Order: Confirmed.*Delivery: Assigned/);
  const form = tracking.children[4];
  assert.equal(form.hidden, false);
  form.children[0].children[0].value = "Please cancel";
  await form.listeners.submit({ preventDefault() {} });
  const call = calls.find((call) => call.url.includes("request_cancellation"));
  assert.equal(call.options.body.get("reason"), "Please cancel");
  assert.equal(call.options.body.has("status"), false);
  assert.equal(form.hidden, true);
  assert.match(tracking.children.at(-1).textContent, /Staff must approve/);
  paid = true;
  await tracking.children[2].listeners.click();
  const card = nodes.get("#order-detail").children[0];
  assert.equal(card.children[2].textContent, "Payment status: Paid");
  const paymentForm = card.children.find((child) => child.className === "status-update-form");
  assert.equal(paymentForm.hidden, true);
  assert.equal(paymentForm.children[1].disabled, true);
});
