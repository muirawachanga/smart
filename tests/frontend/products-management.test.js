import assert from "node:assert/strict";
import test from "node:test";

class Element {
  constructor() {
    this.children = [];
    this.listeners = {};
    this.value = "";
    this.disabled = false;
    this.hidden = false;
    this._text = "";
  }
  get textContent() { return this._text + this.children.map((child) => child.textContent).join(""); }
  set textContent(value) { this._text = String(value ?? ""); this.children = []; }
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren(...nodes) { this.children = nodes; this._text = ""; }
  addEventListener(name, callback) { this.listeners[name] = callback; }
  reportValidity() { return true; }
  focus() {}
}

function install(t) {
  const nodes = new Map([
    "form", "fields", "status", "error", "list", "editor", "image-file", "image-upload",
    "editor-heading", "save-status", "save-error", "image-status", "image-form",
    "category-form", "category-section", "inventory-link", "previous", "next", "page", "new", "search",
    "category-status",
  ].map((id) => [`#products-${id}`, new Element()]));
  const form = nodes.get("#products-form");
  const keys = ["sku", "product_name", "category", "description", "price", "currency", "enabled"];
  const fields = Object.fromEntries(keys.map((key) => [key, new Element()]));
  form.elements = { namedItem: (key) => fields[key] };
  form.reset = () => { for (const field of Object.values(fields)) field.value = ""; };
  const category = nodes.get("#products-category-form");
  category.elements = { category_name: new Element(), description: new Element() };
  category.querySelector = () => new Element();
  category.reset = () => {};
  nodes.get("#products-search").elements = { search: new Element() };
  const globals = {
    document: { querySelector: (selector) => nodes.get(selector), createElement: () => new Element() },
    window: { frappe: { csrf_token: "csrf" } },
    Option: class extends Element {
      constructor(label, value) { super(); this.textContent = label; this.value = value; }
    },
  };
  for (const [key, value] of Object.entries(globals)) {
    const old = Object.getOwnPropertyDescriptor(globalThis, key);
    Object.defineProperty(globalThis, key, { value, writable: true, configurable: true });
    t.after(() => old ? Object.defineProperty(globalThis, key, old) : delete globalThis[key]);
  }
  return { nodes, form, fields };
}

const response = (message) => ({ ok: true, json: async () => ({ message }) });
const tick = () => new Promise((resolve) => setTimeout(resolve, 0));
const product = {
  name: "MILK", sku: "MILK", product_name: "Milk", category: "Dairy", description: "",
  price: 120, currency: "KES", enabled: 1, image: "", modified: "2026-11-17 10:00:00",
};
const listing = {
  products: [product], categories: [{ name: "Dairy", category_name: "Dairy" }],
  can_create_category: false, can_receive_stock: true, has_more: false,
};

test("authorized product form saves existing DocType fields without touching stock", async (t) => {
  const { nodes, form, fields } = install(t);
  const calls = [];
  t.mock.method(globalThis, "fetch", async (url, options) => {
    calls.push({ url: String(url), options });
    return response(String(url).includes("save_product") ? { product } : listing);
  });
  await import(`../../intelligent_ordering/public/js/products-management.js?create=${Date.now()}`);
  await tick();
  assert.equal(nodes.get("#products-inventory-link").hidden, false);
  assert.equal(nodes.get("#products-category-section").hidden, true);
  nodes.get("#products-new").listeners.click();
  for (const key of ["sku", "product_name", "category", "price", "currency", "enabled"]) {
    fields[key].value = String(product[key]);
  }
  await form.listeners.submit({ preventDefault() {} });
  const save = calls.find((call) => call.url.includes("save_product"));
  assert.equal(save.options.body.get("sku"), "MILK");
  assert.equal(save.options.body.has("quantity"), false);
  assert.equal(save.options.method, "POST");
  assert.match(nodes.get("#products-save-status").textContent, /Product saved/);
  assert.equal(nodes.get("#products-image-upload").disabled, false);
  assert.ok(calls.every((call) => !call.url.includes("inventory.")));
});

test("editing passes the product version and shows rejected writes without success", async (t) => {
  const { nodes, form } = install(t);
  let save;
  t.mock.method(globalThis, "fetch", async (url, options) => {
    if (String(url).includes("save_product")) {
      save = options.body;
      return { ok: false, status: 403, json: async () => ({}) };
    }
    return response(listing);
  });
  await import(`../../intelligent_ordering/public/js/products-management.js?edit=${Date.now()}`);
  await tick();
  nodes.get("#products-list").children[0].children.at(-1).listeners.click();
  await form.listeners.submit({ preventDefault() {} });
  assert.equal(save.get("product"), "MILK");
  assert.equal(save.get("modified"), product.modified);
  assert.match(nodes.get("#products-save-error").textContent, /permission/);
  assert.doesNotMatch(nodes.get("#products-save-status").textContent, /Product saved/);
});

test("denied listing leaves editing and inventory entry unavailable", async (t) => {
  const { nodes } = install(t);
  t.mock.method(globalThis, "fetch", async () => ({
    ok: false, status: 403, json: async () => ({}),
  }));
  await import(`../../intelligent_ordering/public/js/products-management.js?denied=${Date.now()}`);
  await tick();
  assert.equal(nodes.get("#products-fields").disabled, true);
  assert.equal(nodes.get("#products-inventory-link").hidden, true);
  nodes.get("#products-new").listeners.click();
  assert.equal(nodes.get("#products-fields").disabled, true);
});

test("product images use native authenticated uploads and link only the returned file", async (t) => {
  const { nodes } = install(t);
  const calls = [];
  t.mock.method(globalThis, "fetch", async (url, options) => {
    calls.push({ url: String(url), options });
    if (String(url).endsWith("upload_file")) return response({ file_url: "/files/milk.png" });
    if (String(url).includes("save_product")) return response({
      product: { ...product, image: "/files/milk.png" },
    });
    return response(listing);
  });
  await import(`../../intelligent_ordering/public/js/products-management.js?image=${Date.now()}`);
  await tick();
  nodes.get("#products-list").children[0].children.at(-1).listeners.click();
  const file = new Blob(["image"], { type: "image/png" });
  nodes.get("#products-image-file").files = [file];
  await nodes.get("#products-image-form").listeners.submit({ preventDefault() {} });
  const upload = calls.find((call) => call.url.endsWith("upload_file"));
  assert.equal(upload.options.headers["X-Frappe-CSRF-Token"], "csrf");
  assert.equal(upload.options.body.get("is_private"), "0");
  assert.equal(upload.options.body.get("docname"), "MILK");
  assert.equal(upload.options.body.get("doctype"), "Product");
  const link = calls.find((call) => call.url.includes("save_product"));
  assert.equal(link.options.body.get("image"), "/files/milk.png");
  assert.match(nodes.get("#products-image-status").textContent, /uploaded and linked/);
});

test("confirmed product save with failed refresh never invites duplicate creation", async (t) => {
  const { nodes, form } = install(t);
  let saved = false;
  t.mock.method(globalThis, "fetch", async (url) => {
    if (String(url).includes("save_product")) {
      saved = true;
      return response({ product });
    }
    if (saved) throw new Error("offline");
    return response(listing);
  });
  await import(`../../intelligent_ordering/public/js/products-management.js?refresh=${Date.now()}`);
  await tick();
  nodes.get("#products-list").children[0].children.at(-1).listeners.click();
  await form.listeners.submit({ preventDefault() {} });
  assert.match(nodes.get("#products-save-status").textContent, /Product saved, but/);
  assert.equal(nodes.get("#products-fields").disabled, true);
});
