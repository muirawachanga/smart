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
  append(...nodes) {
    for (const node of nodes) {
      node.remove();
      node.parent = this;
      this.children.push(node);
    }
  }
  prepend(...nodes) {
    for (const node of [...nodes].reverse()) {
      node.remove();
      node.parent = this;
      this.children.unshift(node);
    }
  }
  remove() {
    if (this.parent) this.parent.children = this.parent.children.filter((node) => node !== this);
    this.parent = null;
  }
  replaceChildren(...nodes) {
    for (const node of this.children) node.parent = null;
    this.children = [];
    this.append(...nodes);
  }
  add(node) { this.children.push(node); }
  addEventListener(name, handler) { this.listeners[name] = handler; }
  setAttribute(name, value) { this[name] = value; }
  setCustomValidity(value) { this.validationMessage = value; }
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
  setGlobal("window", {
    frappe: {}, location: { pathname: mode === "customer" ? "/track-order" : "/dashboard/orders", search: "" },
    setInterval: () => 1, clearInterval() {}, confirm: () => true,
  });
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
const renderedText = (node) => [node.textContent, ...node.children.map(renderedText)].join(" ");
async function waitFor(predicate) {
  for (let attempt = 0; attempt < 10 && !predicate(); attempt += 1) await tick();
  assert.ok(predicate(), "expected asynchronous order UI to finish rendering");
}
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
  assert.equal(nodes.get("#order-detail").parent, orderCard);
  assert.equal(orderCard.children[0].children[1].dataset.status, "pending");
  assert.ok(calls.some((url) => url.includes("orders.get_my_order?")));
  const card = nodes.get("#order-detail").children[0];
  assert.ok(card.children.some((node) => node.textContent === "Payment status: Unpaid"));
});

test("checkout tracking URL opens the order and shows its assigned rider", async (t) => {
  const nodes = install(t, "customer");
  window.location.search = "?order=SO-1";
  t.mock.method(globalThis, "fetch", async (url) => {
    if (url.includes("orders.get_my_orders")) return response({ orders: [order], has_more: false });
    if (url.includes("orders.get_my_order")) return response({ ...order });
    if (url.includes("payments.get_order_payments")) return response([]);
    if (url.includes("customers.track_order")) return response({
      order_status: "Ready for Delivery", payment_status: "Paid",
      delivery: {
        name: "DEL-1", status: "Assigned", delivery_area: "Central",
        assigned_rider: "Rider One", scheduled_delivery_date: "2026-11-18",
      },
      timeline: [{ activity_datetime: "now", from_status: "Awaiting Assignment", to_status: "Assigned" }],
    });
    throw new Error(`Unexpected request: ${url}`);
  });
  await import(`../../intelligent_ordering/public/js/order-pages.js?track-order=${Date.now()}`);
  for (let attempt = 0; attempt < 5 && !nodes.get("#order-detail").children.length; attempt += 1) {
    await tick();
  }
  const detail = nodes.get("#order-detail");
  assert.ok(detail.children.length);
  const content = renderedText(detail);
  assert.match(content, /Rider: Rider One/);
  assert.match(content, /Delivery: Assigned/);
  assert.match(content, /Awaiting Assignment → Assigned/);
});

test("tracking link opens an owned order not present on the first history page", async (t) => {
  const nodes = install(t, "customer");
  window.location.search = "?order=SO-OLD";
  t.mock.method(globalThis, "fetch", async (url) => {
    if (url.includes("orders.get_my_orders")) return response({ orders: [order], has_more: true });
    if (url.includes("orders.get_my_order")) return response({ ...order, name: "SO-OLD" });
    if (url.includes("payments.get_order_payments")) return response([]);
    if (url.includes("customers.track_order")) return response({
      order_status: "Ready for Delivery", payment_status: "Unpaid",
      delivery: { status: "Delivered", customer_receipt_confirmed: 0 }, timeline: [],
    });
    throw new Error(`Unexpected request: ${url}`);
  });
  await import(`../../intelligent_ordering/public/js/order-pages.js?older-order=${Date.now()}`);
  await waitFor(() => renderedText(nodes.get("#order-detail")).includes("Order SO-OLD"));
  const button = nodes.get("#order-detail").children[0].children.at(-1).children
    .find((child) => child.textContent === "Confirm I received this order");
  await waitFor(() => !button.disabled);
  assert.equal(button.hidden, false);
});

test("guest sees login and no customer records", async (t) => {
  const nodes = install(t, "customer");
  t.mock.method(globalThis, "fetch", async () => response({ requires_login: true, orders: [] }));
  await import(`../../intelligent_ordering/public/js/order-pages.js?guest=${Date.now()}`);
  await tick();
  assert.equal(nodes.get("#orders-login").hidden, false);
  assert.equal(nodes.get("#orders-list").children.length, 0);
});

test("order details move to the selected card and detach when filtering it out", async (t) => {
  const nodes = install(t, "support");
  let visibleOrders = [order, { ...order, name: "SO-2" }];
  t.mock.method(globalThis, "fetch", async (url) => {
    if (url.includes("orders.list_orders")) return response({ orders: visibleOrders, has_more: false });
    const name = new URL(url, "https://example.test").searchParams.get("order_name");
    return response({ ...order, name });
  });
  await import(`../../intelligent_ordering/public/js/order-pages.js?inline=${Date.now()}`);
  await tick();
  const [first, second] = nodes.get("#orders-list").children;
  await first.children.at(-1).listeners.click();
  assert.equal(nodes.get("#order-detail").parent, first);
  await second.children.at(-1).listeners.click();
  assert.equal(nodes.get("#order-detail").parent, second);
  assert.ok(!first.children.includes(nodes.get("#order-detail")));
  visibleOrders = [order];
  nodes.get("#orders-filters").listeners.submit({ preventDefault() {} });
  await tick();
  assert.equal(nodes.get("#order-detail").parent, null);
  assert.equal(nodes.get("#order-detail").children.length, 0);
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
  await waitFor(() => nodes.get("#order-detail").children[0]?.children
    .some((child) => child.className === "status-update-form"));
  const card = nodes.get("#order-detail").children[0];
  const form = card.children.find((child) => child.className === "status-update-form");
  assert.equal(form.children[2].disabled, true);
  resolvePayments(response([{ status: "Pending", amount: 110 }]));
  await tick();
  assert.equal(form.children[2].disabled, true);
});

test("payment failure shows a dismissible warning to check payment status", async (t) => {
  const nodes = install(t, "customer");
  t.mock.method(globalThis, "fetch", async (url) => {
    if (url.includes("orders.get_my_orders")) return response({ orders: [order], has_more: false });
    if (url.includes("orders.get_my_order")) return response(order);
    if (url.includes("customers.track_order")) return response({ order_status: "Pending", payment_status: "Unpaid", timeline: [] });
    if (url.includes("payments.get_order_payments")) return response([]);
    if (url.includes("payments.initiate_payment")) throw new Error("network details");
    throw new Error(`Unexpected request: ${url}`);
  });
  await import(`../../intelligent_ordering/public/js/order-pages.js?payment-error=${Date.now()}`);
  await tick();
  await nodes.get("#orders-list").children[0].children.at(-1).listeners.click();
  const form = nodes.get("#order-detail").children[0].children.find((child) => child.className === "status-update-form");
  await waitFor(() => !form.children[2].disabled);
  form.children[1].children[0].value = "+254700000000";
  await form.listeners.submit({ preventDefault() {} });
  const banner = form.children[0];
  assert.equal(banner.hidden, false);
  assert.match(banner.children[0].textContent, /Check your payment status/);
  assert.equal(form.children[1].children[0].value, "+254700000000");
  banner.children[1].listeners.click();
  assert.equal(banner.hidden, true);
});

test("an unresolved provider response is not described as a failed payment", async (t) => {
  const nodes = install(t, "customer");
  let initiated = false;
  const pending = { status: "Initiated", amount: 110, failure_description: "Provider outcome unknown" };
  t.mock.method(globalThis, "fetch", async (url) => {
    if (url.includes("orders.get_my_orders")) return response({ orders: [order], has_more: false });
    if (url.includes("orders.get_my_order")) return response(order);
    if (url.includes("customers.track_order")) return response({ order_status: "Pending", payment_status: "Unpaid", timeline: [] });
    if (url.includes("payments.get_order_payments")) return response(initiated ? [pending] : []);
    if (url.includes("payments.initiate_payment")) { initiated = true; return response(pending); }
    throw new Error(`Unexpected request: ${url}`);
  });
  await import(`../../intelligent_ordering/public/js/order-pages.js?unknown-payment=${Date.now()}`);
  await tick();
  await nodes.get("#orders-list").children[0].children.at(-1).listeners.click();
  const card = nodes.get("#order-detail").children[0];
  const form = card.children.find((child) => child.className === "status-update-form");
  await waitFor(() => !form.children[2].disabled);
  await form.listeners.submit({ preventDefault() {} });
  assert.match(form.children[0].children[0].textContent, /Check your payment status/);
  assert.match(renderedText(card), /Check your payment status/);
  assert.doesNotMatch(renderedText(card), /Payment couldn't be completed|Provider outcome unknown/);
  assert.equal(form.children[2].disabled, true);
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

test("ready order assignment link preserves the selected order", async (t) => {
  const nodes = install(t, "staff");
  const readyOrder = { ...order, name: "SO /1", status: "Ready for Delivery" };
  t.mock.method(globalThis, "fetch", async (url) => {
    if (url.includes("orders.list_orders")) return response({ orders: [readyOrder], has_more: false });
    if (url.includes("orders.get_order")) return response(readyOrder);
    throw new Error(`Unexpected request: ${url}`);
  });
  await import(`../../intelligent_ordering/public/js/order-pages.js?assignment=${Date.now()}`);
  await tick();
  await nodes.get("#orders-list").children[0].children.at(-1).listeners.click();
  const link = nodes.get("#order-detail").children[0].children
    .find((child) => child.textContent === "Assign or monitor delivery");
  const target = new URL(link.href, "https://example.test");
  assert.equal(target.pathname, "/dashboard/delivery");
  assert.equal(target.searchParams.get("order"), readyOrder.name);
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
  await waitFor(() => nodes.get("#order-detail").children[0]?.children.at(-1)?.children
    .some((child) => /Order: Confirmed.*Delivery: Assigned/.test(child.textContent)));
  const tracking = nodes.get("#order-detail").children[0].children.at(-1);
  assert.match(tracking.children[1].textContent, /Order: Confirmed.*Delivery: Assigned/);
  const form = tracking.children.find((child) => child.className === "smarto-checkout-form");
  assert.equal(form.hidden, false);
  form.children[1].children[0].value = "Please cancel";
  await form.listeners.submit({ preventDefault() {} });
  const call = calls.find((call) => call.url.includes("request_cancellation"));
  assert.equal(call.options.body.get("reason"), "Please cancel");
  assert.equal(call.options.body.has("status"), false);
  assert.equal(form.hidden, true);
  assert.match(tracking.children.at(-1).textContent, /Staff must approve/);
  paid = true;
  await tracking.children.find((child) => child.textContent === "Refresh order status").listeners.click();
  const card = nodes.get("#order-detail").children[0];
  assert.equal(card.children[2].textContent, "Payment status: Paid");
  const paymentForm = card.children.find((child) => child.className === "status-update-form");
  assert.equal(paymentForm.hidden, true);
  assert.equal(paymentForm.children[2].disabled, true);
});

test("cancellation failure preserves the reason and shows a dismissible warning", async (t) => {
  const nodes = install(t, "customer");
  t.mock.method(globalThis, "fetch", async (url) => {
    if (url.includes("orders.get_my_orders")) return response({ orders: [order], has_more: false });
    if (url.includes("orders.get_my_order")) return response(order);
    if (url.includes("payments.get_order_payments")) return response([]);
    if (url.includes("customers.request_cancellation")) return { ok: false, status: 500, json: async () => ({ message: "private details" }) };
    if (url.includes("customers.track_order")) return response({ order_status: "Pending", payment_status: "Unpaid", timeline: [] });
    throw new Error(`Unexpected request: ${url}`);
  });
  await import(`../../intelligent_ordering/public/js/order-pages.js?cancellation-error=${Date.now()}`);
  await tick();
  await nodes.get("#orders-list").children[0].children.at(-1).listeners.click();
  const tracking = nodes.get("#order-detail").children[0].children.at(-1);
  const form = tracking.children.find((child) => child.className === "smarto-checkout-form");
  const reason = form.children[1].children[0];
  reason.value = "Please cancel";
  await form.listeners.submit({ preventDefault() {} });
  const banner = form.children[0];
  assert.equal(banner.hidden, false);
  assert.match(banner.children[0].textContent, /try again later/i);
  assert.doesNotMatch(banner.children[0].textContent, /private details/);
  assert.equal(reason.value, "Please cancel");
  banner.children[1].listeners.click();
  assert.equal(banner.hidden, true);
});

test("customer confirms receipt after rider delivery and sees COD reconciliation pending", async (t) => {
  const nodes = install(t, "customer");
  let confirmed = false;
  const calls = [];
  t.mock.method(globalThis, "fetch", async (url, options = {}) => {
    calls.push({ url: String(url), options });
    if (url.includes("orders.get_my_orders")) return response({ orders: [order], has_more: false });
    if (url.includes("orders.get_my_order")) return response({ ...order });
    if (url.includes("payments.get_order_payments")) return response([]);
    if (url.includes("customers.confirm_delivery_receipt")) {
      confirmed = true;
      return response({
        order_status: "Ready for Delivery", payment_status: "Unpaid",
        delivery: { status: "Delivered", customer_receipt_confirmed: true },
        timeline: [],
      });
    }
    if (url.includes("customers.track_order")) return response({
      order_status: "Ready for Delivery", payment_status: "Unpaid",
      delivery: { status: "Delivered", customer_receipt_confirmed: confirmed },
      timeline: [],
    });
    throw new Error(`Unexpected request: ${url}`);
  });
  await import(`../../intelligent_ordering/public/js/order-pages.js?receipt=${Date.now()}`);
  await tick();
  await nodes.get("#orders-list").children[0].children.at(-1).listeners.click();
  const tracking = nodes.get("#order-detail").children[0].children.at(-1);
  const button = tracking.children.find((child) => child.textContent === "Confirm I received this order");
  await waitFor(() => !button.disabled);
  assert.match(tracking.children[1].textContent, /Delivery: Delivered.*Awaiting your confirmation/);
  await button.listeners.click();
  assert.ok(calls.some((call) => call.url.includes("customers.confirm_delivery_receipt")
    && call.options.body.get("order_name") === order.name));
  assert.equal(button.hidden, true);
  assert.match(tracking.children[3].textContent, /Payment verification is still pending/);
});

test("receipt button follows delivery status and disables if tracking refresh fails", async (t) => {
  const nodes = install(t, "customer");
  let deliveryStatus = "In Transit";
  let trackingFails = false;
  t.mock.method(globalThis, "fetch", async (url) => {
    if (url.includes("orders.get_my_orders")) return response({ orders: [order], has_more: false });
    if (url.includes("orders.get_my_order")) return response({ ...order });
    if (url.includes("payments.get_order_payments")) return response([]);
    if (url.includes("customers.track_order")) return trackingFails ? failed("Tracking unavailable") : response({
      order_status: "Ready for Delivery", payment_status: "Paid",
      delivery: { status: deliveryStatus, customer_receipt_confirmed: 0 }, timeline: [],
    });
    throw new Error(`Unexpected request: ${url}`);
  });
  await import(`../../intelligent_ordering/public/js/order-pages.js?pending-receipt=${Date.now()}`);
  await tick();
  await nodes.get("#orders-list").children[0].children.at(-1).listeners.click();
  const tracking = nodes.get("#order-detail").children[0].children.at(-1);
  await waitFor(() => tracking.children[1].textContent.includes("In Transit"));
  const button = tracking.children.find((child) => child.textContent === "Confirm I received this order");
  assert.equal(button.hidden, false);
  assert.equal(button.disabled, true);
  assert.match(tracking.children[3].textContent, /after the rider marks the delivery as delivered/);
  const refresh = tracking.children.find((child) => child.textContent === "Refresh order status");
  deliveryStatus = "Delivered";
  await refresh.listeners.click();
  assert.equal(button.disabled, false);
  trackingFails = true;
  await refresh.listeners.click();
  assert.equal(button.disabled, true);
  assert.match(tracking.children[1].textContent, /Order status could not be refreshed/);
});
