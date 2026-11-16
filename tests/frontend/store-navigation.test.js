import assert from "node:assert/strict";
import test from "node:test";
import { initStoreNavigation } from "../../intelligent_ordering/public/js/store-navigation.js";
import { initPaymentDashboard } from "../../intelligent_ordering/public/js/payments.js";

function install(t, hash) {
  const nodes = new Map();
  function node(selector) {
    if (!nodes.has(selector)) nodes.set(selector, {
      children: [], dataset: {}, listeners: {}, textContent: "", hidden: false,
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

function displayedText(element) {
  return [
    element.textContent,
    ...element.children.flatMap(displayedText),
  ].join(" ");
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
      ? [{ environment: "Sandbox", status: "Pending", currency: "KES", transactions: 1, amount: 100 }]
      : { transactions: [{ name: "PAY-1", order: "SO-1", status: "Pending", amount: 100 }], has_more: false } }) };
  });
  initPaymentDashboard();
  await new Promise((resolve) => setTimeout(resolve, 0));
  assert.equal(calls.length, 2);
  assert.equal(node("#payment-transactions").children.length, 1);
  assert.match(displayedText(node("#payment-summary").children[0]), /Sandbox.*Pending/);
  changeHash("#admin-dashboard");
  assert.equal(calls.length, 2);
  changeHash("#payment-dashboard");
  await new Promise((resolve) => setTimeout(resolve, 0));
  assert.equal(calls.length, 4);
});

test("payment details emphasize transaction fields and keep provider diagnostics collapsible", async (t) => {
  const { node } = install(t, "#payment-dashboard");
  t.mock.method(globalThis, "fetch", async (url) => {
    const target = String(url);
    const message = target.includes("payments.get_transaction")
      ? {
        order: "SO-1", status: "Successful", amount: 1250, payment_method: "M-Pesa",
        phone_number: "254700000000", mpesa_receipt_number: "ABC123",
        transaction_date: "2026-11-15", creation: "2026-11-15 10:00:00",
        checkout_request_id: "CHECKOUT-1", callback_response: { ResultCode: 0 },
      }
      : target.includes("payment_summary")
        ? [{ environment: "Production", status: "Successful", transactions: 1, amount: 1250 }]
        : {
          transactions: [{
            name: "PAY-1", order: "SO-1", status: "Successful", amount: 1250,
            phone_number: "254700000000", mpesa_receipt_number: "ABC123",
            transaction_date: "2026-11-15",
          }],
          has_more: false,
        };
    return { ok: true, json: async () => ({ message }) };
  });
  initPaymentDashboard();
  await new Promise((resolve) => setTimeout(resolve, 0));
  assert.equal(node("#payment-transactions").children.length, 1, node("#payment-feedback").textContent);
  const view = node("#payment-transactions").children[0].children.find(
    (child) => child.textContent === "View payment",
  );
  await view.listeners.click();
  const detail = node("#payment-detail").children[0];
  const content = displayedText(detail);
  assert.match(content, /SO-1.*Successful.*KES 1,250\.00/);
  assert.match(content, /254700000000.*ABC123/);
  assert.match(content, /Technical transaction data[\s\S]*CHECKOUT-1[\s\S]*ResultCode/);
});

test("finance workspace loads without a legacy hash and limits reconciliation controls", async (t) => {
  const { node } = install(t, "");
  let permitted = false;
  t.mock.method(globalThis, "fetch", async (url) => {
    const target = String(url);
    return { ok: true, json: async () => ({ message:
      target.includes("payments.get_transaction") ? {
        name: "PAY-1", order: "SO-1", status: "Pending", amount: 100,
        can_reconcile: permitted,
        order_summary: { name: "SO-1", status: "Confirmed", payment_status: "Unpaid", total: 100, currency: "KES" },
      } : target.includes("payment_summary") ? [] : {
        transactions: [{ name: "PAY-1", order: "SO-1", status: "Pending", amount: 100 }],
        has_more: false,
      },
    }) };
  });
  initPaymentDashboard();
  await new Promise((resolve) => setTimeout(resolve, 0));
  assert.equal(node("#payment-transactions").children.length, 1, node("#payment-feedback").textContent);
  const view = node("#payment-transactions").children[0].children.find(
    (child) => child.textContent === "View payment",
  );
  await view.listeners.click();
  assert.match(displayedText(node("#payment-detail")), /Associated order.*Confirmed.*Unpaid/);
  assert.ok(!node("#payment-detail").children.some((child) => child.textContent === "Check with Safaricom"));
  permitted = true;
  await view.listeners.click();
  assert.ok(node("#payment-detail").children.some((child) => child.textContent === "Check with Safaricom"));
});
