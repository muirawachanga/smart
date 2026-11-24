import { ApiError, get } from "./api.js";
import { formatPrice, orderConfirmationUrl, orderPaymentUrl, orderTrackingUrl, renderOrderItems, text } from "./components/order-display.js";
import { mountOrderPayment } from "./payments.js";
import { FINGERPRINT_KEY, ORDER_KEY, TOKEN_KEY } from "./checkout-recovery.js";
import { displayError, ERROR_MESSAGES } from "./error-messages.js";

const status = document.querySelector("#order-status");
const target = document.querySelector("#order-detail");
const login = document.querySelector("#order-login");
const paymentPage = window.location.pathname.replace(/\/$/, "") === "/payment";

async function loadOrder() {
  try {
    const path = window.location.pathname.replace(/\/$/, "");
    const id = path.startsWith("/order-confirmation/")
      ? decodeURIComponent(path.slice("/order-confirmation/".length))
      : new URLSearchParams(window.location.search).get("order");
    if (!id) throw new ApiError(ERROR_MESSAGES.missing);
    const order = await get("orders.get_my_order", { order_name: id });
    if (order.requires_login) {
      login.href = `/login?${new URLSearchParams({ "redirect-to": paymentPage ? orderPaymentUrl(id) : orderConfirmationUrl(id) })}`;
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
    const tracking = text("a", "Track delivery and confirm receipt", "smarto-button smarto-button-secondary");
    tracking.href = orderTrackingUrl(order.name);
    target.append(tracking);
    if (paymentPage) {
      mountOrderPayment(target, order);
      status.textContent = order.payment_status === "Paid"
        ? "This order is paid."
        : ["Cancelled", "Completed"].includes(order.status)
          ? "This order is closed; no new payment can be initiated."
          : order.payment_method === "Cash on Delivery"
            ? order.status === "Confirmed"
              ? "Your Cash on Delivery order is confirmed and stock is reserved. Staff will prepare it and arrange delivery. Pay the rider at handover."
              : "Order placed with Cash on Delivery. Pay the rider at handover; finance confirms collection."
            : "Order placed. Pay using M-Pesa below. Payment is confirmed only after server verification.";
    } else {
      const payLink = text("a",
        order.payment_method === "Cash on Delivery" ? "View Cash on Delivery details" : "Continue to payment",
        "smarto-button");
      payLink.href = orderPaymentUrl(order.name);
      target.append(payLink);
      status.textContent = order.status === "Confirmed" && order.payment_method === "Cash on Delivery"
        ? "Order confirmed. The store will prepare it; pay the rider at handover."
        : order.status === "Pending" && order.payment_method === "M-Pesa"
          ? order.payment_status === "Paid"
            ? "Payment verified. The store will confirm the order separately."
            : "Order placed. Continue to payment; the store will confirm the order separately."
          : "Order details and current status are shown below.";
    }
  } catch (error) {
    status.textContent = `Order could not be loaded: ${displayError(error)}`;
  }
}

loadOrder();
