import { get } from "./api.js";
import { formatPrice, orderConfirmationUrl, renderOrderItems, text } from "./components/order-display.js";
import { FINGERPRINT_KEY, ORDER_KEY, TOKEN_KEY } from "./checkout-recovery.js";

const status = document.querySelector("#order-status");
const target = document.querySelector("#order-detail");
const login = document.querySelector("#order-login");

async function loadOrder() {
  try {
    const path = window.location.pathname.replace(/\/$/, "");
    const id = path.startsWith("/order-confirmation/")
      ? decodeURIComponent(path.slice("/order-confirmation/".length))
      : new URLSearchParams(window.location.search).get("order");
    if (!id) throw new Error("An order reference is required.");
    const order = await get("orders.get_my_order", { order_name: id });
    if (order.requires_login) {
      login.href = `/login?${new URLSearchParams({ "redirect-to": orderConfirmationUrl(id) })}`;
      login.hidden = false;
      status.textContent = "Sign in with the customer account that placed this order.";
      return;
    }
    try {
      if (sessionStorage.getItem(ORDER_KEY) === order.name) {
        sessionStorage.removeItem(TOKEN_KEY);
        sessionStorage.removeItem(ORDER_KEY);
        sessionStorage.removeItem(FINGERPRINT_KEY);
      }
    } catch (error) {
      console.error("Could not clear the completed checkout recovery state:", error);
    }
    const items = text("div", "", "smarto-cart-items");
    renderOrderItems(items, order.items, order.currency);
    target.replaceChildren(
      text("h2", `Order ${order.name}`),
      text("p", `Order status: ${order.status}`),
      text("p", `Payment status: ${order.payment_status}`),
      text("p", `Customer: ${order.customer_name} · ${order.customer_phone}`),
      text("p", `Delivery address: ${order.delivery_address}`),
      items,
      text("p", `Subtotal: ${formatPrice(order.subtotal, order.currency)}`),
      text("p", `Delivery${order.delivery_area ? ` (${order.delivery_area})` : ""}: ${formatPrice(order.delivery_fee, order.currency)}`),
      text("p", `Total: ${formatPrice(order.total, order.currency)}`),
    );
    status.textContent = "Order details";
  } catch (error) {
    status.textContent = `Order could not be loaded: ${error.message}`;
  }
}

loadOrder();
