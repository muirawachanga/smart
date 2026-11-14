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

  nodes.get("#inventory-product-options").value = "SKU-1";
  nodes.get("#inventory-product-options").listeners.change();
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

const deliveryIds = [
  "delivery-feedback", "delivery-filters", "delivery-list", "delivery-detail",
  "delivery-manager", "delivery-ready-orders", "delivery-area-form",
  "delivery-previous", "delivery-next", "delivery-ready-previous", "delivery-ready-next",
  "delivery-workloads", "delivery-areas", "deliveries-link",
];

test("delivery workspace shows assigned deliveries using scoped APIs", async (t) => {
  const nodes = install(t, deliveryIds, "[data-delivery-page]", {});
  const calls = [];
  t.mock.method(globalThis, "fetch", async (url) => {
    calls.push(String(url));
    if (url.includes("deliveries.delivery_dashboard")) return response({ manager: false });
    if (url.includes("deliveries.list_deliveries")) {
      return response({ deliveries: [{
        name: "DEL-1", order: "SO-1", status: "Assigned",
        delivery_area: "Central", scheduled_delivery_date: "2026-11-15",
      }], has_more: false });
    }
    if (url.includes("deliveries.get_delivery")) return response({
      name: "DEL-1", order: "SO-1", status: "Assigned",
      customer_name: "Buyer", customer_phone: "254712345678",
      delivery_address: "Nairobi", delivery_area: "Central",
      currency: "KES", delivery_fee: 20, assigned_delivery_person: "driver@example.test",
      allowed_statuses: ["In Transit"], activities: [],
    });
    throw new Error(`Unexpected request: ${url}`);
  });
  await import(`../../intelligent_ordering/public/js/delivery-page.js?delivery=${Date.now()}`);
  await tick();
  assert.match(nodes.get("#delivery-list").children[0].textContent, /DEL-1/);
  nodes.get("#delivery-list").children[0].children.at(-1).listeners.click();
  await tick();
  assert.ok(calls.some((url) => url.includes("deliveries.get_delivery")));
  assert.ok(nodes.get("#delivery-detail").children.filter(Boolean)
    .some((child) => /Buyer/.test(child.textContent)), nodes.get("#delivery-feedback").textContent);
  assert.equal(nodes.get("#delivery-feedback").textContent, "");
});
