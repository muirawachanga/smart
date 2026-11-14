import { changeCart, loadCart } from "./cart-service.js";
import { clearGuestCart } from "./cart-storage.js";
import { formatPrice, text } from "./components/order-display.js";
import { productImage } from "./components/product-image.js";

const status = document.querySelector("#cart-status");
const feedback = document.querySelector("#cart-feedback");
const items = document.querySelector("#cart-items");
const total = document.querySelector("#cart-total");
const clearButton = document.querySelector("#clear-cart");
const clearGuestButton = document.querySelector("#clear-guest-cart");
const checkoutLink = document.querySelector("#checkout-link");
let cart = null;
let busy = false;

function render() {
  clearButton.hidden = !cart?.items.length;
  clearButton.disabled = busy;
  checkoutLink.hidden = !cart?.items.length || busy || cart.items.some((item) => !item.available);
  if (!cart) {
    items.replaceChildren();
    total.textContent = "";
    return;
  }
  status.textContent = cart.items.length
    ? `${cart.item_count} item(s) in your cart.`
    : "Your cart is empty.";
  total.textContent = `Subtotal: ${formatPrice(cart.total, cart.currency)}`;
  items.replaceChildren(...cart.items.map((item) => {
    const row = text("article", "", "smarto-order-item");
    row.append(productImage(item.image, item.product_name, "smarto-cart-image"));
    row.append(text("h2", item.product_name));
    if (item.unit_price !== null) {
      row.append(text("p", `${formatPrice(item.unit_price, item.currency)} each`));
      row.append(text("p", `Subtotal: ${formatPrice(item.subtotal, item.currency)}`));
    }
    if (!item.available) {
      row.append(text("p", item.stock_status === "Unavailable"
        ? "This product is unavailable."
        : `Only ${item.available_quantity} available. Adjust the quantity or remove this item.`));
    }
    const label = text("label", "Quantity ");
    const quantity = document.createElement("input");
    quantity.type = "number";
    quantity.min = "1";
    quantity.max = String(Math.min(Number(item.available_quantity), cart.max_quantity));
    quantity.step = "1";
    quantity.value = String(item.quantity);
    quantity.disabled = busy || Number(item.available_quantity) < 1;
    label.append(quantity);
    const update = text("button", "Update quantity", "smarto-button smarto-button-secondary");
    update.type = "button";
    update.disabled = quantity.disabled;
    update.addEventListener("click", () => {
      if (!quantity.reportValidity()) return;
      mutate("cart.update_item", { product: item.product, quantity: quantity.value });
    });
    const remove = text("button", "Remove", "smarto-button smarto-button-secondary");
    remove.type = "button";
    remove.disabled = busy;
    remove.addEventListener("click", () => mutate("cart.remove_item", { product: item.product }));
    const controls = text("div", "", "smarto-actions");
    controls.append(label, update, remove);
    row.append(controls);
    return row;
  }));
}

async function initialize() {
  status.textContent = "Loading cart...";
  feedback.textContent = "";
  clearGuestButton.hidden = true;
  try {
    cart = await loadCart();
    if (cart.removed_products?.length) {
      feedback.textContent = `${cart.removed_products.length} unavailable item(s) were removed from your cart.`;
    }
  } catch (error) {
    cart = null;
    status.textContent = "Cart could not be loaded.";
    feedback.textContent = error.message;
    clearGuestButton.hidden = false;
  }
  render();
}

async function mutate(endpoint, parameters = {}) {
  if (!cart || busy) return;
  busy = true;
  feedback.textContent = "";
  render();
  try {
    cart = await changeCart(endpoint, parameters, cart.is_guest);
    if (cart.removed_products?.length) {
      feedback.textContent = `${cart.removed_products.length} unavailable item(s) were removed from your cart.`;
    }
  } catch (error) {
    feedback.textContent = `Cart could not be updated: ${error.message}`;
  } finally {
    busy = false;
    render();
  }
}

clearButton.addEventListener("click", () => mutate("cart.clear_cart"));
clearGuestButton.addEventListener("click", () => {
  try {
    clearGuestCart();
    initialize();
  } catch (error) {
    feedback.textContent = `Browser-saved cart could not be cleared: ${error.message}`;
  }
});
initialize();
