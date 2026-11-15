import assert from "node:assert/strict";
import test from "node:test";
import { initStoreNavigation } from "../../intelligent_ordering/public/js/store-navigation.js";
import { initPaymentDashboard } from "../../intelligent_ordering/public/js/payments.js";

function install(t, hash) {
  const nodes = new Map();
  function node(selector) {
    if (!nodes.has(selector)) nodes.set(selector, {
      children: [], listeners: {}, textContent: "", hidden: false,
      append(...children) { this.children.push(...children); },
      replaceChildren(...children) { this.children = children; },
      addEventListener(event, handler) { this.listeners[event] = handler; },
    });
    return nodes.get(selector);
  }
  const shell = { dataset: {}, querySelector: node };
  const events = {};
  function global(name, value) {
    const original = Object.getOwnPropertyDescriptor(globalThis, name);
    Object.defineProperty(globalThis, name, { value, configurable: true, writable: true });
    t.after(() => {
      if (original) Object.defineProperty(globalThis, name, original);
      else delete globalThis[name];
    });
  }
  global("document", {
    title: "SmartO Storefront", querySelector: (selector) => selector === ".ordering-shell" ? shell : node(selector),
    createElement: () => node(Symbol()),
  });
  global("window", {
    location: { hash }, frappe: {},
    addEventListener(event, handler) { (events[event] ||= []).push(handler); },
  });
  global("FormData", class { *[Symbol.iterator]() { yield ["search", ""]; yield ["status", ""]; } });
  node("#smarto-breadcrumb-current").textContent = "SmartO";
  return { shell, node, changeHash(value) {
    window.location.hash = value;
    for (const handler of events.hashchange || []) handler();
  } };
}

test("admin and payments links focus their section and restore the store on other hashes", (t) => {
  const { shell, node, changeHash } = install(t, "#admin-dashboard");
  initStoreNavigation();
  assert.equal(shell.dataset.storeView, "admin");
  assert.equal(node(".store-page-heading").hidden, true);
  assert.equal(document.title, "Admin dashboard | SmartO");
  changeHash("#payment-dashboard");
  assert.equal(shell.dataset.storeView, "payments");
  assert.equal(node("#smarto-breadcrumb-current").textContent, "Payments");
  changeHash("#catalog");
  assert.equal(shell.dataset.storeView, "");
  assert.equal(node(".store-page-heading").hidden, false);
  assert.equal(document.title, "SmartO Storefront");
  assert.equal(node("#smarto-breadcrumb-current").textContent, "SmartO");
});

test("payments load on a direct dashboard URL and when returning through hash navigation", async (t) => {
  const { node, changeHash } = install(t, "#payment-dashboard");
  const calls = [];
  t.mock.method(globalThis, "fetch", async (url) => {
    calls.push(url);
    return { ok: true, json: async () => ({ message: String(url).includes("payment_summary")
      ? [{ environment: "Sandbox", status: "Pending", transactions: 1, amount: 100 }]
      : { transactions: [{ name: "PAY-1", order: "SO-1", status: "Pending", amount: 100 }], has_more: false } }) };
  });
  initPaymentDashboard();
  await new Promise((resolve) => setTimeout(resolve, 0));
  assert.equal(calls.length, 2);
  assert.equal(node("#payment-transactions").children.length, 1);
  assert.match(node("#payment-summary").children[0].textContent, /Sandbox.*Pending/);
  changeHash("#admin-dashboard");
  assert.equal(calls.length, 2);
  changeHash("#payment-dashboard");
  await new Promise((resolve) => setTimeout(resolve, 0));
  assert.equal(calls.length, 4);
});
