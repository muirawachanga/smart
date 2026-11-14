import assert from "node:assert/strict";
import test from "node:test";
import { webcrypto } from "node:crypto";

class Element {
  constructor() {
    this.children = [];
    this.listeners = {};
    this.textContent = "";
    this.value = "";
    this.hidden = false;
    this.disabled = false;
  }
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren(...nodes) { this.children = nodes; }
  add(node) { this.children.push(node); }
  addEventListener(name, handler) { this.listeners[name] = handler; }
  reportValidity() { return true; }
}

function install(t) {
  function setGlobal(name, value) {
    const original = Object.getOwnPropertyDescriptor(globalThis, name);
    Object.defineProperty(globalThis, name, { value, configurable: true, writable: true });
    t.after(() => {
      if (original) Object.defineProperty(globalThis, name, original);
      else delete globalThis[name];
    });
  }
  const ids = [
    "cart-status", "cart-feedback", "cart-items", "cart-total", "clear-cart",
    "clear-guest-cart", "checkout-link", "checkout-status", "checkout-feedback",
    "checkout-login", "checkout-form", "checkout-area", "refresh-quote",
    "checkout-submit", "checkout-review", "checkout-totals", "checkout-subtotal", "checkout-address",
    "checkout-delivery-fee", "checkout-total", "order-status", "order-detail", "order-login",
  ];
  const nodes = new Map(ids.map((id) => [`#${id}`, new Element()]));
  nodes.get("#checkout-submit").disabled = true;
  const form = nodes.get("#checkout-form");
  form.elements = {
    customer_name: new Element(),
    phone: new Element(),
    address_line_1: new Element(), address_line_2: new Element(),
    city: new Element(), region: new Element(), postal_code: new Element(),
  };
  const session = new Map();
  const local = new Map();
  const events = [];
  const locations = [];
  const storage = (map) => ({
    getItem: (key) => map.get(key) ?? null,
    setItem: (key, value) => map.set(key, value),
    removeItem: (key) => map.delete(key),
  });
  setGlobal("document", {
    querySelector: (selector) => nodes.get(selector),
    createElement: () => new Element(),
    dispatchEvent: (event) => events.push(event),
  });
  setGlobal("window", {
    location: { pathname: "/checkout", search: "", assign: (url) => locations.push(url) },
    frappe: {},
  });
  setGlobal("sessionStorage", storage(session));
  setGlobal("localStorage", storage(local));
  setGlobal("Option", class extends Element {
    constructor(label, value) { super(); this.textContent = label; this.value = value; }
  });
  setGlobal("CustomEvent", class {
    constructor(type, options) { this.type = type; this.detail = options.detail; }
  });
  let tokenNumber = 0;
  setGlobal("crypto", {
    randomUUID: () => `4ec2b6b5-31a2-4c7f-a301-${String(++tokenNumber).padStart(12, "0")}`,
    subtle: webcrypto.subtle,
  });
  setGlobal("FormData", class {
    *[Symbol.iterator]() {
      yield ["customer_name", form.elements.customer_name.value];
      yield ["phone", form.elements.phone.value];
      yield ["address_line_1", "1 Main Road"];
      yield ["city", "Nairobi"];
    }
  });
  return { nodes, session, local, events, locations };
}

const response = (message) => ({ ok: true, json: async () => ({ message }) });
const failed = (message) => ({ ok: false, json: async () => ({ message }) });
const item = {
  product: "SKU-1", product_name: "Milk", quantity: 2, unit_price: 50,
  subtotal: 100, currency: "KES", available: true, available_quantity: 5,
};
const cart = { items: [item], item_count: 2, total: 100, currency: "KES", is_guest: false, max_quantity: 9999 };
const checkout = {
  requires_login: false, cart, cart_revision: "revision-1", customer_name: "Customer",
  phone: "+254700000000", delivery_areas: [{ name: "Central", delivery_fee: 10, currency: "KES" }],
};
const tick = () => new Promise((resolve) => setTimeout(resolve, 0));

test("cart updates quantity and blocks checkout for unavailable items", async (t) => {
  const { nodes, events } = install(t);
  const calls = [];
  t.mock.method(globalThis, "fetch", async (url, options) => {
    calls.push({ url: String(url), options });
    if (url.includes("cart.get_cart")) return response(cart);
    if (url.includes("cart.update_item")) return response({
      ...cart, items: [{ ...item, quantity: 3, available: false, available_quantity: 2 }], item_count: 3,
    });
    throw new Error(`Unexpected request: ${url}`);
  });
  await import(`../../intelligent_ordering/public/js/cart-page.js?cart=${Date.now()}`);
  await tick();
  assert.equal(nodes.get("#checkout-link").hidden, false);
  const controls = nodes.get("#cart-items").children[0].children.at(-1);
  controls.children[0].children[0].value = "3";
  await controls.children[1].listeners.click();
  await tick();
  const update = calls.find((call) => call.url.includes("cart.update_item"));
  assert.equal(update.options.body.get("quantity"), "3");
  assert.equal(nodes.get("#checkout-link").hidden, true);
  assert.equal(events.at(-1).detail, 3);
});

test("cart displays product images and removal persists the empty cart", async (t) => {
  const { nodes, events } = install(t);
  t.mock.method(globalThis, "fetch", async (url) => {
    if (url.includes("cart.get_cart")) return response({
      ...cart, items: [{ ...item, image: "/files/milk.jpg" }],
    });
    if (url.includes("cart.remove_item")) return response({ ...cart, items: [], item_count: 0, total: 0 });
    throw new Error(`Unexpected request: ${url}`);
  });
  await import(`../../intelligent_ordering/public/js/cart-page.js?remove=${Date.now()}`);
  await tick();
  const row = nodes.get("#cart-items").children[0];
  assert.equal(row.children[0].src, "/files/milk.jpg");
  assert.equal(row.children[0].alt, "Milk");
  await row.children.at(-1).children.at(-1).listeners.click();
  await tick();
  assert.equal(nodes.get("#cart-status").textContent, "Your cart is empty.");
  assert.equal(nodes.get("#checkout-link").hidden, true);
  assert.equal(events.at(-1).detail, 0);
});

test("checkout quotes server totals and recovers an interrupted submission", async (t) => {
  const { nodes, session, locations } = install(t);
  const calls = [];
  let recover = false;
  t.mock.method(globalThis, "fetch", async (url, options) => {
    calls.push({ url: String(url), options });
    if (url.includes("checkout.get_checkout_attempt")) return response({ order_name: recover ? "SO-1" : null });
    if (url.includes("checkout.get_checkout")) {
      return response(String(url).includes("delivery_area=")
        ? { ...checkout, delivery_fee: 10, currency: "KES", total: 110, delivery_quote: "quote-1" }
        : checkout);
    }
    if (url.includes("cart.get_cart")) return response(cart);
    if (url.includes("checkout.create_order")) return failed("Connection interrupted");
    throw new Error(`Unexpected request: ${url}`);
  });
  await import(`../../intelligent_ordering/public/js/checkout-page.js?first=${Date.now()}`);
  await tick();
  assert.equal(nodes.get("#checkout-submit").disabled, true);
  nodes.get("#checkout-area").value = "Central";
  await nodes.get("#checkout-area").listeners.change();
  assert.equal(nodes.get("#checkout-submit").disabled, false);
  assert.match(nodes.get("#checkout-total").textContent, /110/);
  await nodes.get("#checkout-form").listeners.submit({ preventDefault() {} });
  assert.match(nodes.get("#checkout-status").textContent, /could not be confirmed/);
  const create = calls.find((call) => call.url.includes("checkout.create_order"));
  assert.equal(create.options.body.get("delivery_quote"), "quote-1");
  assert.equal(create.options.body.get("cart_revision"), "revision-1");
  assert.equal(create.options.body.get("delivery_area"), "Central");
  assert.equal(session.get("smarto.checkout.pending-token.v1"), create.options.body.get("request_token"));
  recover = true;
  await import(`../../intelligent_ordering/public/js/checkout-page.js?reload=${Date.now()}`);
  await tick();
  assert.equal(locations.at(-1), "/order-confirmation/SO-1");
  assert.equal(session.get("smarto.checkout.pending-order.v1"), "SO-1");
  assert.equal(calls.filter((call) => call.url.includes("checkout.create_order")).length, 1);
});

test("guest checkout offers login without creating an order", async (t) => {
  const { nodes } = install(t);
  t.mock.method(globalThis, "fetch", async () => response({ requires_login: true }));
  await import(`../../intelligent_ordering/public/js/checkout-page.js?guest=${Date.now()}`);
  await tick();
  assert.equal(nodes.get("#checkout-login").hidden, false);
  assert.match(nodes.get("#checkout-status").textContent, /Sign in/);
});

test("retry uses the same checkout token and accepts an existing order", async (t) => {
  const { nodes, locations } = install(t);
  const tokens = [];
  t.mock.method(globalThis, "fetch", async (url, options) => {
    if (url.includes("cart.get_cart")) return response(cart);
    if (url.includes("checkout.get_checkout")) return response(String(url).includes("delivery_area=")
      ? { ...checkout, delivery_fee: 10, currency: "KES", total: 110, delivery_quote: "quote-1" }
      : checkout);
    if (url.includes("checkout.create_order")) {
      tokens.push(options.body.get("request_token"));
      return tokens.length === 1 ? failed("Connection interrupted")
        : response({ duplicate: true, order: { name: "SO-1" } });
    }
    throw new Error(`Unexpected request: ${url}`);
  });
  await import(`../../intelligent_ordering/public/js/checkout-page.js?retry=${Date.now()}`);
  await tick();
  nodes.get("#checkout-area").value = "Central";
  await nodes.get("#checkout-area").listeners.change();
  await nodes.get("#checkout-form").listeners.submit({ preventDefault() {} });
  nodes.get("#checkout-form").elements.phone.value = "+254711111111";
  await nodes.get("#checkout-form").listeners.submit({ preventDefault() {} });
  assert.equal(tokens.length, 1);
  assert.match(nodes.get("#checkout-feedback").textContent, /different details/);
  nodes.get("#checkout-form").elements.phone.value = "+254700000000";
  await nodes.get("#checkout-form").listeners.submit({ preventDefault() {} });
  assert.equal(tokens.length, 2);
  assert.equal(tokens[0], tokens[1]);
  assert.equal(locations.at(-1), "/order-confirmation/SO-1");
});

test("a definitive validation rejection allows a corrected new submission", async (t) => {
  const { nodes, locations } = install(t);
  const tokens = [];
  t.mock.method(globalThis, "fetch", async (url, options) => {
    if (url.includes("cart.get_cart")) return response(cart);
    if (url.includes("checkout.get_checkout")) return response(String(url).includes("delivery_area=")
      ? { ...checkout, delivery_fee: 10, currency: "KES", total: 110, delivery_quote: "quote-1" }
      : checkout);
    if (url.includes("checkout.create_order")) {
      tokens.push(options.body.get("request_token"));
      return tokens.length === 1
        ? { ok: false, status: 417, json: async () => ({ message: "Invalid phone" }) }
        : response({ order: { name: "SO-2" } });
    }
    throw new Error(`Unexpected request: ${url}`);
  });
  await import(`../../intelligent_ordering/public/js/checkout-page.js?rejected=${Date.now()}`);
  await tick();
  nodes.get("#checkout-area").value = "Central";
  await nodes.get("#checkout-area").listeners.change();
  await nodes.get("#checkout-form").listeners.submit({ preventDefault() {} });
  assert.match(nodes.get("#checkout-status").textContent, /rejected/);
  nodes.get("#checkout-form").elements.phone.value = "+254711111111";
  await nodes.get("#checkout-form").listeners.submit({ preventDefault() {} });
  assert.equal(tokens.length, 2);
  assert.notEqual(tokens[0], tokens[1]);
  assert.equal(locations.at(-1), "/order-confirmation/SO-2");
});

test("failed delivery quotes never enable order submission", async (t) => {
  const { nodes } = install(t);
  t.mock.method(globalThis, "fetch", async (url) => {
    if (url.includes("cart.get_cart")) return response(cart);
    if (String(url).includes("delivery_area=")) return failed("Delivery area unavailable");
    return response(checkout);
  });
  await import(`../../intelligent_ordering/public/js/checkout-page.js?quote=${Date.now()}`);
  await tick();
  nodes.get("#checkout-area").value = "Central";
  await nodes.get("#checkout-area").listeners.change();
  assert.equal(nodes.get("#checkout-submit").disabled, true);
  assert.match(nodes.get("#checkout-feedback").textContent, /Delivery area unavailable/);
});

test("confirmation shows only the server-returned order and clears its recovery state", async (t) => {
  const { nodes, session } = install(t);
  window.location.pathname = "/order-confirmation/SO-1";
  session.set("smarto.checkout.pending-token.v1", "token");
  session.set("smarto.checkout.pending-order.v1", "SO-1");
  t.mock.method(globalThis, "fetch", async (url) => {
    assert.match(String(url), /orders.get_my_order/);
    return response({
      name: "SO-1", status: "Pending", payment_status: "Unpaid",
      customer_name: "Customer", customer_phone: "123", delivery_address: "Road",
      items: [{ ...item, line_total: 100 }], subtotal: 100, total: 110,
      delivery_fee: 10, currency: "KES",
    });
  });
  await import(`../../intelligent_ordering/public/js/order-confirmation.js?order=${Date.now()}`);
  await tick();
  assert.equal(nodes.get("#order-detail").children[0].textContent, "Order SO-1");
  assert.equal(nodes.get("#order-detail").children[2].textContent, "Payment status: Unpaid");
  assert.equal(session.size, 0);
});

test("confirmation does not show details when the owner-scoped request fails", async (t) => {
  const { nodes } = install(t);
  window.location.pathname = "/order-confirmation/SO-2";
  t.mock.method(globalThis, "fetch", async () => failed("This order is unavailable."));
  await import(`../../intelligent_ordering/public/js/order-confirmation.js?denied=${Date.now()}`);
  await tick();
  assert.equal(nodes.get("#order-detail").children.length, 0);
  assert.match(nodes.get("#order-status").textContent, /unavailable/);
});

test("checkout fills a default saved address without submitting its owner", async (t) => {
  const { nodes } = install(t);
  t.mock.method(globalThis, "fetch", async (url) => response(url.includes("cart.get_cart") ? cart : {
    ...checkout, saved_addresses: [{
      name: "ADDR-1", address_label: "Home", address_line_1: "Saved Road", city: "Nairobi", is_default: 1,
    }],
  }));
  await import(`../../intelligent_ordering/public/js/checkout-page.js?address=${Date.now()}`);
  await tick();
  assert.equal(nodes.get("#checkout-address").value, "ADDR-1");
  assert.equal(nodes.get("#checkout-form").elements.address_line_1.value, "Saved Road");
});

test("private HTTP checkout uses secure random tokens and preserves same-submission retry checks", async (t) => {
  const { nodes } = install(t);
  crypto.randomUUID = undefined;
  crypto.subtle = undefined;
  crypto.getRandomValues = (bytes) => webcrypto.getRandomValues(bytes);
  const calls = [];
  t.mock.method(globalThis, "fetch", async (url, options) => {
    if (url.includes("cart.get_cart")) return response(cart);
    if (url.includes("checkout.create_order")) {
      calls.push(options.body);
      return failed("Connection interrupted");
    }
    return response({ ...checkout, delivery_fee: 10, currency: "KES", total: 110, delivery_quote: "quote-1" });
  });
  await import(`../../intelligent_ordering/public/js/checkout-page.js?http=${Date.now()}`);
  await tick();
  nodes.get("#checkout-area").value = "Central";
  await nodes.get("#checkout-area").listeners.change();
  await nodes.get("#checkout-form").listeners.submit({ preventDefault() {} });
  assert.match(calls[0].get("request_token"), /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
  await nodes.get("#checkout-form").listeners.submit({ preventDefault() {} });
  assert.equal(calls[0].get("request_token"), calls[1].get("request_token"));
  nodes.get("#checkout-form").elements.phone.value = "+254711111111";
  await nodes.get("#checkout-form").listeners.submit({ preventDefault() {} });
  assert.equal(calls.length, 2);
  assert.match(nodes.get("#checkout-feedback").textContent, /different details/);
});
