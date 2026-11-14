import { ApiError, get, post } from "./api.js";
import { loadCart } from "./cart-service.js";
import { formatPrice, orderConfirmationUrl, renderOrderItems } from "./components/order-display.js";
import { checkoutFingerprint, createCheckoutToken, FINGERPRINT_KEY, ORDER_KEY, TOKEN_KEY } from "./checkout-recovery.js";

const status = document.querySelector("#checkout-status");
const feedback = document.querySelector("#checkout-feedback");
const login = document.querySelector("#checkout-login");
const form = document.querySelector("#checkout-form");
const area = document.querySelector("#checkout-area");
const savedAddress = document.querySelector("#checkout-address");
const refreshButton = document.querySelector("#refresh-quote");
const submit = document.querySelector("#checkout-submit");
const review = document.querySelector("#checkout-review");
const totals = document.querySelector("#checkout-totals");
const subtotal = document.querySelector("#checkout-subtotal");
const deliveryFee = document.querySelector("#checkout-delivery-fee");
const total = document.querySelector("#checkout-total");
let requestToken = null;
let revision = null;
let quote = null;
let quoteRequest = 0;
let submitting = false;
let uncertain = false;

function goToOrder(orderName) {
  try {
    sessionStorage.setItem(ORDER_KEY, orderName);
  } catch (error) {
    console.error("Could not store the recovered order reference:", error);
  }
  window.location.assign(orderConfirmationUrl(orderName));
}

function showCart(checkout) {
  renderOrderItems(review, checkout.cart.items, checkout.cart.currency);
  subtotal.textContent = formatPrice(checkout.cart.total, checkout.cart.currency);
  totals.hidden = false;
  document.dispatchEvent(new CustomEvent("smarto:cart-updated", { detail: checkout.cart.item_count }));
}

function canSubmit(checkout) {
  return checkout.cart.items.length > 0 && checkout.cart.items.every((item) => item.available);
}

async function initialize() {
  try {
    requestToken = sessionStorage.getItem(TOKEN_KEY);
    if (requestToken) {
      uncertain = true;
      const previous = await post("checkout.get_checkout_attempt", { request_token: requestToken });
      if (previous.requires_login) {
        status.textContent = "Sign in with the customer account that submitted this checkout.";
        login.hidden = false;
        return;
      }
      if (previous.order_name) {
        goToOrder(previous.order_name);
        return;
      }
    }
    const initial = await get("checkout.get_checkout");
    if (initial.requires_login) {
      status.textContent = "Sign in with a customer account to continue. Your guest cart will be merged after sign-in.";
      login.hidden = false;
      return;
    }

    const cart = await loadCart();
    const checkout = await get("checkout.get_checkout");
    if (checkout.requires_login) throw new Error("Sign in again before checking out.");
    if (cart.removed_products?.length) {
      feedback.textContent = `${cart.removed_products.length} unavailable item(s) were removed from your cart.`;
    }
    revision = checkout.cart_revision;
    form.elements.customer_name.value = checkout.customer_name || "";
    form.elements.phone.value = checkout.phone || "";
    const addresses = checkout.saved_addresses || [];
    savedAddress.replaceChildren(new Option("Enter a new address", ""));
    for (const entry of addresses) {
      savedAddress.add(new Option(entry.address_label || `${entry.address_line_1}, ${entry.city}`, entry.name));
    }
    function fillSavedAddress() {
      const selected = addresses.find((entry) => entry.name === savedAddress.value);
      if (!selected) return;
      for (const field of ["address_line_1", "address_line_2", "city", "region", "postal_code"]) {
        form.elements[field].value = selected[field] || "";
      }
    }
    savedAddress.addEventListener("change", fillSavedAddress);
    const defaultAddress = addresses.find((entry) => entry.is_default);
    if (defaultAddress) {
      savedAddress.value = defaultAddress.name;
      fillSavedAddress();
    }
    area.replaceChildren(new Option("Select delivery area", ""));
    for (const entry of checkout.delivery_areas) {
      area.add(new Option(`${entry.name} - ${formatPrice(entry.delivery_fee, entry.currency)}`, entry.name));
    }
    showCart(checkout);
    form.hidden = false;
    status.textContent = !canSubmit(checkout)
      ? "Your cart is empty or contains unavailable products. Return to your cart to make changes."
      : checkout.delivery_areas.length
        ? "Select a delivery area to review your total."
        : "No delivery areas are configured for this currency. Contact the store.";
  } catch (error) {
    status.textContent = "Checkout could not be loaded.";
    feedback.textContent = error.message;
  }
}

async function refreshQuote() {
  const request = ++quoteRequest;
  quote = null;
  submit.disabled = true;
  feedback.textContent = "";
  if (!area.value) {
    deliveryFee.textContent = "Select a delivery area";
    total.textContent = "Select a delivery area";
    status.textContent = "Select a delivery area to review your total.";
    return;
  }
  status.textContent = "Loading delivery quote...";
  try {
    const checkout = await get("checkout.get_checkout", { delivery_area: area.value });
    if (request !== quoteRequest) return;
    if (checkout.requires_login) throw new Error("Sign in again before checking out.");
    revision = checkout.cart_revision;
    quote = checkout.delivery_quote;
    showCart(checkout);
    deliveryFee.textContent = formatPrice(checkout.delivery_fee, checkout.currency);
    total.textContent = formatPrice(checkout.total, checkout.currency);
    submit.disabled = !canSubmit(checkout);
    status.textContent = submit.disabled
      ? "Your cart is empty or contains unavailable products."
      : "Review the products, delivery fee and address before placing your order.";
  } catch (error) {
    if (request !== quoteRequest) return;
    deliveryFee.textContent = "Unavailable";
    total.textContent = "Refresh the delivery quote";
    status.textContent = "The delivery quote could not be loaded.";
    feedback.textContent = error.message;
  }
}

async function submitOrder(event) {
  event.preventDefault();
  if (submitting || !quote || !form.reportValidity()) return;
  submitting = true;
  submit.disabled = true;
  area.disabled = true;
  refreshButton.disabled = true;
  status.textContent = "Submitting your order...";
  feedback.textContent = "";
  try {
    const values = Object.fromEntries(new FormData(form));
    const submission = {
      ...values,
      delivery_area: area.value,
      cart_revision: revision,
      delivery_quote: quote,
    };
    const fingerprint = await checkoutFingerprint(
      submission, requestToken ? sessionStorage.getItem(FINGERPRINT_KEY) : null,
    );
    if (requestToken) {
      if (sessionStorage.getItem(FINGERPRINT_KEY) !== fingerprint) {
        throw new Error("This pending checkout has different details. Retry the original details or contact the store before placing another order.");
      }
    } else {
      requestToken = createCheckoutToken();
      sessionStorage.setItem(FINGERPRINT_KEY, fingerprint);
      sessionStorage.setItem(TOKEN_KEY, requestToken);
    }
    const result = await post("checkout.create_order", { ...submission, request_token: requestToken });
    goToOrder(result.order.name);
  } catch (error) {
    const rejected = !uncertain && error instanceof ApiError
      && error.status >= 400 && error.status < 500 && ![408, 409].includes(error.status);
    if (rejected) {
      try {
        sessionStorage.removeItem(TOKEN_KEY);
        sessionStorage.removeItem(FINGERPRINT_KEY);
        requestToken = null;
        status.textContent = "The order was rejected. Correct the details and try again.";
      } catch (storageError) {
        uncertain = true;
        status.textContent = "The order was rejected, but checkout recovery state could not be cleared.";
        feedback.textContent = storageError.message;
      }
    } else {
      uncertain = Boolean(requestToken);
      status.textContent = "The order result could not be confirmed. Retry the same submission or reload checkout to check it.";
    }
    if (!feedback.textContent) feedback.textContent = error.message;
    submit.disabled = false;
  } finally {
    submitting = false;
    area.disabled = false;
    refreshButton.disabled = false;
  }
}

area.addEventListener("change", refreshQuote);
refreshButton.addEventListener("click", refreshQuote);
form.addEventListener("submit", submitOrder);
initialize();
