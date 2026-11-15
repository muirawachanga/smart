import assert from "node:assert/strict";
import test from "node:test";

class Element {
  constructor() {
    this.dataset = {};
    this.listeners = {};
    this.hidden = false;
    this.disabled = false;
    this.value = "";
    this.checked = false;
    this.textContent = "";
  }
  addEventListener(event, handler) { this.listeners[event] = handler; }
  setAttribute(key, value) { this[key] = value; }
  reportValidity() { return true; }
  reset() { for (const field of Object.values(this.elements)) field.value = ""; }
}

function install(t, kind, search = "") {
  const page = new Element();
  page.dataset = { authPage: kind, authCsrf: "CSRF-TEST" };
  const nodes = new Map(["auth-form", "auth-status", "auth-error", "auth-otp-form", "auth-otp-prompt"]
    .map((id) => [`#${id}`, new Element()]));
  const form = nodes.get("#auth-form");
  form.elements = Object.fromEntries([
    "email", "password", "confirm_password", "full_name", "phone", "terms_version", "privacy_version",
    "accept_terms", "acknowledge_privacy", "marketing_consent",
  ].map((key) => [key, new Element()]));
  form.fields = kind === "login" || kind === "forgot" ? ["email", ...(kind === "login" ? ["password"] : [])]
    : kind === "reset" ? ["password", "confirm_password"] : Object.keys(form.elements);
  form.querySelector = () => new Element();
  const otp = nodes.get("#auth-otp-form");
  otp.elements = { otp: new Element() };
  otp.fields = ["otp"];
  otp.querySelector = () => new Element();
  const redirects = [];
  for (const [name, value] of Object.entries({
    document: {
      querySelector: (selector) => selector === "[data-auth-page]" ? page : nodes.get(selector),
      querySelectorAll: () => [],
    },
    window: { location: { search, origin: "https://shop.example.test", assign: (target) => redirects.push(target) } },
    FormData: class {
      constructor(target) { this.target = target; }
      *[Symbol.iterator]() {
        for (const key of this.target.fields) {
          const field = this.target.elements[key];
          if (["accept_terms", "acknowledge_privacy", "marketing_consent"].includes(key) && !field.checked) continue;
          yield [key, field.value];
        }
      }
    },
  })) {
    const previous = Object.getOwnPropertyDescriptor(globalThis, name);
    Object.defineProperty(globalThis, name, { value, configurable: true, writable: true });
    t.after(() => {
      if (previous) Object.defineProperty(globalThis, name, previous);
      else delete globalThis[name];
    });
  }
  return { form, otp, nodes, redirects };
}

const response = (payload, status = 200) => ({ ok: status < 400, status, json: async () => payload });
const start = (tag) => import(`../../intelligent_ordering/public/js/authentication.js?test=${tag}-${Date.now()}`);
const submit = (form) => form.listeners.submit({ preventDefault() {} });

test("login sends credentials to Frappe and uses the server-authorized destination", async (t) => {
  const { form, redirects } = install(t, "login", "?redirect-to=%2Fcheckout");
  const calls = [];
  t.mock.method(globalThis, "fetch", async (url, options) => {
    calls.push({ url, options });
    return response(url === "/" ? { message: "No App" } : { message: { destination: "/checkout" } });
  });
  await start("login");
  form.elements.email.value = "customer@example.test";
  form.elements.password.value = "long unique test password";
  await submit(form);
  assert.equal(calls[0].options.body.get("cmd"), "login");
  assert.equal(calls[0].options.body.get("pwd"), "long unique test password");
  assert.equal(calls[0].options.credentials, "same-origin");
  assert.equal(calls[0].options.headers["X-Frappe-CSRF-Token"], "CSRF-TEST");
  assert.match(calls[1].url, /authentication.destination/);
  assert.deepEqual(redirects, ["/checkout"]);
});

test("invalid login credentials show feedback without a success redirect", async (t) => {
  const { form, nodes, redirects } = install(t, "login");
  t.mock.method(globalThis, "fetch", async () => response({}, 401));
  await start("invalid");
  await submit(form);
  assert.match(nodes.get("#auth-error").textContent, /Invalid credentials/);
  assert.deepEqual(redirects, []);
});

test("two-factor login submits only the Frappe challenge and verification code", async (t) => {
  const { form, otp, nodes, redirects } = install(t, "login");
  const calls = [];
  t.mock.method(globalThis, "fetch", async (url, options) => {
    calls.push({ url, options });
    return response(calls.length === 1
      ? { verification: { method: "OTP App", setup: true }, tmp_id: "TEMP" }
      : url === "/" ? { message: "Logged In" } : { message: { destination: "/dashboard/admin" } });
  });
  await start("otp");
  form.elements.password.value = "test credential";
  await submit(form);
  assert.equal(form.hidden, true);
  assert.equal(form.elements.password.value, "");
  assert.match(nodes.get("#auth-otp-prompt").textContent, /OTP App/);
  otp.elements.otp.value = "123456";
  await submit(otp);
  assert.equal(calls[1].options.body.get("tmp_id"), "TEMP");
  assert.equal(calls[1].options.body.get("otp"), "123456");
  assert.equal(calls[1].options.body.has("pwd"), false);
  assert.deepEqual(redirects, ["/dashboard/admin"]);
});

test("registration submits exact policy versions and keeps optional marketing consent separate", async (t) => {
  const { form, nodes } = install(t, "register");
  let posted;
  t.mock.method(globalThis, "fetch", async (url, options) => {
    posted = options.body;
    assert.match(url, /customers.register$/);
    return response({ message: { message: "Account created. Sign in to start shopping." } });
  });
  await start("register");
  for (const [key, value] of Object.entries({
    email: "customer@example.test", full_name: "Customer", phone: "+254700000000",
    password: "long unique test passphrase", confirm_password: "long unique test passphrase",
    terms_version: "T-1", privacy_version: "P-1", accept_terms: "1", acknowledge_privacy: "1",
  })) form.elements[key].value = value;
  form.elements.accept_terms.checked = form.elements.acknowledge_privacy.checked = true;
  await submit(form);
  assert.equal(posted.get("terms_version"), "T-1");
  assert.equal(posted.get("privacy_version"), "P-1");
  assert.equal(posted.get("accept_terms"), "1");
  assert.equal(posted.get("marketing_consent"), "0");
  assert.equal(posted.has("roles"), false);
  assert.match(nodes.get("#auth-status").textContent, /Account created/);
  assert.equal(form.hidden, true);
});

test("password confirmation and missing reset tokens fail before making requests", async (t) => {
  const { form, nodes } = install(t, "reset");
  const fetch = t.mock.method(globalThis, "fetch", async () => { throw new Error("Unexpected request"); });
  await start("reset");
  form.elements.password.value = "long unique test passphrase";
  form.elements.confirm_password.value = "different";
  await submit(form);
  assert.match(nodes.get("#auth-error").textContent, /Passwords do not match/);
  form.elements.confirm_password.value = form.elements.password.value;
  await submit(form);
  assert.match(nodes.get("#auth-error").textContent, /reset link from your email/);
  assert.equal(fetch.mock.callCount(), 0);
});

test("reset token errors never hide the form or show a reset success", async (t) => {
  const { form, nodes } = install(t, "reset", "?key=expired");
  t.mock.method(globalThis, "fetch", async (url, options) => {
    assert.equal(options.body.get("key"), "expired");
    return response({ message: "Reset link expired." }, 410);
  });
  await start("expired");
  form.elements.password.value = form.elements.confirm_password.value = "long unique test passphrase";
  await submit(form);
  assert.equal(form.hidden, false);
  assert.match(nodes.get("#auth-error").textContent, /expired/);
});
