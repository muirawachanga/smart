import assert from "node:assert/strict";
import test from "node:test";

class Element {
  constructor() {
    this.listeners = {};
    this.disabled = false;
    this.hidden = false;
    this.textContent = "";
    this.value = "";
  }
  addEventListener(event, callback) { this.listeners[event] = callback; }
  querySelector() { return this.button; }
  reportValidity() { return true; }
  reset() { this.elements.token.value = ""; }
}

function install(t, hash = "") {
  const nodes = new Map([
    "contact-verification", "contact-verification-status", "contact-verification-feedback",
    "contact-email-confirm", "contact-phone-confirm", "contact-email-send", "contact-phone-send",
  ].map((id) => [`#${id}`, new Element()]));
  for (const id of ["contact-email-confirm", "contact-phone-confirm"]) nodes.get(`#${id}`).button = new Element();
  nodes.get("#contact-phone-confirm").elements = { token: new Element() };
  const events = {};
  const history = [];
  for (const [name, value] of Object.entries({
    document: {
      querySelector: (selector) => nodes.get(selector),
      addEventListener: (event, callback) => { events[event] = callback; },
    },
    window: {
      location: { pathname: "/account/profile", search: "", hash },
      history: { replaceState: (...args) => history.push(args) },
      frappe: { csrf_token: "csrf" },
    },
  })) {
    const old = Object.getOwnPropertyDescriptor(globalThis, name);
    Object.defineProperty(globalThis, name, { value, writable: true, configurable: true });
    t.after(() => old ? Object.defineProperty(globalThis, name, old) : delete globalThis[name]);
  }
  return { nodes, events, history };
}

const tick = () => new Promise((resolve) => setTimeout(resolve, 0));
const response = (message) => ({ ok: true, json: async () => ({ message }) });
const profile = {
  verification: { email_verified: false, phone_verified: false, required_for_ordering: true },
};

test("email links are removed from the address bar and require explicit confirmation", async (t) => {
  const { nodes, history } = install(t, "#verify-email=private-token");
  const calls = [];
  let verified = false;
  t.mock.method(globalThis, "fetch", async (url, options) => {
    calls.push({ url, options });
    if (url.includes("contact_verification.confirm")) {
      verified = true;
      return response({ message: "Contact verified." });
    }
    return response({ verification: { ...profile.verification, email_verified: verified } });
  });
  await import(`../../intelligent_ordering/public/js/contact-verification.js?email=${Date.now()}`);
  await tick();
  assert.equal(history[0][2], "/account/profile");
  assert.equal(calls.length, 1);
  const form = nodes.get("#contact-email-confirm");
  assert.equal(form.hidden, false);
  await form.listeners.submit({ preventDefault() {} });
  const confirm = calls.find((call) => call.url.includes("contact_verification.confirm"));
  assert.equal(confirm.options.body.get("token"), "private-token");
  assert.equal(confirm.options.body.get("channel"), "email");
  assert.equal(confirm.options.headers["X-Frappe-CSRF-Token"], "csrf");
  assert.equal(form.hidden, true);
  assert.equal(nodes.get("#contact-email-send").disabled, true);
  assert.match(nodes.get("#contact-verification-status").textContent, /Email: verified/);
});

test("phone verification uses saved contacts and refreshes proof after confirmation", async (t) => {
  const { nodes } = install(t);
  const calls = [];
  let verified = false;
  t.mock.method(globalThis, "fetch", async (url, options) => {
    calls.push({ url, options });
    if (url.includes("contact_verification.request")) return response({ message: "Verification sent." });
    if (url.includes("contact_verification.confirm")) {
      verified = true;
      return response({ message: "Contact verified." });
    }
    return response({ verification: { ...profile.verification, phone_verified: verified } });
  });
  await import(`../../intelligent_ordering/public/js/contact-verification.js?phone=${Date.now()}`);
  await tick();
  await nodes.get("#contact-phone-send").listeners.click();
  const send = calls.at(-1);
  assert.equal(send.options.body.get("channel"), "phone");
  assert.equal(send.options.body.has("phone"), false);
  const form = nodes.get("#contact-phone-confirm");
  form.elements.token.value = "012345";
  await form.listeners.submit({ preventDefault() {} });
  assert.equal(form.elements.token.value, "");
  assert.equal(nodes.get("#contact-phone-send").disabled, true);
  assert.match(nodes.get("#contact-verification-status").textContent, /Phone: verified/);
});

test("invalid challenges display safe feedback without showing verification success", async (t) => {
  const { nodes } = install(t);
  t.mock.method(globalThis, "fetch", async (url) => url.includes("contact_verification.confirm")
    ? { ok: false, status: 417, json: async () => ({
      message: "This verification link or code is invalid or expired. Request a new one.",
    }) } : response(profile));
  await import(`../../intelligent_ordering/public/js/contact-verification.js?invalid=${Date.now()}`);
  await tick();
  const form = nodes.get("#contact-phone-confirm");
  form.elements.token.value = "111111";
  await form.listeners.submit({ preventDefault() {} });
  assert.match(nodes.get("#contact-verification-feedback").textContent, /invalid or expired/);
  assert.match(nodes.get("#contact-verification-status").textContent, /Phone: not verified/);
});

test("profile changes reload proof and failed status requests keep controls disabled", async (t) => {
  const { nodes, events } = install(t);
  let failed = false;
  t.mock.method(globalThis, "fetch", async () => {
    if (failed) throw new Error("offline");
    return response(profile);
  });
  await import(`../../intelligent_ordering/public/js/contact-verification.js?reload=${Date.now()}`);
  await tick();
  assert.equal(nodes.get("#contact-phone-send").disabled, false);
  failed = true;
  events["smarto:profile-saved"]();
  await tick();
  assert.equal(nodes.get("#contact-phone-send").disabled, true);
  assert.match(nodes.get("#contact-verification-feedback").textContent, /connect/);
});
