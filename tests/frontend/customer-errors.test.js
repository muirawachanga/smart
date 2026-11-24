import assert from "node:assert/strict";
import test from "node:test";
import { fetchWithTimeout, get, post, readResponse } from "../../intelligent_ordering/public/js/api.js";
import { ERROR_MESSAGES } from "../../intelligent_ordering/public/js/error-messages.js";
import { initErrorUI, setupPhoneValidation } from "../../intelligent_ordering/public/js/error-ui.js";

test("customer API errors are actionable without server details and retain status", async (t) => {
  const previous = Object.getOwnPropertyDescriptor(globalThis, "window");
  Object.defineProperty(globalThis, "window", {
    value: { location: { pathname: "/checkout" } }, configurable: true,
  });
  t.after(() => previous ? Object.defineProperty(globalThis, "window", previous) : delete globalThis.window);
  for (const [status, message] of [
    [401, ERROR_MESSAGES.session], [403, ERROR_MESSAGES.access], [404, ERROR_MESSAGES.missing],
    [429, ERROR_MESSAGES.rateLimit], [500, ERROR_MESSAGES.busy], [503, ERROR_MESSAGES.busy],
  ]) {
    await assert.rejects(readResponse({
      ok: false, status, json: async () => ({ message: "private details", exc: "traceback" }),
    }, "checkout.create_order"), (error) => {
      assert.equal(error.status, status);
      assert.equal(error.message, message);
      assert.doesNotMatch(error.message, /HTTP|checkout\.create_order|private|traceback/);
      return true;
    });
  }
  await assert.rejects(readResponse({
    ok: false, status: 401, json: async () => ({ message: "unknown user" }),
  }, "authentication.login"), { message: ERROR_MESSAGES.login });
  await assert.rejects(readResponse({
    ok: false, status: 502, json: async () => { throw new Error("HTML traceback"); },
  }, "checkout.get_checkout"), { message: ERROR_MESSAGES.busy });
  t.mock.method(globalThis, "fetch", async () => { throw new Error("private browser details"); });
  await assert.rejects(get("checkout.get_checkout"), { message: ERROR_MESSAGES.connection });
});

test("timeouts cover both the request and response body", async (t) => {
  for (const stage of ["request", "body"]) {
    t.mock.method(globalThis, "fetch", (_url, { signal }) => {
      const pending = () => new Promise((_resolve, reject) => {
        signal.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError")));
      });
      return stage === "request" ? pending() : Promise.resolve({ ok: true, json: pending });
    });
    await assert.rejects(fetchWithTimeout("/", {}, "checkout.create_order", {}, 5), { name: "AbortError" });
    t.mock.restoreAll();
  }
});

test("uncertain payment outcomes tell customers to check status before retrying", async (t) => {
  const previous = Object.getOwnPropertyDescriptor(globalThis, "window");
  Object.defineProperty(globalThis, "window", {
    value: { location: { pathname: "/payments" } }, configurable: true,
  });
  t.after(() => previous ? Object.defineProperty(globalThis, "window", previous) : delete globalThis.window);
  t.mock.method(globalThis, "fetch", async () => { throw new DOMException("Aborted", "AbortError"); });
  await assert.rejects(post("payments.initiate_payment"), { message: ERROR_MESSAGES.paymentUnknown });
  await assert.rejects(readResponse({
    ok: false, status: 500, json: async () => ({ message: "provider details" }),
  }, "payments.initiate_payment"), { message: ERROR_MESSAGES.paymentUnknown });
  await assert.rejects(readResponse({
    ok: true, status: 200, json: async () => { throw new Error("invalid response"); },
  }, "payments.initiate_payment"), { message: ERROR_MESSAGES.paymentUnknown });
});

test("inline errors describe the field and clear when corrected without changing values", (t) => {
  const saved = Object.fromEntries(["window", "document"].map((key) => [key, Object.getOwnPropertyDescriptor(globalThis, key)]));
  t.after(() => {
    for (const [key, descriptor] of Object.entries(saved)) {
      if (descriptor) Object.defineProperty(globalThis, key, descriptor);
      else delete globalThis[key];
    }
  });
  const handlers = {};
  const elements = new Map();
  const field = {
    value: "", type: "email", willValidate: true, validity: { valueMissing: true, valid: false },
    dataset: {}, attributes: { "aria-describedby": "help" },
    getAttribute(name) { return this.attributes[name] || null; },
    setAttribute(name, value) { this.attributes[name] = value; },
    removeAttribute(name) { delete this.attributes[name]; },
    insertAdjacentElement(_where, error) { elements.set(error.id, error); },
  };
  Object.defineProperty(globalThis, "window", {
    value: { location: { pathname: "/register" }, addEventListener() {} }, configurable: true,
  });
  Object.defineProperty(globalThis, "document", {
    value: {
      querySelector: () => null, querySelectorAll: () => [],
      addEventListener(name, handler) { handlers[name] = handler; },
      getElementById: (id) => elements.get(id),
      createElement: () => ({
        children: [], setAttribute() {},
        append(...children) { this.children.push(...children); this.lastElementChild = this.children.at(-1); },
        remove() { elements.delete(this.id); },
      }),
    }, configurable: true,
  });
  initErrorUI();
  handlers.invalid({ target: field });
  const id = field.dataset.smartoErrorId;
  assert.equal(elements.get(id).lastElementChild.textContent, ERROR_MESSAGES.required);
  assert.equal(field.attributes["aria-invalid"], "true");
  assert.equal(field.attributes["aria-describedby"], `help ${id}`);
  field.value = "customer@example.test";
  field.validity = { valid: true };
  handlers.input({ target: field });
  assert.equal(field.value, "customer@example.test");
  assert.equal(field.attributes["aria-describedby"], "help");
  assert.equal(field.attributes["aria-invalid"], undefined);
  assert.equal(elements.has(id), false);
});

test("phone validation accepts corrected values without clearing them", () => {
  const handlers = {};
  const field = {
    value: "12",
    addEventListener(name, handler) { handlers[name] = handler; },
    setCustomValidity(message) { this.validationMessage = message; },
  };
  setupPhoneValidation(field);
  assert.equal(field.validationMessage, ERROR_MESSAGES.phone);
  field.value = "+254 700 000 000";
  handlers.input();
  assert.equal(field.validationMessage, "");
  assert.equal(field.value, "+254 700 000 000");
});
