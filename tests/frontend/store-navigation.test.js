import assert from "node:assert/strict";
import test from "node:test";
import { initStoreNavigation } from "../../intelligent_ordering/public/js/store-navigation.js";
import { initPaymentDashboard } from "../../intelligent_ordering/public/js/payments.js";

function install(t, hash) {
  const nodes = new Map();
  function node(selector) {
    if (!nodes.has(selector)) nodes.set(selector, {
      children: [], dataset: {}, listeners: {}, textContent: "", hidden: false,
      append(...children) {
        for (const child of children) {
          child.remove?.();
          child.parent = this;
          this.children.push(child);
        }
      },
      prepend(...children) {
        for (const child of [...children].reverse()) {
          child.remove?.();
          child.parent = this;
          this.children.unshift(child);
        }
      },
      replaceChildren(...children) {
        for (const child of this.children) child.parent = null;
        this.children = [];
        this.append(...children);
      },
      addEventListener(event, handler) { this.listeners[event] = handler; },
      setAttribute(name, value) { this[name] = value; },
      focus() { this.focused = true; },
      scrollIntoView() { this.scrolledIntoView = true; },
      remove() {
        if (this.parent) this.parent.children = this.parent.children.filter((child) => child !== this);
        this.parent = null;
      },
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
    location: { hash }, frappe: {}, confirm: () => true,
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

test("payment method filter is sent to the server and cash does not show M-Pesa receipt", async (t) => {
  const { node } = install(t, "");
  let method = "";
  globalThis.FormData = class {
    *[Symbol.iterator]() { yield ["search", ""]; yield ["status", "Pending"]; yield ["payment_method", method]; }
  };
  const calls = [];
  t.mock.method(globalThis, "fetch", async (url) => {
    calls.push(String(url));
    const message = String(url).includes("payment_summary") ? [] : {
      transactions: [
        { name: "PAY-MP", order: "SO-1", status: "Pending", amount: 100, payment_method: "M-Pesa" },
        { name: "PAY-COD", order: "SO-2", status: "Pending", amount: 200, payment_method: "Cash on Delivery" },
      ], has_more: false,
    };
    return { ok: true, json: async () => ({ message }) };
  });
  initPaymentDashboard();
  await new Promise((resolve) => setTimeout(resolve, 0));
  assert.match(displayedText(node("#payment-transactions").children[0]), /M-Pesa receipt: Not received/);
  const cash = displayedText(node("#payment-transactions").children[1]);
  assert.match(cash, /Cash on Delivery.*Cash collection date: Not confirmed/);
  assert.doesNotMatch(cash, /receipt/i);
  method = "Cash on Delivery";
  node("#payment-filters").listeners.submit({ preventDefault() {} });
  await new Promise((resolve) => setTimeout(resolve, 0));
  const listing = calls.filter((url) => url.includes("payments.list_transactions")).at(-1);
  assert.equal(new URL(listing, "https://example.test").searchParams.get("payment_method"), method);
  assert.equal(new URL(listing, "https://example.test").searchParams.get("status"), "Pending");
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
  assert.ok(node("#payment-transactions").children[0].children.includes(node("#payment-detail")));
  assert.notEqual(node("#payment-detail").scrolledIntoView, true);
  assert.equal(view.disabled, false);
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
  assert.equal(node("#payment-detail").children[0].textContent, "Check with Safaricom");
});

test("finance can confirm COD only when the server reports rider cash collection", async (t) => {
  const { node } = install(t, "#payment-dashboard");
  const calls = [];
  t.mock.method(globalThis, "fetch", async (url, options) => {
    const target = String(url);
    calls.push(target);
    const message = target.includes("payments.get_transaction")
      ? {
        name: "PAY-COD", order: "SO-COD", status: "Pending", amount: 250,
        payment_method: "Cash on Delivery", can_reconcile: false, can_confirm_cod: true,
        cash_collection: {
          status: "Delivered", cash_collected: 1, cash_collected_amount: 250,
          cash_collected_at: "2026-11-17 12:00:00", cash_collected_by: "rider@example.test",
        },
        order_summary: { name: "SO-COD", status: "Ready for Delivery", payment_status: "Unpaid", total: 250, currency: "KES" },
      }
      : target.includes("payment_summary")
        ? []
        : target.includes("payments.list_transactions")
          ? { transactions: [{ name: "PAY-COD", order: "SO-COD", status: "Pending", amount: 250, payment_method: "Cash on Delivery" }], has_more: false }
          : {};
    return { ok: true, json: async () => ({ message }) };
  });
  initPaymentDashboard();
  await new Promise((resolve) => setTimeout(resolve, 0));
  const view = node("#payment-transactions").children[0].children.find(
    (child) => child.textContent === "View payment",
  );
  await view.listeners.click();
  const confirm = node("#payment-detail").children.find(
    (child) => child.textContent === "Confirm cash received",
  );
  assert.ok(confirm);
  await confirm.listeners.click();
  assert.ok(calls.some((url) => url.includes("payments.confirm_cod_payment")));
  assert.ok(!calls.some((url) => url.includes("payments.reconcile_payment")));
});

test("view payment shows loading feedback and a visible error when detail access fails", async (t) => {
  const { node } = install(t, "#payment-dashboard");
  let rejectDetails;
  t.mock.method(globalThis, "fetch", async (url) => {
    if (String(url).includes("payments.get_transaction")) {
      return new Promise((resolve) => { rejectDetails = () => resolve({
        ok: false, status: 403, json: async () => ({}),
      }); });
    }
    return { ok: true, json: async () => ({ message: String(url).includes("payment_summary") ? [] : {
      transactions: [{ name: "PAY-1", order: "SO-1", status: "Pending", amount: 4 }], has_more: false,
    } }) };
  });
  initPaymentDashboard();
  await new Promise((resolve) => setTimeout(resolve, 0));
  const view = node("#payment-transactions").children[0].children.find(
    (child) => child.textContent === "View payment",
  );
  const opening = view.listeners.click();
  assert.equal(view.disabled, true);
  assert.equal(view.textContent, "Opening payment...");
  assert.match(displayedText(node("#payment-detail")), /Loading payment details/);
  rejectDetails();
  await opening;
  assert.match(displayedText(node("#payment-detail")), /permission.*HTTP 403/);
  assert.equal(node("#payment-detail").children[0].role, "alert");
  assert.equal(view.disabled, false);
  assert.equal(view.textContent, "View payment");
});

test("details follow the selected payment and reconciliation stays within its refreshed card", async (t) => {
  const { node } = install(t, "#payment-dashboard");
  const payments = [
    { name: "PAY-1", order: "SO-1", status: "Pending", amount: 4 },
    { name: "PAY-2", order: "SO-2", status: "Pending", amount: 8 },
  ];
  const calls = [];
  t.mock.method(globalThis, "fetch", async (url, options = {}) => {
    calls.push({ url: String(url), options });
    const target = String(url);
    let message;
    if (target.includes("get_transaction")) {
      const id = new URL(target, "https://example.test").searchParams.get("payment_name");
      message = { ...payments.find((payment) => payment.name === id), can_reconcile: true };
    } else if (target.includes("reconcile_payment")) {
      message = {};
    } else if (target.includes("payment_summary")) {
      message = [];
    } else {
      message = { transactions: payments, has_more: false };
    }
    return { ok: true, json: async () => ({ message }) };
  });
  initPaymentDashboard();
  await new Promise((resolve) => setTimeout(resolve, 0));
  const first = node("#payment-transactions").children[0];
  const second = node("#payment-transactions").children[1];
  const view = (card) => card.children.find((child) => child.textContent === "View payment");
  await view(first).listeners.click();
  assert.equal(node("#payment-detail").parent, first);
  await view(second).listeners.click();
  assert.equal(node("#payment-detail").parent, second);
  assert.ok(!first.children.includes(node("#payment-detail")));
  const reconcile = node("#payment-detail").children.find((child) => child.textContent === "Check with Safaricom");
  await reconcile.listeners.click();
  const call = calls.find((item) => item.url.includes("reconcile_payment"));
  assert.equal(call.options.body.get("payment_name"), "PAY-2");
  assert.equal(node("#payment-detail").parent, node("#payment-transactions").children[1]);
  assert.match(displayedText(node("#payment-detail")), /SO-2/);
  assert.notEqual(node("#payment-detail").scrolledIntoView, true);
});
