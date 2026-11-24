import assert from "node:assert/strict";
import test from "node:test";

class Element {
  constructor() {
    this.children = [];
    this.listeners = {};
    this.value = "";
    this.textContent = "";
    this.hidden = true;
    this.disabled = false;
    this.checked = false;
    this.dataset = {};
  }
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren(...nodes) { this.children = nodes; }
  addEventListener(name, handler) { this.listeners[name] = handler; }
  reportValidity() { return true; }
  focus() {}
}

function install(t, kind) {
  const nodes = new Map([
    "customer-status", "customer-feedback", "customer-form", "customer-list", "customer-pagination",
    "customer-previous", "customer-next", "customer-page", "customer-refresh", "customer-login",
    "customer-email", "address-form-title", "address-new",
    "customer-payment-search", "customer-payment-clear",
  ].map((id) => [`#${id}`, new Element()]));
  const form = nodes.get("#customer-form");
  const fields = kind === "register" ? ["full_name", "email"] : kind === "profile" ? ["full_name", "phone"]
    : ["address_name", "address_label", "address_line_1", "address_line_2", "city", "region", "postal_code", "is_default"];
  form.elements = Object.fromEntries(fields.map((field) => [field, new Element()]));
  const submit = new Element();
  const searchForm = nodes.get("#customer-payment-search");
  searchForm.elements = { search: new Element(), search_by: new Element() };
  searchForm.elements.search_by.value = "phone";
  searchForm.reset = () => {
    searchForm.elements.search.value = "";
    searchForm.elements.search_by.value = "phone";
  };
  form.querySelector = () => submit;
  form.reset = () => { for (const field of Object.values(form.elements)) { field.value = ""; field.checked = false; } };
  function setGlobal(name, value) {
    const original = Object.getOwnPropertyDescriptor(globalThis, name);
    Object.defineProperty(globalThis, name, { value, writable: true, configurable: true });
    t.after(() => {
      if (original) Object.defineProperty(globalThis, name, original);
      else delete globalThis[name];
    });
  }
  setGlobal("document", {
    querySelector: (selector) => selector === "[data-customer-page]" ? { dataset: { customerPage: kind } }
      : selector === "#customer-form" && ["payments", "notifications"].includes(kind) ? null : nodes.get(selector),
    createElement: () => new Element(),
  });
  setGlobal("window", { location: { pathname: "/account/payments" }, frappe: {}, confirm: () => true });
  setGlobal("FormData", class {
    *[Symbol.iterator]() {
      for (const [key, field] of Object.entries(form.elements)) yield [key, field.value];
    }
  });
  return { nodes, form, submit };
}

const response = (message) => ({ ok: true, json: async () => ({ message }) });
const tick = () => new Promise((resolve) => setTimeout(resolve, 0));

test("profile form uses actual profile data and saves validated fields through API", async (t) => {
  const { nodes, form } = install(t, "profile");
  const calls = [];
  t.mock.method(globalThis, "fetch", async (url, options) => {
    calls.push({ url, options });
    return response({ email: "customer@example.test", full_name: "Customer", phone: "+254700000000" });
  });
  await import(`../../intelligent_ordering/public/js/customer-portal.js?profile=${Date.now()}`);
  await tick();
  assert.equal(form.hidden, false);
  assert.equal(form.elements.full_name.value, "Customer");
  form.elements.full_name.value = "Updated";
  await form.listeners.submit({ preventDefault() {} });
  assert.match(calls.at(-1).url, /customers.save_profile$/);
  assert.equal(calls.at(-1).options.body.get("full_name"), "Updated");
  assert.equal(nodes.get("#customer-status").textContent, "Profile saved.");
});

test("address edit and save retains identifier but never submits a customer identifier", async (t) => {
  const { nodes, form } = install(t, "addresses");
  const calls = [];
  const address = { name: "ADDR-1", address_line_1: "Home Road", city: "Nairobi", is_default: 1 };
  t.mock.method(globalThis, "fetch", async (url, options) => {
    calls.push({ url, options });
    return response([address]);
  });
  await import(`../../intelligent_ordering/public/js/customer-portal.js?address=${Date.now()}`);
  await tick();
  nodes.get("#customer-list").children[0].children[2].listeners.click();
  assert.equal(form.elements.address_name.value, "ADDR-1");
  form.elements.address_line_1.value = "Updated Road";
  await form.listeners.submit({ preventDefault() {} });
  assert.equal(calls.at(-1).options.body.get("address_name"), "ADDR-1");
  assert.equal(calls.at(-1).options.body.get("is_default"), "1");
  assert.equal(calls.at(-1).options.body.has("customer"), false);
  assert.equal(form.elements.address_name.value, "");
});

test("notifications mark a real record read and refresh the list", async (t) => {
  const { nodes } = install(t, "notifications");
  const calls = [];
  let read = false;
  t.mock.method(globalThis, "fetch", async (url, options) => {
    calls.push({ url, options });
    if (url.includes("read_notification")) { read = true; return response({ name: "NOTICE-1", read: 1 }); }
    return response({
      notifications: [{ name: "NOTICE-1", subject: "<Order confirmed>", creation: "Today", read }],
      has_more: false,
    });
  });
  await import(`../../intelligent_ordering/public/js/customer-portal.js?notifications=${Date.now()}`);
  await tick();
  const card = nodes.get("#customer-list").children[0];
  assert.equal(card.children[0].children[0].textContent, "<Order confirmed>");
  assert.equal(card.children[0].children[1].dataset.status, "unread");
  await card.children.at(-1).listeners.click();
  assert.equal(calls.find((call) => call.url.includes("read_notification")).options.body.get("name"), "NOTICE-1");
  assert.equal(nodes.get("#customer-list").children[0].children.length, 3);
});

test("unauthorized portal requests show an error and login without customer records", async (t) => {
  const { nodes } = install(t, "payments");
  t.mock.method(globalThis, "fetch", async () => ({
    ok: false, status: 403, json: async () => ({ message: "Customer access required." }),
  }));
  await import(`../../intelligent_ordering/public/js/customer-portal.js?denied=${Date.now()}`);
  await tick();
  assert.equal(nodes.get("#customer-list").children.length, 0);
  assert.equal(nodes.get("#customer-login").hidden, false);
  assert.match(nodes.get("#customer-feedback").textContent, /can't access.*sign in/i);
  assert.doesNotMatch(nodes.get("#customer-feedback").textContent, /HTTP|customers\.payment_history/);
});

test("customers search their payment history and filters persist across pages and refresh", async (t) => {
  const { nodes } = install(t, "payments");
  const calls = [];
  t.mock.method(globalThis, "fetch", async (url) => {
    calls.push(new URL(url, "https://example.test"));
    return response({ transactions: [{
      order: "SO-OWN", status: "Pending", payment_method: "M-Pesa", amount: 4, currency: "KES",
      phone_number: "254712345678",
    }], has_more: true });
  });
  await import(`../../intelligent_ordering/public/js/customer-portal.js?search=${Date.now()}`);
  await tick();
  const search = nodes.get("#customer-payment-search");
  search.elements.search.value = " 0712345678 ";
  search.listeners.submit({ preventDefault() {} });
  await tick();
  assert.equal(calls.at(-1).searchParams.get("search"), "0712345678");
  assert.equal(calls.at(-1).searchParams.get("search_by"), "phone");
  nodes.get("#customer-next").listeners.click();
  await tick();
  assert.equal(calls.at(-1).searchParams.get("page"), "2");
  await nodes.get("#customer-refresh").listeners.click();
  assert.equal(calls.at(-1).searchParams.get("search"), "0712345678");
  search.elements.search_by.value = "receipt";
  search.elements.search.value = "TEST1234567";
  search.listeners.submit({ preventDefault() {} });
  await tick();
  assert.equal(calls.at(-1).searchParams.get("page"), "1");
  assert.equal(calls.at(-1).searchParams.get("search_by"), "receipt");
  nodes.get("#customer-payment-clear").listeners.click();
  await tick();
  assert.equal(calls.at(-1).searchParams.get("search"), "");
  assert.ok(calls.every((url) => url.pathname.endsWith("customers.payment_history")));
});
