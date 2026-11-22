import assert from "node:assert/strict";
import test from "node:test";

class Element {
  constructor() {
    this.children = [];
    this.listeners = {};
    this.disabled = false;
    this.checked = false;
    this.value = "";
    this._text = "";
  }
  get textContent() { return this._text + this.children.map((child) => child.textContent).join(""); }
  set textContent(value) { this._text = String(value ?? ""); this.children = []; }
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren(...nodes) { this._text = ""; this.children = nodes; }
  addEventListener(name, callback) { this.listeners[name] = callback; }
  querySelector() { return this.submit; }
  reportValidity() { return true; }
}

function install(t, ids) {
  const nodes = new Map(ids.map((id) => [`#${id}`, new Element()]));
  const setGlobal = (name, value) => {
    const old = Object.getOwnPropertyDescriptor(globalThis, name);
    Object.defineProperty(globalThis, name, { value, writable: true, configurable: true });
    t.after(() => old ? Object.defineProperty(globalThis, name, old) : delete globalThis[name]);
  };
  setGlobal("document", {
    querySelector: (selector) => nodes.get(selector),
    createElement: () => new Element(),
    dispatchEvent() {},
  });
  setGlobal("window", { frappe: {} });
  setGlobal("localStorage", { getItem: () => null, setItem() {}, removeItem() {} });
  setGlobal("CustomEvent", class { constructor(type, data) { this.type = type; this.detail = data.detail; } });
  return nodes;
}

const response = (message) => ({ ok: true, json: async () => ({ message }) });
const tick = () => new Promise((resolve) => setTimeout(resolve, 0));

test("assistant requires consent and adds reviewed products through the existing cart API", async (t) => {
  const nodes = install(t, [
    "assistant-form", "assistant-conversation", "assistant-status", "assistant-products",
    "assistant-recommendations", "assistant-recommendation-products", "assistant-voice-input",
    "assistant-voice-consent", "assistant-voice-status", "assistant-speak-replies",
  ]);
  const form = nodes.get("#assistant-form");
  form.submit = new Element();
  form.elements = { message: new Element(), consent: new Element() };
  const calls = [];
  t.mock.method(globalThis, "fetch", async (url, options = {}) => {
    calls.push({ url: String(url), options });
    if (url.includes("assistant.converse")) return response({
      reply: "Consider milk.", products: [{ name: "MILK", product_name: "Milk", quantity: 2, price: 100, currency: "KES" }], notice: "",
    });
    if (url.includes("catalog.personalized_recommendations")) return response({
      basis: "Based on completed purchases.", products: [{ name: "YOGURT", product_name: "Yogurt", price: 50, currency: "KES" }],
    });
    if (url.includes("cart.get_cart")) return response({ items: [], item_count: 0, is_guest: false });
    if (url.includes("cart.add_item")) return response({ items: [], item_count: 2, is_guest: false });
    throw new Error(`Unexpected request: ${url}`);
  });
  await import(`../../intelligent_ordering/public/js/assistant.js?ui=${Date.now()}`);
  form.elements.message.value = "I need milk";
  form.elements.consent.checked = true;
  await form.listeners.submit({ preventDefault() {} });
  const request = calls.find((call) => call.url.includes("assistant.converse"));
  assert.equal(request.options.body.get("consent"), "1");
  assert.match(nodes.get("#assistant-conversation").textContent, /Consider milk/);
  assert.ok(!calls.some((call) => call.url.includes("cart.add_item")));
  await nodes.get("#assistant-products").children[0].children.at(-1).listeners.click();
  const add = calls.find((call) => call.url.includes("cart.add_item"));
  assert.equal(add.options.body.get("product"), "MILK");
  assert.equal(add.options.body.get("quantity"), "2");
  await nodes.get("#assistant-recommendations").listeners.click();
  assert.match(nodes.get("#assistant-recommendation-products").textContent, /Yogurt/);
});

test("voice input needs consent, requires review, and reads replies only when enabled", async (t) => {
  const nodes = install(t, [
    "assistant-form", "assistant-conversation", "assistant-status", "assistant-products",
    "assistant-recommendations", "assistant-recommendation-products", "assistant-voice-input",
    "assistant-voice-consent", "assistant-voice-status", "assistant-speak-replies",
  ]);
  const form = nodes.get("#assistant-form");
  form.submit = new Element();
  form.elements = { message: new Element(), consent: new Element() };
  let listening;
  const spoken = [];
  window.isSecureContext = true;
  window.SpeechRecognition = class {
    constructor() { listening = this; }
    start() {}
    abort() { this.onend(); }
  };
  window.SpeechSynthesisUtterance = class { constructor(value) { this.text = value; } };
  window.speechSynthesis = { cancel() {}, speak: (utterance) => spoken.push(utterance.text) };
  let requests = 0;
  t.mock.method(globalThis, "fetch", async (url) => {
    if (url.includes("assistant.converse")) {
      requests += 1;
      return response({ reply: "Consider milk.", products: [] });
    }
    throw new Error(`Unexpected request: ${url}`);
  });
  await import(`../../intelligent_ordering/public/js/assistant.js?voice=${Date.now()}`);
  nodes.get("#assistant-voice-input").listeners.click();
  assert.match(nodes.get("#assistant-voice-status").textContent, /Agree/);
  assert.equal(listening, undefined);
  nodes.get("#assistant-voice-consent").checked = true;
  nodes.get("#assistant-voice-input").listeners.click();
  listening.onresult({ results: [[{ transcript: "Find milk" }]] });
  await form.listeners.submit({ preventDefault() {} });
  assert.equal(requests, 0);
  listening.onend();
  assert.equal(form.elements.message.value, "Find milk");
  assert.equal(requests, 0);
  form.elements.consent.checked = true;
  await form.listeners.submit({ preventDefault() {} });
  assert.equal(requests, 1);
  assert.deepEqual(spoken, []);
  nodes.get("#assistant-speak-replies").checked = true;
  form.elements.message.value = "More milk";
  await form.listeners.submit({ preventDefault() {} });
  assert.deepEqual(spoken, ["Consider milk."]);
});

test("voice input offers a typed alternative without secure browser support", async (t) => {
  const nodes = install(t, [
    "assistant-form", "assistant-conversation", "assistant-status", "assistant-products",
    "assistant-recommendations", "assistant-recommendation-products", "assistant-voice-input",
    "assistant-voice-consent", "assistant-voice-status", "assistant-speak-replies",
  ]);
  const form = nodes.get("#assistant-form");
  form.submit = new Element();
  form.elements = { message: new Element(), consent: new Element() };
  window.isSecureContext = false;
  await import(`../../intelligent_ordering/public/js/assistant.js?no-voice=${Date.now()}`);
  assert.equal(nodes.get("#assistant-voice-input").disabled, true);
  assert.match(nodes.get("#assistant-voice-status").textContent, /HTTPS/);
});

test("forecast widgets display labeled estimates and insufficient history", async (t) => {
  const nodes = install(t, [
    "sales-forecast-results", "sales-forecast-status", "demand-forecast-results", "demand-forecast-status",
  ]);
  t.mock.method(globalThis, "fetch", async (url) => {
    if (url.includes("sales_forecast")) return response({
      basis: "Successful payments.", model: "Statistical model.",
      series: [{ currency: "KES", environment: "Production", available: true,
        forecast: [{ date: "2026-02-01", estimate: 100 }] }],
    });
    if (url.includes("demand_forecast")) return response({
      basis: "Completed orders.", model: "Statistical model.",
      products: [{ product: "MILK", product_name: "Milk", available: false, history_days: 10, active_days: 3 }],
    });
    throw new Error(`Unexpected request: ${url}`);
  });
  await import(`../../intelligent_ordering/public/js/forecasts.js?ui=${Date.now()}`);
  await tick();
  assert.match(nodes.get("#sales-forecast-results").textContent, /KES.*Production.*100/);
  assert.match(nodes.get("#demand-forecast-results").textContent, /Milk.*Insufficient history/);
});
