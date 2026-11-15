import assert from "node:assert/strict";
import test from "node:test";
import { initStaffSidebar } from "../../intelligent_ordering/public/js/staff-sidebar.js";

function install(t, path, hash = "", smallScreen = false) {
  const nodes = new Map();
  const events = {};
  let document;
  function node(selector) {
    if (!nodes.has(selector)) {
      const classes = new Set();
      const attributes = new Map();
      nodes.set(selector, {
        hidden: false,
        inert: false,
        listeners: {},
        classList: {
          toggle(name, value) { if (value) classes.add(name); else classes.delete(name); },
          contains(name) { return classes.has(name); },
        },
        addEventListener(name, handler) { this.listeners[name] = handler; },
        setAttribute(name, value) { attributes.set(name, value); },
        getAttribute(name) { return attributes.get(name) ?? null; },
        removeAttribute(name) { attributes.delete(name); },
        focus() { document.activeElement = this; },
        querySelectorAll(selector) {
          return selector === "a" ? links : [brand, node("#smarto-sidebar-close"), ...links,
            node("#smarto-sidebar-collapse")];
        },
      });
    }
    return nodes.get(selector);
  }
  const links = ["/dashboard/admin", "/dashboard/orders", "/store#payment-dashboard",
    "/store#admin-dashboard", "/dashboard/inventory"].map((href) => {
    const link = node(href);
    link.setAttribute("href", href);
    return link;
  });
  const brand = node("brand");
  const media = {
    matches: smallScreen,
    addEventListener(name, handler) { this.onChange = handler; },
  };
  document = {
    activeElement: null,
    querySelector: node,
    addEventListener(name, handler) { events[name] = handler; },
  };
  const window = {
    location: { pathname: path, hash },
    matchMedia: () => media,
    addEventListener(name, handler) { events[name] = handler; },
  };
  for (const [key, value] of Object.entries({ document, window })) {
    const original = Object.getOwnPropertyDescriptor(globalThis, key);
    Object.defineProperty(globalThis, key, { value, configurable: true });
    t.after(() => {
      if (original) Object.defineProperty(globalThis, key, original);
      else delete globalThis[key];
    });
  }
  return { node, links, brand, media, events, document, window };
}

test("desktop sidebar collapses and highlights the current authorized workspace", (t) => {
  const { node, links } = install(t, "/dashboard/admin");
  initStaffSidebar(true);
  assert.equal(node("#smarto-sidebar").hidden, false);
  assert.equal(links[0].getAttribute("aria-current"), "page");
  assert.equal(links[1].getAttribute("aria-current"), null);
  node("#smarto-sidebar-collapse").listeners.click();
  assert.equal(node("#smarto-workspace-shell").classList.contains("is-sidebar-collapsed"), true);
  assert.equal(node("#smarto-sidebar-collapse").getAttribute("aria-expanded"), "false");
  assert.equal(node("#smarto-sidebar-collapse").getAttribute("aria-label"), "Expand staff navigation");
  node("#smarto-sidebar-collapse").listeners.click();
  assert.equal(node("#smarto-sidebar-collapse").getAttribute("aria-expanded"), "true");
});

test("mobile drawer contains focus and closes through Escape, backdrop and close button", (t) => {
  const { node, events, document, brand, links } = install(t, "/dashboard/orders", "", true);
  initStaffSidebar(true);
  const toggle = node("#smarto-sidebar-toggle");
  const sidebar = node("#smarto-sidebar");
  const close = node("#smarto-sidebar-close");
  const content = node("#smarto-workspace-content");
  assert.equal(sidebar.inert, true);
  toggle.listeners.click();
  assert.equal(content.inert, true);
  assert.equal(sidebar.inert, false);
  assert.equal(document.activeElement, close);
  assert.equal(toggle.getAttribute("aria-expanded"), "true");
  links.at(-1).focus();
  let prevented = false;
  events.keydown({ key: "Tab", preventDefault() { prevented = true; } });
  assert.equal(prevented, true);
  assert.equal(document.activeElement, brand);
  events.keydown({ key: "Tab", shiftKey: true, preventDefault() {} });
  assert.equal(document.activeElement, links.at(-1));
  for (const dismiss of [
    () => events.keydown({ key: "Escape" }),
    () => node("#smarto-sidebar-backdrop").listeners.click(),
    () => close.listeners.click(),
  ]) {
    dismiss();
    assert.equal(content.inert, false);
    assert.equal(sidebar.inert, true);
    assert.equal(toggle.getAttribute("aria-expanded"), "false");
    assert.equal(document.activeElement, toggle);
    toggle.listeners.click();
  }
});

test("hash navigation changes the active management view and restores shopping layout", (t) => {
  const { node, links, window, events } = install(t, "/store", "#payment-dashboard");
  initStaffSidebar(true);
  assert.equal(links[2].getAttribute("aria-current"), "page");
  window.location.hash = "#admin-dashboard";
  events.hashchange();
  assert.equal(links[2].getAttribute("aria-current"), null);
  assert.equal(links[3].getAttribute("aria-current"), "page");
  window.location.hash = "#catalog";
  events.hashchange();
  assert.equal(node("#smarto-sidebar").hidden, true);
  assert.equal(node("#smarto-workspace-shell").classList.contains("has-sidebar"), false);
});

test("guests and customers never activate staff navigation, and hidden links are not highlighted", (t) => {
  const { node, links } = install(t, "/dashboard/admin");
  initStaffSidebar(false);
  assert.equal(node("#smarto-sidebar").hidden, true);
  assert.equal(node("#smarto-sidebar-toggle").hidden, true);
  links[0].hidden = true;
  initStaffSidebar(true);
  assert.ok(links.every((link) => link.getAttribute("aria-current") === null));
});

test("resizing an open mobile drawer restores desktop interaction and navigation closes the drawer", (t) => {
  const { node, media, document } = install(t, "/dashboard/orders", "", true);
  initStaffSidebar(true);
  const toggle = node("#smarto-sidebar-toggle");
  toggle.listeners.click();
  node("#smarto-staff-navigation").listeners.click({ target: { closest: () => ({}) } });
  assert.equal(document.activeElement, toggle);
  assert.equal(node("#smarto-workspace-content").inert, false);
  toggle.listeners.click();
  media.matches = false;
  media.onChange();
  assert.equal(node("#smarto-workspace-content").inert, false);
  assert.equal(node("#smarto-sidebar").inert, false);
  assert.equal(node("#smarto-sidebar-backdrop").hidden, true);
  assert.equal(document.activeElement, node("#smarto-sidebar-collapse"));
});
