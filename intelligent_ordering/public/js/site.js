import { get, post } from "./api.js";
import { readGuestCart } from "./cart-storage.js";
import { initStaffSidebar } from "./staff-sidebar.js";

const menuButton = document.querySelector("#smarto-menu-toggle");
const primaryNavigation = document.querySelector("#smarto-primary-navigation");
const pageStatus = document.querySelector("#smarto-nav-status");
const cartCount = document.querySelector("#cart-count");
let cartCountRevision = 0;
document.addEventListener("smarto:cart-updated", (event) => {
  cartCountRevision += 1;
  cartCount.textContent = String(event.detail);
});

const ROUTE_LABELS = {
  "/": "Home",
  "/about": "About SmartO",
  "/products": "Products",
  "/categories": "Categories",
  "/cart": "Shopping cart",
  "/checkout": "Checkout",
  "/payment": "Payment",
  "/contact": "Contact",
  "/track-order": "Track an order",
  "/order-confirmation": "Order confirmation",
  "/product-details": "Product details",
  "/register": "Create an account",
  "/forgot-password": "Forgot password",
  "/reset-password": "Reset password",
  "/account": "My account",
};

function setNavigationOpen(open) {
  primaryNavigation.classList.toggle("is-open", open);
  menuButton.setAttribute("aria-expanded", String(open));
}

menuButton.addEventListener("click", () => {
  setNavigationOpen(menuButton.getAttribute("aria-expanded") !== "true");
});

document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") setNavigationOpen(false);
});

primaryNavigation.addEventListener("click", (event) => {
  if (event.target.closest("a")) setNavigationOpen(false);
});

function currentPageLabel(path) {
  if (path.startsWith("/products/")) return ROUTE_LABELS["/product-details"];
  if (path.startsWith("/order-confirmation/")) return ROUTE_LABELS["/order-confirmation"];
  if (path.startsWith("/dashboard/")) {
    return `${path.split("/").at(-1).replaceAll("-", " ")} dashboard`;
  }
  return ROUTE_LABELS[path.replace(/\/$/, "")] || "SmartO";
}

function decodeRouteReference(path, prefix) {
  const raw = path.slice(prefix.length);
  try {
    return decodeURIComponent(raw);
  } catch {
    return raw;
  }
}

function updateRouteChrome() {
  const path = window.location.pathname.replace(/\/$/, "") || "/";
  const label = currentPageLabel(path);
  const breadcrumb = document.querySelector("#smarto-breadcrumb-current");
  if (breadcrumb) breadcrumb.textContent = label;

  for (const link of document.querySelectorAll("[data-nav-path]")) {
    const target = link.dataset.navPath;
    const active = path === target
      || (target === "/products" && path.startsWith("/products/"));
    if (active) link.setAttribute("aria-current", "page");
    else link.removeAttribute("aria-current");
  }

  for (const link of document.querySelectorAll("[data-account-path]")) {
    const target = link.dataset.accountPath;
    if (path === target) link.setAttribute("aria-current", "page");
    else link.removeAttribute("aria-current");
  }

  const routeReferenceElement = document.querySelector("[data-route-reference]");
  if (routeReferenceElement && path.startsWith("/products/")) {
    routeReferenceElement.textContent = decodeRouteReference(path, "/products/");
  } else if (routeReferenceElement && path.startsWith("/order-confirmation/")) {
    routeReferenceElement.textContent = decodeRouteReference(path, "/order-confirmation/");
  }
}

function setVisible(element, visible) {
  element.hidden = !visible;
}

function setupAccountNavigation(user) {
  const roles = new Set(user?.roles || []);
  const authenticated = Boolean(user?.user);
  const administrator = user?.user === "Administrator";
  setVisible(document.querySelector("#smarto-login-link"), !authenticated);
  setVisible(document.querySelector("#smarto-register-link"), !authenticated);
  setVisible(document.querySelector("#smarto-account-link"), authenticated);
  setVisible(document.querySelector("#smarto-logout-link"), authenticated);

  const staffNavigation = document.querySelector("#smarto-staff-navigation");
  const staffControls = [
    ["#staff-setup-link", ["System Manager", "Business Admin"]],
    ["#staff-reports-link", ["System Manager", "Business Admin"]],
    ["#staff-delivery-areas-link", ["System Manager", "Business Admin", "Store Manager", "Order Manager", "Delivery Manager"]],
    ["#staff-products-link", ["System Manager", "Business Admin", "Store Manager", "Order Manager", "Inventory Manager"]],
    ["#staff-customers-link", ["System Manager", "Business Admin", "Store Manager", "Customer Support"]],
    ["#staff-accounts-link", ["System Manager"]],
    ["#staff-users-link", ["System Manager"]],
    ["#staff-roles-link", ["System Manager"]],
    ["#staff-permissions-link", ["System Manager"]],
    ["#staff-settings-link", ["System Manager"]],
    ["#staff-audit-link", ["System Manager", "Business Admin"]],
    ["#staff-orders-link", ["System Manager", "Business Admin", "Store Manager", "Order Manager"]],
    ["#payments-link", ["System Manager", "Business Admin", "Store Manager", "Order Manager", "Finance Manager"]],
    ["#deliveries-link", ["System Manager", "Business Admin", "Store Manager", "Order Manager", "Delivery Manager", "Delivery Staff"]],
    ["#admin-dashboard-link", ["System Manager", "Business Admin", "Store Manager", "Order Manager", "Finance Manager", "Inventory Manager", "Delivery Manager"]],
    ["#inventory-dashboard-link", ["System Manager", "Business Admin", "Inventory Manager"]],
    ["#support-dashboard-link", ["System Manager", "Business Admin", "Store Manager", "Customer Support"]],
  ];
  let hasStaffLinks = false;
  for (const [selector, allowedRoles] of staffControls) {
    const link = document.querySelector(selector);
    const visible = authenticated && (administrator || allowedRoles.some((role) => roles.has(role)));
    setVisible(link, visible);
    hasStaffLinks ||= visible;
  }

  const workspace = document.querySelector("#smarto-workspace-link");
  if (administrator || ["System Manager", "Business Admin", "Store Manager", "Finance Manager"].some((role) => roles.has(role))) {
    document.querySelector("#payments-link").href = "/dashboard/sales#payment-dashboard";
  }
  const workspaceByRole = [
    [["System Manager", "Business Admin"], "/dashboard/admin"],
    [["Store Manager"], "/dashboard/owner"],
    [["Finance Manager"], "/dashboard/sales"],
    [["Order Manager"], "/dashboard/orders"],
    [["Inventory Manager"], "/dashboard/inventory"],
    [["Delivery Manager", "Delivery Staff"], "/dashboard/delivery"],
    [["Customer Support"], "/dashboard/support"],
  ];
  const destination = workspaceByRole.find(([allowedRoles]) =>
    administrator || allowedRoles.some((role) => roles.has(role)));
  const staffEntry = document.querySelector("#smarto-staff-entry-link");
  if (destination) {
    workspace.href = destination[1];
    staffEntry.href = destination[1];
    const duplicate = staffControls.some(([selector]) => {
      const link = document.querySelector(selector);
      return !link.hidden && link.getAttribute("href") === destination[1];
    });
    setVisible(workspace, !duplicate);
    setVisible(staffEntry, true);
    hasStaffLinks = true;
  } else {
    setVisible(workspace, false);
    setVisible(staffEntry, false);
  }
  staffNavigation.hidden = !hasStaffLinks;
  initStaffSidebar(hasStaffLinks);
}

async function loadCartCount(user) {
  const revision = cartCountRevision;
  try {
    const guestItems = readGuestCart();
    const cart = await post("cart.get_cart", {
      guest_items: JSON.stringify(guestItems),
    });
    const count = Number.isInteger(cart.item_count)
      ? cart.item_count
      : (cart.items || []).reduce((total, item) => total + Number(item.quantity || 0), 0);
    if (revision === cartCountRevision) cartCount.textContent = String(count);
  } catch (error) {
    if (user?.roles?.includes("Customer")) {
      pageStatus.textContent = `Cart count could not be loaded: ${error.message}`;
      return;
    }
    try {
      const count = readGuestCart().reduce((total, item) => total + item.quantity, 0);
      if (revision === cartCountRevision) cartCount.textContent = String(count);
    } catch (cartError) {
      if (revision === cartCountRevision) cartCount.textContent = "0";
      pageStatus.textContent = cartError.message;
    }
  }
}

async function signOut(event) {
  event.preventDefault();
  const link = event.currentTarget;
  link.setAttribute("aria-disabled", "true");
  try {
    const response = await fetch(link.href, {
      method: "POST",
      credentials: "same-origin",
      headers: { "X-Frappe-CSRF-Token": window.frappe?.csrf_token || "" },
    });
    if (!response.ok) {
      throw new Error(`SmartO could not end this session. Try again. (Operation: authentication.logout, HTTP ${response.status})`);
    }
    window.location.assign("/logged-out");
  } catch (error) {
    const sessionError = document.querySelector("#smarto-session-error");
    const message = error instanceof TypeError
      ? "Could not connect to the server. Check your connection and try again. (Operation: authentication.logout)"
      : error.message;
    if (sessionError) {
      sessionError.textContent = message;
      sessionError.hidden = false;
    } else {
      pageStatus.textContent = message;
    }
    link.removeAttribute("aria-disabled");
  }
}

document.querySelector("#smarto-logout-link").addEventListener("click", signOut);
for (const year of document.querySelectorAll("[data-current-year]")) {
  year.textContent = String(new Date().getFullYear());
}

updateRouteChrome();
const isExistingStorefront = window.location.pathname.replace(/\/$/, "") === "/store";
get("v1.current_user")
  .then((user) => {
    setupAccountNavigation(user);
    if (!isExistingStorefront) return loadCartCount(user);
    return undefined;
  })
  .catch((error) => {
    setupAccountNavigation(null);
    const path = window.location.pathname;
    if (path.startsWith("/dashboard/") || (path === "/store"
      && ["#admin-dashboard", "#payment-dashboard"].includes(window.location.hash))) {
      const sessionError = document.querySelector("#smarto-session-error");
      if (sessionError) {
        sessionError.textContent = `Staff navigation could not be loaded: ${error.message}`;
        sessionError.hidden = false;
      }
    }
    if (!isExistingStorefront) loadCartCount(null);
  });
