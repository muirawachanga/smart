import assert from "node:assert/strict";
import test from "node:test";

class Node {
  constructor(tag = "div") {
    this.tag = tag;
    this.children = [];
    this.listeners = {};
    this.value = "";
    this.textContent = "";
    this.hidden = false;
    this.disabled = false;
  }
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren(...nodes) { this.children = nodes; }
  add(node) { this.children.push(node); }
  setAttribute(name, value) { this[name] = value; }
  addEventListener(name, handler) { this.listeners[name] = handler; }
}

function installPage(t, kind, search = "", pathname = "/products") {
  function setGlobal(name, value) {
    const original = Object.getOwnPropertyDescriptor(globalThis, name);
    Object.defineProperty(globalThis, name, { value, configurable: true, writable: true });
    t.after(() => {
      if (original) Object.defineProperty(globalThis, name, original);
      else delete globalThis[name];
    });
  }
  const nodes = new Map();
  for (const id of [
    "catalog-form", "catalog-status", "catalog-products", "catalog-pagination",
    "catalog-previous", "catalog-next", "catalog-page", "cart-feedback",
    "product-status", "product-detail",
  ]) nodes.set(`#${id}`, new Node());
  const form = nodes.get("#catalog-form");
  form.elements = { search: new Node(), category: new Node(), sort: new Node() };
  const storage = new Map();
  const events = [];
  setGlobal("document", {
    querySelector: (selector) => selector === "[data-catalog-page]"
      ? { dataset: { catalogPage: kind } } : nodes.get(selector),
    createElement: (tag) => new Node(tag),
    dispatchEvent: (event) => events.push(event),
  });
  setGlobal("window", { location: { pathname, search }, frappe: {} });
  setGlobal("history", { replaceState() {} });
  setGlobal("localStorage", {
    getItem: (key) => storage.get(key) ?? null,
    setItem: (key, value) => storage.set(key, value),
    removeItem: (key) => storage.delete(key),
  });
  setGlobal("Option", class extends Node {
    constructor(label, value) { super("option"); this.textContent = label; this.value = value; }
  });
  setGlobal("CustomEvent", class {
    constructor(type, options) { this.type = type; this.detail = options.detail; }
  });
  return { nodes, storage, events };
}

function response(message) {
  return { ok: true, json: async () => ({ message }) };
}

const product = {
  name: "SKU/1", sku: "SKU/1", product_name: "<Milk>", category: "Drinks",
  price: 12, currency: "KES", available_quantity: 3,
};

test("catalog loads filters and adds a real product to the persisted guest cart", async (t) => {
  const { nodes, storage, events } = installPage(t, "products", "?category=Drinks");
  const calls = [];
  t.mock.method(globalThis, "fetch", async (url, options) => {
    calls.push({ url: String(url), options });
    if (url.includes("catalog.get_catalog")) return response({
      products: [product], categories: [{ name: "Drinks", category_name: "Drinks" }],
      page: 1, page_size: 20, total: 1, has_more: false,
    });
    if (url.includes("cart.get_cart")) return response({ items: [], item_count: 0, is_guest: true });
    if (url.includes("cart.add_item")) return response({
      items: [{ product: "SKU/1", quantity: 1 }], item_count: 1, is_guest: true,
    });
    throw new Error(`Unexpected request: ${url}`);
  });
  await import(`../../intelligent_ordering/public/js/catalog-pages.js?listing=${Date.now()}`);
  await new Promise((resolve) => setTimeout(resolve, 0));
  assert.match(calls.find((call) => call.url.includes("get_catalog")).url, /category=Drinks/);
  const card = nodes.get("#catalog-products").children[0];
  assert.equal(card.children[1].children[0].textContent, "<Milk>");
  assert.equal(card.children[1].children[0].href, "/product-details?product=SKU%2F1");
  const button = card.children.at(-1);
  assert.equal(button.disabled, false);
  await button.listeners.click();
  const addCall = calls.find((call) => call.url.includes("cart.add_item"));
  assert.equal(addCall.options.body.get("product"), "SKU/1");
  assert.deepEqual(JSON.parse([...storage.values()][0]), [{ product: "SKU/1", quantity: 1 }]);
  assert.equal(events.at(-1).detail, 1);
  assert.equal(nodes.get("#cart-feedback").textContent, "Added to cart.");
});

test("detail page reports an unavailable product without fabricating data", async (t) => {
  const { nodes } = installPage(t, "detail", "", "/products/missing");
  t.mock.method(globalThis, "fetch", async (url) => {
    if (url.includes("catalog.get_product")) {
      return { ok: false, json: async () => ({ message: "This product is unavailable." }) };
    }
    return response({ items: [], item_count: 0, is_guest: true });
  });
  await import(`../../intelligent_ordering/public/js/catalog-pages.js?detail=${Date.now()}`);
  await new Promise((resolve) => setTimeout(resolve, 0));
  assert.match(nodes.get("#product-status").textContent, /unavailable/);
  assert.equal(nodes.get("#product-detail").children.length, 0);
});

test("customer cart merges saved guest items before adding a product", async (t) => {
  const { nodes, storage, events } = installPage(t, "detail", "", "/products/SKU-1");
  storage.set("intelligent-ordering.guest-cart.v1", JSON.stringify([{ product: "OLD", quantity: 2 }]));
  const calls = [];
  t.mock.method(globalThis, "fetch", async (url, options) => {
    calls.push({ url: String(url), options });
    if (url.includes("catalog.get_product")) return response({ ...product, name: "SKU-1" });
    if (url.includes("cart.get_cart")) return response({ items: [], item_count: 0, is_guest: false });
    if (url.includes("cart.merge_guest_cart")) return response({
      items: [{ product: "OLD", quantity: 2 }], item_count: 2, is_guest: false,
    });
    if (url.includes("cart.add_item")) return response({
      items: [{ product: "OLD", quantity: 2 }, { product: "SKU-1", quantity: 1 }],
      item_count: 3, is_guest: false,
    });
    throw new Error(`Unexpected request: ${url}`);
  });
  await import(`../../intelligent_ordering/public/js/catalog-pages.js?customer=${Date.now()}`);
  await new Promise((resolve) => setTimeout(resolve, 0));
  const merge = calls.find((call) => call.url.includes("merge_guest_cart"));
  assert.deepEqual(JSON.parse(merge.options.body.get("guest_items")), [{ product: "OLD", quantity: 2 }]);
  assert.equal(storage.size, 0);
  const button = nodes.get("#product-detail").children[0].children.at(-1);
  await button.listeners.click();
  assert.equal(events.at(-1).detail, 3);
});

test("out of stock products cannot be added and cart failures are shown", async (t) => {
  const { nodes } = installPage(t, "detail", "", "/products/SKU-1");
  t.mock.method(globalThis, "fetch", async (url) => {
    if (url.includes("catalog.get_product")) return response({ ...product, available_quantity: 0 });
    return { ok: false, json: async () => ({ message: "Cart is unavailable." }) };
  });
  await import(`../../intelligent_ordering/public/js/catalog-pages.js?stock=${Date.now()}`);
  await new Promise((resolve) => setTimeout(resolve, 0));
  const card = nodes.get("#product-detail").children[0];
  assert.equal(card.children.at(-1).disabled, true);
  assert.equal(card.children.at(-2).textContent, "Out of stock");
  assert.match(nodes.get("#cart-feedback").textContent, /Cart is unavailable/);
});

test("catalog submits filters and advances through server-sorted pages", async (t) => {
  const { nodes } = installPage(t, "products");
  const requests = [];
  t.mock.method(globalThis, "fetch", async (url) => {
    if (url.includes("cart.get_cart")) return response({ items: [], item_count: 0, is_guest: true });
    const query = new URL(String(url), "https://example.test").searchParams;
    requests.push(query);
    const page = Number(query.get("page"));
    return response({
      products: [product], categories: [{ name: "Drinks", category_name: "Drinks" }],
      page, page_size: 20, total: 21, has_more: page === 1,
    });
  });
  await import(`../../intelligent_ordering/public/js/catalog-pages.js?filters=${Date.now()}`);
  await new Promise((resolve) => setTimeout(resolve, 0));
  const form = nodes.get("#catalog-form");
  form.elements.search.value = " Milk ";
  form.elements.category.value = "Drinks";
  form.elements.sort.value = "price_desc";
  form.listeners.submit({ preventDefault() {} });
  await new Promise((resolve) => setTimeout(resolve, 0));
  assert.equal(requests.at(-1).get("search"), "Milk");
  assert.equal(requests.at(-1).get("category"), "Drinks");
  assert.equal(requests.at(-1).get("sort"), "price_desc");
  nodes.get("#catalog-next").listeners.click();
  await new Promise((resolve) => setTimeout(resolve, 0));
  assert.equal(requests.at(-1).get("page"), "2");
  assert.equal(nodes.get("#catalog-next").disabled, true);
  assert.equal(nodes.get("#catalog-page").textContent, "Page 2");
});
