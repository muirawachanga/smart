import assert from "node:assert/strict";
import test from "node:test";
import { ApiError, get } from "../../intelligent_ordering/public/js/api.js";

test("Frappe validation errors are displayed without executing server markup", async (t) => {
  t.mock.method(globalThis, "fetch", async () => ({
    ok: false,
    json: async () => ({
      _server_messages: JSON.stringify([
        JSON.stringify({ message: "Enter a Kenyan M-Pesa mobile number." }),
      ]),
    }),
  }));
  await assert.rejects(get("payments.get_order_payments"), /Kenyan M-Pesa/);
});

test("malformed server errors still report the failed request", async (t) => {
  t.mock.method(globalThis, "fetch", async () => ({
    ok: false,
    json: async () => ({ _server_messages: "not-json", message: { invalid: true } }),
  }));
  await assert.rejects(get("payments.get_order_payments"), /could not be completed/);
});

test("API errors identify operation and status without exposing server tracebacks or query values", async (t) => {
  t.mock.method(globalThis, "fetch", async () => ({
    ok: false, status: 500,
    json: async () => ({ message: "private database details", exc: "secret traceback" }),
  }));
  await assert.rejects(get("orders.get_order", { order_name: "PRIVATE-ORDER" }), (error) => {
    assert.ok(error instanceof ApiError);
    assert.equal(error.status, 500);
    assert.match(error.message, /Operation: orders\.get_order, HTTP 500/);
    assert.doesNotMatch(error.message, /private database|secret traceback|PRIVATE-ORDER/);
    return true;
  });
});

test("network, permission and non-JSON failures give actionable diagnostics", async (t) => {
  const fetch = t.mock.method(globalThis, "fetch", async () => { throw new Error("private browser detail"); });
  await assert.rejects(get("inventory.get_dashboard"), /Could not connect.*Operation: inventory\.get_dashboard/);
  fetch.mock.mockImplementation(async () => ({
    ok: false, status: 403, json: async () => ({ message: "private data" }),
  }));
  await assert.rejects(get("deliveries.list_deliveries"), /permission.*HTTP 403/);
  fetch.mock.mockImplementation(async () => ({
    ok: false, status: 502, json: async () => { throw new Error("bad json"); },
  }));
  await assert.rejects(get("orders.list_orders"), /invalid response.*orders\.list_orders, HTTP 502/);
});
