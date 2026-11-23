import { post } from "./api.js";
import { clearGuestCart, readGuestCart, writeGuestCart } from "./cart-storage.js";

function publishCart(cart) {
  document.dispatchEvent(new CustomEvent("smarto:cart-updated", { detail: cart.item_count }));
  return cart;
}

export async function loadCart() {
  const guestItems = readGuestCart();
  let cart = await post("cart.get_cart", { guest_items: JSON.stringify(guestItems) });
  if (cart.is_guest) {
    writeGuestCart(cart.items);
  } else {
    // Keep the guest cart until the server confirms the merge succeeded.
    if (guestItems.length) {
      cart = await post("cart.merge_guest_cart", { guest_items: JSON.stringify(guestItems) });
    }
    clearGuestCart();
  }
  return publishCart(cart);
}

export async function changeCart(endpoint, parameters, isGuest) {
  const values = { ...parameters };
  if (endpoint !== "cart.clear_cart") {
    values.guest_items = JSON.stringify(isGuest ? readGuestCart() : []);
  }
  const cart = await post(endpoint, values);
  if (cart.is_guest) writeGuestCart(cart.items);
  return publishCart(cart);
}
