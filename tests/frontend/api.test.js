import assert from "node:assert/strict";
import test from "node:test";
import { get } from "../../intelligent_ordering/public/js/api.js";

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
