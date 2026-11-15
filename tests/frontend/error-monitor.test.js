import assert from "node:assert/strict";
import test from "node:test";

test("unexpected errors show a safe message without exposing error details", async (t) => {
  const original = Object.fromEntries(["window", "document"].map((key) =>
    [key, Object.getOwnPropertyDescriptor(globalThis, key)]));
  t.after(() => {
    for (const [key, descriptor] of Object.entries(original)) {
      if (descriptor) Object.defineProperty(globalThis, key, descriptor);
      else delete globalThis[key];
    }
  });
  const events = {};
  const alert = { hidden: true, textContent: "" };
  Object.defineProperty(globalThis, "window", {
    value: { addEventListener(name, callback) { events[name] = callback; } }, configurable: true,
  });
  Object.defineProperty(globalThis, "document", {
    value: { querySelector: () => alert }, configurable: true,
  });
  await import(`../../intelligent_ordering/public/js/error-monitor.js?test=${Date.now()}`);
  events.error({ message: "private secret", filename: "private-url" });
  assert.equal(alert.hidden, false);
  assert.match(alert.textContent, /PAGE-ERROR.*Time:/);
  assert.doesNotMatch(alert.textContent, /private|secret/);
  events.unhandledrejection({ reason: new Error("private secret") });
  assert.match(alert.textContent, /PAGE-REQUEST.*Time:/);
  assert.doesNotMatch(alert.textContent, /private|secret/);
});
