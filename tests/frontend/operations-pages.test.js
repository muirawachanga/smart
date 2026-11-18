import assert from "node:assert/strict";
import test from "node:test";

class Element {
  constructor(tag = "div") {
    this.tag = tag;
    this.children = [];
    this.listeners = {};
    this.dataset = {};
    this._textContent = "";
    this.value = "";
    this.hidden = false;
    this.disabled = false;
    this.elements = {};
    this.options = [];
  }
  get textContent() {
    return this._textContent + this.children.map((child) => child.textContent).join("");
  }
  set textContent(value) {
    this._textContent = String(value ?? "");
    this.children = [];
    if (this.tag === "select") this.options = [];
  }
  append(...nodes) {
    for (const node of nodes) {
      node.parent = this;
      if (this.tag === "label") node.label = this;
      this.children.push(node);
      if (this.tag === "select") this.options = this.children;
    }
  }
  prepend(...nodes) {
    this.children.unshift(...nodes);
  }
  replaceChildren(...nodes) {
    this.children = [];
    this.options = [];
    this.append(...nodes);
  }
  add(node) { this.append(node); }
  addEventListener(name, handler) { this.listeners[name] = handler; }
  setAttribute(name, value) { this[name] = value; }
  closest(selector) { return selector === "form" ? this.form : this.label; }
  querySelector(selector) { return this.queries?.[selector] || null; }
  querySelectorAll(selector) { return this.queriesAll?.[selector] || []; }
  reportValidity() { return true; }
  reset() {
    for (const field of Object.values(this.elements)) field.value = "";
  }
  scrollIntoView() {}
  cloneNode() {
    const clone = new Element(this.tag);
    clone.textContent = this.textContent;
    clone.value = this.value;
    clone.dataset = { ...this.dataset };
    return clone;
  }
}

class Select extends Element {
  constructor() {
    super("select");
    this.value = "";
  }
  replaceChildren(...nodes) {
    super.replaceChildren(...nodes);
    if (!this.options.some((option) => option.value === this.value)) {
      this.value = this.options[0]?.value || "";
    }
  }
}

class Option extends Element {
  constructor(label, value) {
    super("option");
    this.textContent = label;
    this.value = value;
    this.dataset = {};
  }
}

function install(t, ids, pageSelector, pageValue) {
  const nodes = new Map(ids.map((id) => [`#${id}`, new Element()]));
  for (const selector of [
    "#inventory-stock-filters", "#inventory-product-search",
    "#inventory-adjustment-form", "#inventory-return-form",
    "#inventory-movement-filters",
  ]) {
    const form = nodes.get(selector);
    if (!form) continue;
    form.elements = {
      search: new Element(),
      product: new Select(),
      warehouse: new Select(),
      availability: new Select(),
      transaction_type: new Select(),
      direction: new Select(),
      quantity: new Element(),
      remarks: new Element(),
      order_name: new Element(),
    };
    for (const field of Object.values(form.elements)) field.form = form;
  }
  if (nodes.has("#inventory-stock-filters")) {
    nodes.get("#inventory-stock-filters").querySelectorAll = () => [];
  }
  if (nodes.has("#inventory-movement-filters")) {
    nodes.get("#inventory-movement-filters").querySelectorAll = () => [
      nodes.get("#inventory-movement-filters").elements.warehouse,
    ];
  }
  for (const selector of ["#inventory-adjustment-form", "#inventory-return-form"]) {
    const form = nodes.get(selector);
    if (form) form.queries = { 'button[type="submit"]': new Element("button") };
  }
  if (nodes.has("#delivery-area-form")) {
    nodes.get("#delivery-area-form").elements = Object.fromEntries(
      ["area_name", "currency", "delivery_fee", "enabled"].map((key) => [key, new Element()]),
    );
  }
  if (nodes.has("#delivery-filters")) {
    nodes.get("#delivery-filters").elements = {
      search: new Element(), status: new Select(), area: new Element(),
    };
  }
  const original = {};
  const setGlobal = (name, value) => {
    original[name] = Object.getOwnPropertyDescriptor(globalThis, name);
    Object.defineProperty(globalThis, name, { value, writable: true, configurable: true });
  };
  setGlobal("document", {
    querySelector: (selector) => selector === pageSelector
      ? { dataset: pageValue } : nodes.get(selector),
    createElement: (tag) => tag === "select" ? new Select() : new Element(tag),
  });
  setGlobal("window", { location: { hash: "" } });
  setGlobal("Option", Option);
  setGlobal("FormData", class {
    constructor(form) { this.form = form; }
    *[Symbol.iterator]() {
      for (const [key, field] of Object.entries(this.form.elements)) {
        yield [key, field.value];
      }
    }
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
const tick = () => new Promise((resolve) => setTimeout(resolve, 0));
const inventoryIds = [
  "inventory-feedback", "inventory-metrics", "inventory-stock-filters", "inventory-stock-list",
  "inventory-stock-previous", "inventory-stock-next", "inventory-stock-page",
  "inventory-product-search", "inventory-product-options", "inventory-product-next",
  "inventory-adjustment-form", "inventory-return-form", "inventory-movement-filters",
  "inventory-adjustment-feedback", "inventory-return-feedback",
  "inventory-movements", "inventory-movements-previous", "inventory-movements-next",
  "inventory-movements-page",
];

test("inventory page loads real balances and posts receipt through inventory API", async (t) => {
  const nodes = install(t, inventoryIds, "[data-inventory-page]", {});
  const calls = [];
  const product = { name: "SKU-1", sku: "SKU-1", product_name: "Milk", enabled: 1 };
  const warehouse = { name: "WH-1", warehouse_name: "Main warehouse" };
  t.mock.method(globalThis, "fetch", async (url, options) => {
    calls.push({ url: String(url), options });
    if (url.includes("inventory.get_dashboard")) {
      return response({ summary: {
        total_products: 1, total_stock: 8, available_stock: 7,
        reserved_stock: 1, low_stock_products: 1, out_of_stock_products: 0,
      }, low_stock_threshold: 5 });
    }
    if (url.includes("inventory.list_stock")) {
      return response({ stock: [{
        product: "SKU-1", sku: "SKU-1", product_name: "Milk",
        warehouse: "WH-1", warehouse_name: "Main warehouse",
        quantity_on_hand: 8, reserved_quantity: 1, available_quantity: 7,
      }], warehouses: [warehouse], has_more: false });
    }
    if (url.includes("inventory.list_movements")) return response({ movements: [], has_more: false });
    if (url.includes("inventory.list_product_options")) {
      return response({ products: [product], warehouses: [warehouse], has_more: false });
    }
    if (url.includes("inventory.adjust_stock")) return response({ name: "SLE-1" });
    if (url.includes("inventory.record_order_return")) return response({ name: "SLE-2" });
    throw new Error(`Unexpected request: ${url}`);
  });
  await import(`../../intelligent_ordering/public/js/inventory-page.js?inventory=${Date.now()}`);
  await tick();
  assert.equal(nodes.get("#inventory-metrics").children.length, 6);
  assert.match(nodes.get("#inventory-stock-list").children[0].textContent, /Milk/);

  nodes.get("#inventory-product-search").elements.search.value = "Milk";
  nodes.get("#inventory-product-search").listeners.submit({ preventDefault() {} });
  await tick();
  nodes.get("#inventory-product-options").value = "SKU-1";
  nodes.get("#inventory-product-options").listeners.change();
  const form = nodes.get("#inventory-adjustment-form");
  form.elements.warehouse.value = "WH-1";
  form.elements.transaction_type.value = "Receipt";
  form.elements.quantity.value = "3";
  form.listeners.submit({ preventDefault() {} });
  await tick();
  const receipt = calls.find((call) => call.url.includes("inventory.adjust_stock"));
  assert.equal(receipt.options.body.get("product"), "SKU-1");
  assert.equal(receipt.options.body.get("warehouse"), "WH-1");
  assert.equal(receipt.options.body.get("quantity"), "3");
  assert.match(nodes.get("#inventory-feedback").textContent, /Stock movement recorded/);

  // The shared product picker stays selected after the first submission.
  form.elements.warehouse.value = "WH-1";
  form.elements.transaction_type.value = "Receipt";
  form.elements.quantity.value = "2";
  await form.listeners.submit({ preventDefault() {} });
  assert.equal(calls.filter((call) => call.url.includes("inventory.adjust_stock")).length, 2);
  assert.equal(calls.filter((call) => call.url.includes("inventory.adjust_stock")).at(-1)
    .options.body.get("product"), "SKU-1");
  const returnForm = nodes.get("#inventory-return-form");
  returnForm.elements.order_name.value = "SO-1";
  returnForm.elements.warehouse.value = "WH-1";
  returnForm.elements.quantity.value = "1";
  returnForm.listeners.submit({ preventDefault() {} });
  await tick();
  const orderReturn = calls.find((call) => call.url.includes("inventory.record_order_return"));
  assert.equal(orderReturn.options.body.get("order_name"), "SO-1");
  assert.equal(orderReturn.options.body.get("product"), "SKU-1");
  assert.match(nodes.get("#inventory-feedback").textContent, /stock return recorded/);
});

function mockInventoryReads(url) {
  if (url.includes("inventory.get_dashboard")) {
    return response({ summary: {}, low_stock_threshold: 5 });
  }
  if (url.includes("inventory.list_stock")) {
    return response({ stock: [], warehouses: [], has_more: false });
  }
  if (url.includes("inventory.list_movements")) {
    return response({ movements: [], has_more: false });
  }
  throw new Error(`Unexpected request: ${url}`);
}

test("stock form reports missing product and server rejection beside the button", async (t) => {
  const nodes = install(t, inventoryIds, "[data-inventory-page]", {});
  let posted = 0;
  t.mock.method(globalThis, "fetch", async (url) => {
    if (url.includes("inventory.adjust_stock")) {
      posted += 1;
      return { ok: false, status: 417, json: async () => ({
        message: "Opening stock can only be recorded once.",
      }) };
    }
    return mockInventoryReads(url);
  });
  await import(`../../intelligent_ordering/public/js/inventory-page.js?validation=${Date.now()}`);
  await tick();
  const form = nodes.get("#inventory-adjustment-form");
  await form.listeners.submit({ preventDefault() {} });
  assert.equal(posted, 0);
  assert.match(nodes.get("#inventory-adjustment-feedback").textContent, /Select a product/);
  nodes.get("#inventory-product-options").value = "SKU-1";
  form.elements.warehouse.value = "WH-1";
  form.elements.transaction_type.value = "Opening";
  form.elements.quantity.value = "3";
  await form.listeners.submit({ preventDefault() {} });
  assert.equal(posted, 1);
  assert.match(nodes.get("#inventory-adjustment-feedback").textContent, /Opening stock can only/);
  assert.equal(form.elements.quantity.value, "3");
  assert.equal(form.querySelector('button[type="submit"]').disabled, false);
});

test("successful stock save with failed refresh is not reported as a failed movement", async (t) => {
  const nodes = install(t, inventoryIds, "[data-inventory-page]", {});
  let saved = false;
  t.mock.method(globalThis, "fetch", async (url) => {
    if (url.includes("inventory.adjust_stock")) {
      saved = true;
      return response({ name: "SLE-1" });
    }
    if (saved && url.includes("inventory.list_stock")) {
      throw new Error("Connection lost");
    }
    return mockInventoryReads(url);
  });
  await import(`../../intelligent_ordering/public/js/inventory-page.js?refresh=${Date.now()}`);
  await tick();
  nodes.get("#inventory-product-options").value = "SKU-1";
  const form = nodes.get("#inventory-adjustment-form");
  form.elements.warehouse.value = "WH-1";
  form.elements.transaction_type.value = "Receipt";
  form.elements.quantity.value = "3";
  await form.listeners.submit({ preventDefault() {} });
  const message = nodes.get("#inventory-adjustment-feedback").textContent;
  assert.match(message, /Stock movement recorded.*Display refresh failed/);
  assert.match(message, /Reload the page/);
  assert.doesNotMatch(message, /Stock movement failed/);
  assert.equal(nodes.get("#inventory-product-options").value, "SKU-1");
});

const deliveryIds = [
  "delivery-feedback", "delivery-filters", "delivery-list", "delivery-detail",
  "delivery-manager", "delivery-ready-orders", "delivery-area-form",
  "delivery-previous", "delivery-next", "delivery-ready-previous", "delivery-ready-next",
  "delivery-workloads", "delivery-areas", "deliveries-link", "delivery-metrics",
  "delivery-delayed", "delivery-performance", "delivery-area-management",
];
const optimizationIds = [
  "delivery-location-share", "delivery-share-location", "delivery-clear-location",
  "delivery-my-route", "delivery-my-route-results", "delivery-optimization-manager",
  "delivery-plan-form", "delivery-plan-results",
];
const offerIds = [
  "delivery-offers-section", "delivery-offers-status", "delivery-offers-list",
  "delivery-online", "delivery-offline", "delivery-escalations-section", "delivery-escalations",
];

test("dedicated rider page uses only rider-scoped delivery APIs", async (t) => {
  const ids = [
    "delivery-feedback", "delivery-filters", "delivery-list", "delivery-detail",
    "delivery-previous", "delivery-next", "delivery-metrics", "delivery-delayed",
    ...offerIds, ...optimizationIds.slice(0, 5),
  ];
  const nodes = install(t, ids, "[data-rider-page]", {});
  const calls = [];
  t.mock.method(globalThis, "fetch", async (url) => {
    calls.push(String(url));
    if (url.includes("deliveries.my_delivery_dashboard")) return response({
      manager: false, rider: true, summary: { total: 1 }, delayed_deliveries: 0,
    });
    if (url.includes("deliveries.delivery_offers")) return response({ online: false, busy: false, offers: [] });
    if (url.includes("deliveries.my_deliveries")) return response({
      deliveries: [{
        name: "DEL-1", order: "SO-1", status: "Accepted", delivery_area: "Central",
        customer_name: "Customer", customer_phone: "123", delivery_address: "Street",
      }], has_more: false,
    });
    if (url.includes("deliveries.get_my_delivery")) return response({
      name: "DEL-1", order: "SO-1", status: "Accepted", allowed_statuses: ["Preparing"], activities: [],
    });
    throw new Error(`Unexpected request: ${url}`);
  });
  await import(`../../intelligent_ordering/public/js/delivery-page.js?rider-page=${Date.now()}`);
  await tick();
  assert.equal(nodes.get("#delivery-offers-section").hidden, false);
  assert.equal(nodes.get("#delivery-location-share").hidden, false);
  assert.match(nodes.get("#delivery-list").textContent, /SO-1/);
  nodes.get("#delivery-list").children[0].children.find((child) => child.textContent === "View delivery").listeners.click();
  await tick();
  assert.match(nodes.get("#delivery-detail").textContent, /Accepted/);
  assert.ok(calls.some((url) => url.includes("deliveries.get_my_delivery")));
  assert.ok(!calls.some((url) => url.includes("deliveries.delivery_dashboard")));
  assert.ok(!calls.some((url) => url.includes("deliveries.list_deliveries")));
});

test("rider goes online and accepts a broadcast offer on the rider page", async (t) => {
  const nodes = install(t, [
    "delivery-feedback", "delivery-filters", "delivery-list", "delivery-detail",
    "delivery-previous", "delivery-next", "delivery-metrics", "delivery-delayed", ...offerIds,
  ], "[data-rider-page]", {});
  const calls = [];
  let online = false;
  let accepted = false;
  t.mock.method(globalThis, "fetch", async (url, options = {}) => {
    calls.push({ url: String(url), options });
    if (url.includes("deliveries.my_delivery_dashboard")) return response({
      manager: false, rider: true, summary: {}, delayed_deliveries: 0,
    });
    if (url.includes("deliveries.my_deliveries")) return response({ deliveries: [], has_more: false });
    if (url.includes("deliveries.delivery_offers")) return response({
      online, busy: accepted, offers: online && !accepted
        ? [{ name: "DEL-1", order: "SO-1", delivery_area: "Central", round_number: 1, expires_at: "12:05" }]
        : [],
    });
    if (url.includes("deliveries.set_offer_presence")) {
      online = options.body.get("online") === "1";
      return response({ online });
    }
    if (url.includes("deliveries.accept_delivery_offer")) {
      accepted = true;
      return response({ name: "DEL-1" });
    }
    if (url.includes("deliveries.get_my_delivery")) return response({
      name: "DEL-1", order: "SO-1", status: "Accepted", allowed_statuses: [], activities: [],
    });
    throw new Error(`Unexpected request: ${url}`);
  });
  await import(`../../intelligent_ordering/public/js/delivery-page.js?offers=${Date.now()}`);
  await tick();
  assert.match(nodes.get("#delivery-offers-status").textContent, /Offline/);
  nodes.get("#delivery-online").listeners.click();
  await tick();
  const offer = nodes.get("#delivery-offers-list").children[0];
  assert.match(offer.textContent, /Central/);
  offer.children.find((child) => child.textContent === "Accept offer").listeners.click();
  await tick();
  const acceptance = calls.find((call) => call.url.includes("accept_delivery_offer"));
  assert.equal(acceptance.options.body.get("delivery_name"), "DEL-1");
  assert.equal(acceptance.options.body.get("round_number"), "1");
  assert.match(nodes.get("#delivery-offers-status").textContent, /unavailable/);
  assert.match(nodes.get("#delivery-detail").textContent, /Accepted/);
});

function installOptimization(t) {
  const nodes = install(t, [...deliveryIds, ...optimizationIds], "[data-delivery-page]", {});
  const form = nodes.get("#delivery-plan-form");
  form.elements = {
    delivery_name: new Element(), scheduled_delivery_date: new Element(),
    radius_km: new Element(), max_stops: new Element(),
  };
  form.queries = { 'button[type="submit"]': new Element("button") };
  return nodes;
}

test("rider explicitly shares, uses, and clears a location", async (t) => {
  const nodes = installOptimization(t);
  const calls = [];
  window.navigator = { geolocation: {
    getCurrentPosition: (resolve) => resolve({ coords: { latitude: -1.2, longitude: 36.8, accuracy: 10 } }),
  } };
  t.mock.method(globalThis, "fetch", async (url, options = {}) => {
    calls.push({ url: String(url), options });
    if (url.includes("deliveries.delivery_dashboard")) return response({ manager: false, summary: {}, delayed_deliveries: 0 });
    if (url.includes("deliveries.list_deliveries")) return response({ deliveries: [], has_more: false });
    if (url.includes("deliveries.share_rider_location")) return response({ shared_at: "now" });
    if (url.includes("deliveries.my_delivery_route")) return response({
      route: [{ name: "D1", order: "SO-1", status: "Accepted", delivery_address: "Nairobi", distance_km: 1 }],
      total_distance_km: 1, missing_coordinates: 1,
    });
    if (url.includes("deliveries.clear_rider_location")) return response({ shared: false });
    throw new Error(`Unexpected request: ${url}`);
  });
  await import(`../../intelligent_ordering/public/js/delivery-page.js?gps=${Date.now()}`);
  await tick();
  assert.equal(nodes.get("#delivery-location-share").hidden, false);
  assert.equal(calls.filter((call) => call.url.includes("share_rider_location")).length, 0);
  await nodes.get("#delivery-share-location").listeners.click();
  const share = calls.find((call) => call.url.includes("share_rider_location"));
  assert.equal(share.options.body.get("latitude"), "-1.2");
  await nodes.get("#delivery-my-route").listeners.click();
  assert.match(nodes.get("#delivery-my-route-results").textContent, /SO-1/);
  assert.match(nodes.get("#delivery-my-route-results").textContent, /1 assigned deliveries have no coordinates/);
  await nodes.get("#delivery-clear-location").listeners.click();
  assert.equal(nodes.get("#delivery-my-route-results").textContent, "");
  assert.ok(calls.some((call) => call.url.includes("clear_rider_location")));
});

test("manager reviews and assigns an optimized group", async (t) => {
  const nodes = installOptimization(t);
  const calls = [];
  t.mock.method(globalThis, "fetch", async (url, options = {}) => {
    calls.push({ url: String(url), options });
    if (url.includes("deliveries.delivery_dashboard")) return response({
      manager: true, summary: {}, delayed_deliveries: 0, available_riders: 1,
      can_manage_areas: false, personnel: [], personnel_performance: [],
      ready_orders: [], areas: [], has_more: false,
    });
    if (url.includes("deliveries.list_deliveries")) return response({ deliveries: [], has_more: false });
    if (url.includes("deliveries.suggest_delivery_group")) return response({
      rider: "rider@example.test", rider_name: "Rider", location_updated_at: "today",
      accuracy_meters: 10, total_distance_km: 2, plan_token: "plan-token",
      route: [
        { name: "D1", order: "SO-1", status: "Awaiting Assignment", delivery_address: "First", distance_km: 1 },
        { name: "D2", order: "SO-2", status: "Awaiting Assignment", delivery_address: "Second", distance_km: 1 },
      ],
    });
    if (url.includes("deliveries.assign_delivery_group")) return response({ deliveries: ["D1", "D2"] });
    throw new Error(`Unexpected request: ${url}`);
  });
  await import(`../../intelligent_ordering/public/js/delivery-page.js?planning=${Date.now()}`);
  await tick();
  assert.equal(nodes.get("#delivery-optimization-manager").hidden, false);
  const form = nodes.get("#delivery-plan-form");
  form.elements.delivery_name.value = "D1";
  form.elements.scheduled_delivery_date.value = "2026-11-17";
  form.elements.radius_km.value = "5";
  form.elements.max_stops.value = "5";
  form.listeners.submit({ preventDefault() {} });
  await tick();
  const plan = nodes.get("#delivery-plan-results");
  assert.match(plan.textContent, /Suggested rider: Rider/);
  assert.match(plan.textContent, /not a road route/);
  assert.ok(!calls.some((call) => call.url.includes("assign_delivery_group")));
  await plan.children.find((child) => child.textContent === "Assign this group").listeners.click();
  const assigned = calls.find((call) => call.url.includes("assign_delivery_group"));
  assert.equal(assigned.options.body.get("delivery_names"), '["D1","D2"]');
  assert.equal(assigned.options.body.get("scheduled_delivery_date"), "2026-11-17");
  assert.equal(assigned.options.body.get("plan_token"), "plan-token");
  assert.match(nodes.get("#delivery-feedback").textContent, /rider must accept each delivery/);
});

test("manager saves coordinates against the existing delivery", async (t) => {
  const nodes = installOptimization(t);
  const calls = [];
  t.mock.method(globalThis, "fetch", async (url, options = {}) => {
    calls.push({ url: String(url), options });
    if (url.includes("deliveries.delivery_dashboard")) return response({
      manager: true, summary: {}, delayed_deliveries: 0, available_riders: 1,
      can_manage_areas: false, personnel: [], personnel_performance: [],
      ready_orders: [], areas: [], has_more: false,
    });
    if (url.includes("deliveries.list_deliveries")) return response({
      deliveries: [{ name: "D1", order: "SO-1", status: "Awaiting Assignment", delivery_area: "Central" }],
      has_more: false,
    });
    if (url.includes("deliveries.get_delivery")) return response({
      name: "D1", order: "SO-1", status: "Awaiting Assignment", delivery_area: "Central",
      allowed_statuses: [], activities: [],
    });
    if (url.includes("deliveries.set_delivery_coordinates")) return response({ name: "D1" });
    throw new Error(`Unexpected request: ${url}`);
  });
  await import(`../../intelligent_ordering/public/js/delivery-page.js?coordinates=${Date.now()}`);
  await tick();
  nodes.get("#delivery-list").children[0].children.find((child) => child.textContent === "View delivery").listeners.click();
  await tick();
  const form = nodes.get("#delivery-detail").children.find(
    (child) => child.tag === "form" && child.textContent.includes("Set delivery coordinates"),
  );
  form.children[1].children[0].value = "-1.28";
  form.children[2].children[0].value = "36.82";
  form.listeners.submit({ preventDefault() {} });
  await tick();
  const saved = calls.find((call) => call.url.includes("set_delivery_coordinates"));
  assert.equal(saved.options.body.get("delivery_name"), "D1");
  assert.equal(saved.options.body.get("latitude"), "-1.28");
  assert.equal(saved.options.body.get("longitude"), "36.82");
  assert.match(nodes.get("#delivery-feedback").textContent, /coordinates saved/);
});

test("delivery workspace shows assigned details and accepts rider assignments", async (t) => {
  const nodes = install(t, deliveryIds, "[data-delivery-page]", {});
  const calls = [];
  let status = "Assigned";
  t.mock.method(globalThis, "fetch", async (url) => {
    calls.push(String(url));
    if (url.includes("deliveries.delivery_dashboard")) return response({
      manager: false, summary: { total: 1, pending: 1, accepted: 0, picked_up: 0 },
      delayed_deliveries: 2,
    });
    if (url.includes("deliveries.list_deliveries")) {
      return response({ deliveries: [{
        name: "DEL-1", order: "SO-1", status,
        delivery_area: "Central", scheduled_delivery_date: "2026-11-15",
      }], has_more: false });
    }
    if (url.includes("deliveries.get_delivery")) return response({
      name: "DEL-1", order: "SO-1", status,
      customer_name: "Buyer", customer_phone: "254712345678",
      delivery_address: "Nairobi", delivery_area: "Central",
      currency: "KES", delivery_fee: 20, assigned_delivery_person: "driver@example.test",
      payment_status: "Paid", assignment_date: "2026-11-14",
      items: [{ product_name_snapshot: "Milk", product_sku_snapshot: "SKU-1", quantity: 2 }],
      allowed_statuses: status === "Assigned" ? ["Accepted"] : ["Preparing"], activities: [],
    });
    if (url.includes("deliveries.update_delivery")) {
      status = "Accepted";
      return response({ name: "DEL-1" });
    }
    throw new Error(`Unexpected request: ${url}`);
  });
  await import(`../../intelligent_ordering/public/js/delivery-page.js?delivery=${Date.now()}`);
  await tick();
  assert.equal(nodes.get("#delivery-metrics").children.length, 4);
  assert.match(nodes.get("#delivery-delayed").textContent, /2 delayed deliveries/);
  assert.match(nodes.get("#delivery-list").children[0].textContent, /DEL-1/);
  nodes.get("#delivery-list").children[0].children.at(-1).listeners.click();
  await tick();
  assert.ok(calls.some((url) => url.includes("deliveries.get_delivery")));
  assert.ok(nodes.get("#delivery-detail").children.filter(Boolean)
    .some((child) => /Buyer/.test(child.textContent)), nodes.get("#delivery-feedback").textContent);
  assert.ok(nodes.get("#delivery-detail").children.filter(Boolean)
    .some((child) => /SKU-1/.test(child.textContent)));
  nodes.get("#delivery-detail").children.find((child) => child.textContent === "Accept delivery")
    .listeners.click();
  await tick();
  assert.ok(calls.some((url) => url.includes("deliveries.update_delivery")));
  assert.ok(nodes.get("#delivery-detail").children.some((child) => /Accepted/.test(child.textContent)));
  assert.equal(nodes.get("#delivery-feedback").textContent, "");
});

test("delivery manager sees performance and routing areas without rate editing", async (t) => {
  const nodes = install(t, deliveryIds, "[data-delivery-page]", {});
  t.mock.method(globalThis, "fetch", async (url) => {
    if (url.includes("deliveries.delivery_dashboard")) return response({
      manager: true, summary: { total: 4, unassigned: 1, assigned: 2, completed: 1 },
      delayed_deliveries: 1, available_riders: 1, can_manage_areas: false,
      personnel: [{ name: "rider@example.test", full_name: "Rider", workload: 2 }],
      personnel_performance: [{ rider: "rider@example.test", completed: 3, failed: 1, total: 4 }],
      ready_orders: [], areas: [{ name: "Central", currency: "KES", delivery_fee: 20, enabled: 1 }], has_more: false,
    });
    if (url.includes("deliveries.list_deliveries")) return response({ deliveries: [], has_more: false });
    throw new Error(`Unexpected request: ${url}`);
  });
  await import(`../../intelligent_ordering/public/js/delivery-page.js?manager=${Date.now()}`);
  await tick();
  assert.equal(nodes.get("#delivery-area-management").hidden, false);
  assert.equal(nodes.get("#delivery-area-form").hidden, true);
  assert.equal(nodes.get("#delivery-areas").children[0].children.length, 1);
  assert.match(nodes.get("#delivery-areas").textContent, /Central/);
  assert.match(nodes.get("#delivery-performance").textContent, /3 completed/);
  assert.match(nodes.get("#delivery-performance").textContent, /75\.0% completion/);
  assert.ok(nodes.get("#delivery-metrics").children.some((item) => /Total deliveries4/.test(item.textContent)));
});

test("dedicated delivery area workspace loads directly and saves the selected rate", async (t) => {
  const nodes = install(t, ["areas-form", "areas-status", "areas-error", "areas-list", "areas-new", "areas-heading"]);
  const form = nodes.get("#areas-form");
  form.elements = Object.fromEntries(
    ["area_name", "currency", "delivery_fee", "enabled"].map((key) => [key, new Element()]),
  );
  form.queries = { 'button[type="submit"]': new Element("button") };
  const calls = [];
  t.mock.method(globalThis, "fetch", async (url, options = {}) => {
    calls.push({ url, body: options.body });
    if (url.includes("save_delivery_area")) return response({});
    assert.match(url, /list_delivery_areas/);
    return response({ can_create: true, can_write: true, can_delete: true,
      areas: [{ name: "Central", currency: "KES", delivery_fee: 20, enabled: 1, modified: "version-1" }] });
  });
  await import(`../../intelligent_ordering/public/js/delivery-areas.js?direct=${Date.now()}`);
  await tick();
  assert.match(nodes.get("#areas-list").textContent, /Central/);
  nodes.get("#areas-list").children[0].children[2].listeners.click();
  assert.equal(form.elements.area_name.readOnly, true);
  assert.equal(form.hidden, false);
  form.elements.delivery_fee.value = "45";
  form.listeners.submit({ preventDefault() {} });
  await tick();
  const save = calls.find((call) => call.url.includes("save_delivery_area"));
  assert.equal(save.body.get("modified"), "version-1");
  assert.equal(save.body.get("delivery_fee"), "45");
  assert.match(nodes.get("#areas-status").textContent, /saved/);
  nodes.get("#areas-new").listeners.click();
  assert.equal(form.elements.area_name.readOnly, false);
  assert.equal(form.elements.currency.value, "KES");
});

test("dedicated area workspace does not expose editing or stale data after denied loading", async (t) => {
  const nodes = install(t, ["areas-form", "areas-status", "areas-error", "areas-list", "areas-new", "areas-heading"]);
  nodes.get("#areas-form").queries = { 'button[type="submit"]': new Element("button") };
  t.mock.method(globalThis, "fetch", async () => ({
    ok: false, status: 403, json: async () => ({}),
  }));
  await import(`../../intelligent_ordering/public/js/delivery-areas.js?denied=${Date.now()}`);
  await tick();
  assert.equal(nodes.get("#areas-form").hidden, true);
  assert.equal(nodes.get("#areas-new").hidden, true);
  assert.equal(nodes.get("#areas-list").children.length, 0);
  assert.match(nodes.get("#areas-error").textContent, /permission/);
});

test("authorized area editing uses loaded version and deletion preserves rejected history", async (t) => {
  const nodes = install(t, deliveryIds, "[data-delivery-page]", {});
  window.confirm = () => true;
  const form = nodes.get("#delivery-area-form");
  form.queries = { 'button[type="submit"]': new Element("button") };
  const calls = [];
  let deleted = false;
  let rejectDelete = true;
  t.mock.method(globalThis, "fetch", async (url, options = {}) => {
    if (url.includes("deliveries.delivery_dashboard")) return response({
      manager: true, summary: {}, delayed_deliveries: 0, available_riders: 0,
      can_manage_areas: true, can_delete_areas: true, personnel: [],
      personnel_performance: [], ready_orders: [], has_more: false,
      areas: deleted ? [] : [{ name: "Central", currency: "KES", delivery_fee: 20,
        enabled: 1, modified: "version-1" }],
    });
    if (url.includes("deliveries.list_deliveries")) return response({ deliveries: [], has_more: false });
    calls.push({ url, body: options.body });
    if (url.includes("delete_delivery_area")) {
      if (rejectDelete) return { ok: false, status: 417, json: async () => ({ message: "Disable it instead." }) };
      deleted = true;
      return response({ message: "Unused delivery area deleted." });
    }
    return response({});
  });
  await import(`../../intelligent_ordering/public/js/delivery-page.js?areas=${Date.now()}`);
  await tick();
  nodes.get("#delivery-areas").children[0].children[1].listeners.click();
  assert.equal(form.elements.area_name.readOnly, true);
  form.elements.delivery_fee.value = "35";
  form.listeners.submit({ preventDefault() {} });
  await tick();
  assert.equal(calls[0].body.get("modified"), "version-1");
  assert.equal(calls[0].body.get("delivery_fee"), "35");
  assert.equal(form.elements.area_name.readOnly, false);
  nodes.get("#delivery-areas").children[0].children[2].listeners.click();
  await tick();
  assert.match(nodes.get("#delivery-feedback").textContent, /Disable it instead/);
  assert.equal(nodes.get("#delivery-areas").children.length, 1);
  rejectDelete = false;
  nodes.get("#delivery-areas").children[0].children[2].listeners.click();
  await tick();
  assert.equal(nodes.get("#delivery-areas").children.length, 0);
  assert.match(nodes.get("#delivery-feedback").textContent, /deleted/);
});

test("rider rejection requires a reason and returns the assignment to the queue", async (t) => {
  const nodes = install(t, deliveryIds, "[data-delivery-page]", {});
  const calls = [];
  let assigned = true;
  t.mock.method(globalThis, "fetch", async (url, options = {}) => {
    calls.push({ url: String(url), options });
    if (url.includes("deliveries.delivery_dashboard")) return response({
      manager: false, summary: {}, delayed_deliveries: 0,
    });
    if (url.includes("deliveries.list_deliveries")) return response({
      deliveries: assigned ? [{
        name: "DEL-1", order: "SO-1", status: "Assigned",
        delivery_area: "Central", scheduled_delivery_date: "2026-11-15",
      }] : [], has_more: false,
    });
    if (url.includes("deliveries.get_delivery")) return response({
      name: "DEL-1", order: "SO-1", status: "Assigned",
      customer_name: "Buyer", customer_phone: "254712345678",
      delivery_address: "Nairobi", delivery_area: "Central",
      currency: "KES", delivery_fee: 20, assigned_delivery_person: "driver@example.test",
      allowed_statuses: ["Accepted"], activities: [],
    });
    if (url.includes("deliveries.reject_delivery")) {
      assigned = false;
      return response({ name: "DEL-1" });
    }
    throw new Error(`Unexpected request: ${url}`);
  });
  await import(`../../intelligent_ordering/public/js/delivery-page.js?reject=${Date.now()}`);
  await tick();
  nodes.get("#delivery-list").children[0].children.at(-1).listeners.click();
  await tick();
  const form = nodes.get("#delivery-detail").children.find((child) => child.tag === "form");
  const reason = form.children[0].children[0];
  reason.value = "Rider unavailable";
  await form.listeners.submit({ preventDefault() {} });
  await tick();
  const rejection = calls.find((call) => call.url.includes("deliveries.reject_delivery"));
  assert.equal(new URLSearchParams(rejection.options.body).get("reason"), "Rider unavailable");
  assert.equal(nodes.get("#delivery-list").children[0].textContent, "No matching deliveries.");
});
