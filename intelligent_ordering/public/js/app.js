import { get, post } from "./api.js";
import {
  clearGuestCart,
  readGuestCart,
  writeGuestCart,
} from "./cart-storage.js";
import { showFeedback } from "./components/feedback.js";
import { initPaymentDashboard, mountOrderPayment } from "./payments.js";
import { initDeliveryDashboard } from "./deliveries.js";
import { initAdministrationDashboard } from "./administration.js";
import { initStoreNavigation } from "./store-navigation.js";

initStoreNavigation();

const form = document.querySelector("#catalog-filters");
const searchInput = document.querySelector("#catalog-search");
const categorySelect = document.querySelector("#catalog-category");
const statusElement = document.querySelector("#catalog-status");
const productsElement = document.querySelector("#catalog-products");
const paginationElement = document.querySelector("#catalog-pagination");
const previousButton = document.querySelector("#previous-page");
const nextButton = document.querySelector("#next-page");
const pageIndicator = document.querySelector("#page-indicator");
const cartCountElement = document.querySelector("#cart-count");
const cartStatusElement = document.querySelector("#cart-status");
const cartItemsElement = document.querySelector("#cart-items");
const cartTotalElement = document.querySelector("#cart-total");
const clearCartButton = document.querySelector("#clear-cart");
const feedbackElement = document.querySelector("#app-feedback");
const proceedButton = document.querySelector("#proceed-checkout");
const checkoutSection = document.querySelector("#checkout-section");
const checkoutStatus = document.querySelector("#checkout-status");
const checkoutReview = document.querySelector("#checkout-review");
const checkoutSubtotal = document.querySelector("#checkout-subtotal");
const checkoutTotal = document.querySelector("#checkout-total");
const checkoutArea = document.querySelector("#checkout-delivery-area");
const checkoutFee = document.querySelector("#checkout-delivery-fee");
const checkoutForm = document.querySelector("#checkout-form");
const submitOrderButton = document.querySelector("#submit-order");
const orderConfirmation = document.querySelector("#order-confirmation");
const customerOrdersElement = document.querySelector("#customer-orders");
const customerOrdersStatus = document.querySelector("#orders-status");
const customerOrderDetail = document.querySelector("#customer-order-detail");
const staffOrderForm = document.querySelector("#staff-order-filters");
const staffOrdersElement = document.querySelector("#staff-orders-list");
const staffOrdersStatus = document.querySelector("#staff-orders-status");
const staffOrderDetail = document.querySelector("#staff-order-detail");
const inventorySection = document.querySelector("#inventory-dashboard");
const inventorySummary = document.querySelector("#inventory-summary");
const inventoryStockList = document.querySelector("#inventory-stock-list");
const inventoryStatus = document.querySelector("#inventory-status");
const inventoryMovements = document.querySelector("#inventory-movements");
const inventoryStockFilters = document.querySelector("#inventory-stock-filters");
const inventoryMovementFilters = document.querySelector("#inventory-movement-filters");
const inventoryAdjustmentForm = document.querySelector("#inventory-adjustment-form");
const inventoryReturnForm = document.querySelector("#inventory-return-form");

const ORDER_STATUSES = [
  "Pending",
  "Confirmed",
  "Processing",
  "Ready for Delivery",
  "Completed",
  "Cancelled",
];
const STATUS_TRANSITIONS = {
  Pending: ["Confirmed", "Cancelled"],
  Confirmed: ["Processing", "Cancelled"],
  Processing: ["Ready for Delivery", "Cancelled"],
  "Ready for Delivery": ["Cancelled"],
  Completed: [],
  Cancelled: [],
};

const state = {
  search: "",
  category: "",
  page: 1,
  hasMore: false,
  products: [],
  cart: {
    items: [],
    item_count: 0,
    currency: "KES",
    total: 0,
    is_guest: true,
    max_quantity: 9999,
  },
  cartReady: false,
  cartBusy: true,
  cartError: false,
  checkoutBusy: false,
  checkoutToken: null,
  checkoutRevision: null,
  deliveryQuote: null,
  deliveryQuoteRequest: 0,
  customerOrderPage: 1,
  customerOrdersHasMore: false,
  staffOrderPage: 1,
  staffOrdersHasMore: false,
  staffSearch: "",
  staffStatus: "",
  inventoryPage: 1,
  inventoryHasMore: false,
  inventoryMovementPage: 1,
  inventoryMovementsHasMore: false,
};

form.addEventListener("submit", (event) => {
  event.preventDefault();
  state.search = searchInput.value.trim();
  state.category = categorySelect.value;
  state.page = 1;
  loadCatalog();
});

categorySelect.addEventListener("change", () => {
  state.category = categorySelect.value;
  state.page = 1;
  loadCatalog();
});

previousButton.addEventListener("click", () => {
  if (state.page > 1) {
    state.page -= 1;
    loadCatalog();
  }
});

nextButton.addEventListener("click", () => {
  if (state.hasMore) {
    state.page += 1;
    loadCatalog();
  }
});

clearCartButton.addEventListener("click", clearCart);
proceedButton.addEventListener("click", openCheckout);
document.querySelector("#cancel-checkout").addEventListener("click", () => {
  checkoutSection.hidden = true;
  document.querySelector("#shopping-cart").scrollIntoView({ behavior: "smooth" });
});
checkoutForm.addEventListener("submit", submitOrder);
checkoutArea.addEventListener("change", refreshDeliveryQuote);
document.querySelector("#refresh-orders").addEventListener("click", () => {
  loadCustomerOrders();
});
document.querySelector("#staff-order-filters").addEventListener("submit", (event) => {
  event.preventDefault();
  const values = new FormData(staffOrderForm);
  state.staffSearch = String(values.get("search") || "").trim();
  state.staffStatus = String(values.get("status") || "");
  loadStaffOrders();
});
document.querySelector("#staff-orders-link").addEventListener("click", () => {
  loadStaffOrders();
});
document.querySelector('a[href="#order-history"]').addEventListener("click", () => {
  loadCustomerOrders();
});
document.querySelector("#inventory-dashboard-link").addEventListener("click", () => {
  loadInventoryDashboard();
  loadStock();
});
inventoryStockFilters.addEventListener("submit", (event) => {
  event.preventDefault();
  state.inventoryPage = 1;
  loadStock();
});
inventoryMovementFilters.addEventListener("submit", (event) => {
  event.preventDefault();
  state.inventoryMovementPage = 1;
  loadStockMovements();
});
inventoryAdjustmentForm.addEventListener("submit", submitStockAdjustment);
inventoryReturnForm.addEventListener("submit", submitStockReturn);

for (const select of document.querySelectorAll(
  '#staff-order-filters select[name="status"]',
)) {
  for (const status of ORDER_STATUSES) {
    select.add(new Option(status, status));
  }
}

async function loadCatalog() {
  statusElement.textContent = "Loading products…";
  productsElement.replaceChildren();
  feedbackElement.hidden = true;
  paginationElement.hidden = true;

  try {
    const result = await get("catalog.get_catalog", {
      search: state.search,
      category: state.category,
      page: String(state.page),
      page_size: "20",
    });

    renderCategories(result.categories);
    state.products = result.products;
    renderProducts(state.products);
    state.hasMore = result.has_more;

    if (result.total === 0) {
      statusElement.textContent = "No products match your search.";
    } else {
      const first = (result.page - 1) * result.page_size + 1;
      const last = first + result.products.length - 1;
      statusElement.textContent = `Showing ${first}–${last} of ${result.total} products.`;
      pageIndicator.textContent = `Page ${result.page}`;
      previousButton.disabled = result.page <= 1;
      nextButton.disabled = !result.has_more;
      paginationElement.hidden = false;
    }
  } catch (error) {
    statusElement.textContent = "Products could not be loaded.";
    showFeedback(feedbackElement, error.message);
  }
}

async function loadCart() {
  state.cartBusy = true;
  renderCart();
  renderProducts(state.products);

  try {
    const guestItems = readGuestCart();
    let result = await post("cart.get_cart", {
      guest_items: JSON.stringify(guestItems),
    });

    if (!result.is_guest) {
      if (guestItems.length > 0) {
        result = await post("cart.merge_guest_cart", {
          guest_items: JSON.stringify(guestItems),
        });
      }
      clearGuestCart();
    } else {
      writeGuestCart(result.items);
    }

    setCart(result);
    state.cartError = false;
    state.cartReady = true;
    showRemovedProducts(result.removed_products);
  } catch (error) {
    state.cartError = true;
    showFeedback(feedbackElement, error.message);
  } finally {
    state.cartBusy = false;
    renderCart();
    renderProducts(state.products);
  }
}

async function addToCart(product) {
  await updateCart("cart.add_item", {
    product: product.name,
    quantity: "1",
  });
}

async function changeQuantity(product, quantity) {
  await updateCart("cart.update_item", {
    product,
    quantity: String(quantity),
  });
}

async function removeFromCart(product) {
  await updateCart("cart.remove_item", { product });
}

async function updateCart(endpoint, parameters) {
  if (!state.cartReady || state.cartBusy) {
    return;
  }

  state.cartBusy = true;
  renderCart();
  renderProducts(state.products);
  feedbackElement.hidden = true;

  try {
    if (state.cart.is_guest) {
      parameters.guest_items = JSON.stringify(
        state.cart.items.map(({ product, quantity }) => ({ product, quantity })),
      );
    }
    const result = await post(endpoint, parameters);
    setCart(result);
    showRemovedProducts(result.removed_products);
  } catch (error) {
    showFeedback(feedbackElement, error.message);
  } finally {
    state.cartBusy = false;
    renderCart();
    renderProducts(state.products);
  }
}

async function clearCart() {
  state.cartBusy = true;
  clearCartButton.disabled = true;
  renderCart();

  try {
    const result = await post("cart.clear_cart");
    clearGuestCart();
    setCart(result);
    state.cartError = false;
    state.cartReady = true;
    feedbackElement.hidden = true;
  } catch (error) {
    if (state.cart.is_guest) {
      try {
        clearGuestCart();
        state.cart = {
          items: [],
          item_count: 0,
          currency: "KES",
          total: 0,
          is_guest: true,
          max_quantity: 9999,
        };
        state.cartReady = true;
        state.cartError = false;
        showFeedback(
          feedbackElement,
          "The browser-saved guest cart was cleared locally, but the server did not respond.",
        );
      } catch (storageError) {
        showFeedback(feedbackElement, storageError.message);
      }
    } else {
      showFeedback(feedbackElement, error.message);
    }
  } finally {
    state.cartBusy = false;
    renderCart();
    renderProducts(state.products);
  }
}

function setCart(cart) {
  state.cart = cart;
  cartCountElement.textContent = String(cart.item_count);
  renderCart();

  if (cart.is_guest) {
    writeGuestCart(cart.items);
  }
}

function renderCategories(categories) {
  const selected = state.category;
  categorySelect.replaceChildren(new Option("All categories", ""));

  for (const category of categories) {
    categorySelect.add(new Option(category.category_name, category.name));
  }

  categorySelect.value = selected;
}

function renderProducts(products) {
  const cards = products.map((product) => {
    const card = document.createElement("article");
    card.className = "product-card";

    appendProductImage(card, product.image, product.product_name);

    const heading = document.createElement("h2");
    heading.textContent = product.product_name;
    card.append(heading);

    const sku = document.createElement("p");
    sku.className = "product-sku";
    sku.textContent = `SKU: ${product.sku}`;
    card.append(sku);

    if (product.category) {
      const category = document.createElement("p");
      category.className = "product-category";
      category.textContent = product.category;
      card.append(category);
    }

    if (product.description) {
      const description = document.createElement("p");
      description.className = "product-description";
      description.textContent = product.description;
      card.append(description);
    }

    const price = document.createElement("p");
    price.className = "product-price";
    price.textContent = formatPrice(product.price, product.currency);
    card.append(price);

    const stock = document.createElement("p");
    const availableQuantity = Number(product.available_quantity || 0);
    stock.className = availableQuantity > 0 ? "stock-available" : "stock-unavailable";
    stock.textContent = availableQuantity > 0
      ? `${availableQuantity} available`
      : "Out of stock";
    card.append(stock);

    const addButton = document.createElement("button");
    addButton.className = "primary-button add-to-cart";
    addButton.type = "button";
    addButton.textContent = "Add to cart";
    addButton.setAttribute("aria-label", `Add ${product.product_name} to cart`);
    addButton.disabled =
      !state.cartReady || state.cartBusy || availableQuantity < 1;
    addButton.addEventListener("click", () => addToCart(product));
    card.append(addButton);
    return card;
  });

  productsElement.replaceChildren(...cards);
}

function renderCart() {
  const cart = state.cart;
  cartCountElement.textContent = String(cart.item_count);
  clearCartButton.disabled = state.cartBusy;

  if (!state.cartReady) {
    cartStatusElement.textContent = state.cartError
      ? "Cart unavailable. Clear saved cart data or reload to try again."
      : "Loading cart…";
  } else if (cart.items.length === 0) {
    cartStatusElement.textContent = "Your cart is empty.";
  } else {
    cartStatusElement.textContent = `${cart.item_count} item${
      cart.item_count === 1 ? "" : "s"
    } in your cart.`;
  }
  clearCartButton.hidden = state.cartReady
    ? cart.items.length === 0
    : !state.cartError;
  proceedButton.disabled =
    !state.cartReady ||
    state.cartBusy ||
    cart.items.length === 0 ||
    cart.items.some((item) => !item.available);

  const rows = cart.items.map((item) => {
    const row = document.createElement("article");
    row.className = "cart-item";

    const product = document.createElement("div");
    product.className = "cart-product";
    appendProductImage(product, item.image, item.product_name);

    const details = document.createElement("div");
    const name = document.createElement("h3");
    name.textContent = item.product_name;
    details.append(name);

    if (item.unit_price !== null) {
      const unitPrice = document.createElement("p");
      unitPrice.textContent = `${formatPrice(item.unit_price, item.currency)} each`;
      details.append(unitPrice);
    }
    if (!item.available) {
      const unavailable = document.createElement("p");
      unavailable.className = "unavailable-label";
      unavailable.textContent =
        item.stock_status === "Unavailable"
          ? "Product unavailable"
          : item.stock_status === "Out of Stock"
            ? "Out of stock"
            : `Only ${item.available_quantity} available`;
      details.append(unavailable);
    }
    product.append(details);
    row.append(product);

    const controls = document.createElement("div");
    controls.className = "product-controls";
    if (item.available || item.quantity > 1) {
      const decrease = quantityButton(
        "−",
        `Decrease ${item.product_name}`,
        item.quantity <= 1 || state.cartBusy,
        () => changeQuantity(item.product, item.quantity - 1),
      );
      const quantity = document.createElement("span");
      quantity.className = "quantity-value";
      quantity.textContent = String(item.quantity);
      quantity.setAttribute("aria-label", `Quantity ${item.quantity}`);
      const increase = quantityButton(
        "+",
        `Increase ${item.product_name}`,
        !item.available ||
          item.quantity >= item.available_quantity ||
          item.quantity >= cart.max_quantity ||
          state.cartBusy,
        () => changeQuantity(item.product, item.quantity + 1),
      );
      controls.append(decrease, quantity, increase);
    }
    const remove = document.createElement("button");
    remove.className = "text-button";
    remove.type = "button";
    remove.textContent = "Remove";
    remove.setAttribute("aria-label", `Remove ${item.product_name} from cart`);
    remove.disabled = state.cartBusy;
    remove.addEventListener("click", () => removeFromCart(item.product));
    controls.append(remove);
    row.append(controls);

    const subtotal = document.createElement("p");
    subtotal.className = "cart-subtotal";
    subtotal.textContent = item.unit_price !== null
      ? formatPrice(item.subtotal, item.currency)
      : "—";
    row.append(subtotal);
    return row;
  });

  cartItemsElement.replaceChildren(...rows);
  cartTotalElement.textContent = formatPrice(cart.total, cart.currency);
}

async function openCheckout() {
  state.deliveryQuoteRequest += 1;
  state.deliveryQuote = null;
  checkoutSection.hidden = false;
  orderConfirmation.hidden = true;
  checkoutForm.hidden = false;
  checkoutStatus.textContent = "Loading your order review…";
  submitOrderButton.disabled = true;
  checkoutSection.scrollIntoView({ behavior: "smooth" });

  try {
    const checkout = await get("checkout.get_checkout");
    if (checkout.requires_login) {
      const returnTo = `${window.location.pathname}#checkout`;
      window.location.assign(
        `/login?redirect-to=${encodeURIComponent(returnTo)}`,
      );
      return;
    }

    state.cart = checkout.cart;
    state.cartReady = true;
    state.checkoutToken ||= crypto.randomUUID();
    state.checkoutRevision = checkout.cart_revision;
    setCart(checkout.cart);
    checkoutForm.elements.customer_name.value = checkout.customer_name || "";
    checkoutForm.elements.phone.value = checkout.phone || "";
    renderOrderItems(checkoutReview, checkout.cart.items, checkout.cart.currency);
    checkoutSubtotal.textContent = formatPrice(
      checkout.cart.total,
      checkout.cart.currency,
    );
    checkoutTotal.textContent = formatPrice(
      checkout.cart.total,
      checkout.cart.currency,
    );
    checkoutArea.replaceChildren(new Option("Select delivery area", ""));
    for (const area of checkout.delivery_areas) {
      checkoutArea.add(new Option(
        `${area.name} - ${formatPrice(area.delivery_fee, area.currency)}`, area.name,
      ));
    }
    checkoutFee.textContent = "Select a delivery area";
    checkoutTotal.textContent = "Select a delivery area to review the total";
    const canSubmit =
      checkout.cart.items.length > 0 &&
      checkout.cart.items.every((item) => item.available);
    checkoutStatus.textContent = canSubmit
      ? (checkout.delivery_areas.length
        ? "Select a delivery area to review the full total."
        : "No delivery areas are configured for this currency. Contact the store.")
      : "Your cart is empty or contains unavailable products.";
    submitOrderButton.disabled = true;
  } catch (error) {
    checkoutStatus.textContent = "Checkout could not be loaded.";
    showFeedback(feedbackElement, error.message);
  }
}

async function refreshDeliveryQuote() {
  const request = ++state.deliveryQuoteRequest;
  state.deliveryQuote = null;
  submitOrderButton.disabled = true;
  if (!checkoutArea.value) {
    checkoutFee.textContent = "Select a delivery area";
    checkoutTotal.textContent = "Select a delivery area to review the total";
    return;
  }
  try {
    const checkout = await get("checkout.get_checkout", { delivery_area: checkoutArea.value });
    if (request !== state.deliveryQuoteRequest) return;
    if (checkout.requires_login) throw new Error("Sign in again before checking out.");
    state.checkoutRevision = checkout.cart_revision;
    state.deliveryQuote = checkout.delivery_quote;
    setCart(checkout.cart);
    renderOrderItems(checkoutReview, checkout.cart.items, checkout.cart.currency);
    checkoutSubtotal.textContent = formatPrice(checkout.cart.total, checkout.cart.currency);
    checkoutFee.textContent = formatPrice(checkout.delivery_fee, checkout.currency);
    checkoutTotal.textContent = formatPrice(checkout.total, checkout.currency);
    const available = checkout.cart.items.length > 0 &&
      checkout.cart.items.every((item) => item.available);
    checkoutStatus.textContent = available
      ? "Review the products, delivery fee and address before placing your order."
      : "Your cart is empty or contains unavailable products.";
    submitOrderButton.disabled = !available;
  } catch (error) {
    if (request !== state.deliveryQuoteRequest) return;
    checkoutFee.textContent = "Unavailable";
    checkoutTotal.textContent = "Refresh the delivery quote before submitting";
    checkoutStatus.textContent = error.message;
  }
}

async function submitOrder(event) {
  event.preventDefault();
  if (state.checkoutBusy || !state.deliveryQuote || !checkoutForm.reportValidity()) {
    return;
  }

  state.checkoutBusy = true;
  checkoutArea.disabled = true;
  submitOrderButton.disabled = true;
  checkoutStatus.textContent = "Submitting your order…";
  feedbackElement.hidden = true;
  try {
    const values = Object.fromEntries(new FormData(checkoutForm));
    const result = await post("checkout.create_order", {
      ...values,
      request_token: state.checkoutToken,
      cart_revision: state.checkoutRevision,
      delivery_area: checkoutArea.value,
      delivery_quote: state.deliveryQuote,
    });

    setCart(result.cart);
    state.cartReady = true;
    state.checkoutToken = null;
    state.checkoutRevision = null;
    checkoutForm.hidden = true;
    checkoutStatus.textContent = result.duplicate
      ? "This checkout request was already completed."
      : "Your order has been placed.";
    renderOrderDetail(orderConfirmation, result.order, false);
    orderConfirmation.hidden = false;
    orderConfirmation.scrollIntoView({ behavior: "smooth" });
    loadCustomerOrders();
  } catch (error) {
    checkoutStatus.textContent = "Your order was not submitted.";
    showFeedback(feedbackElement, error.message);
    submitOrderButton.disabled = false;
  } finally {
    state.checkoutBusy = false;
    checkoutArea.disabled = false;
  }
}

function renderOrderItems(container, items, currency) {
  const rows = items.map((item) => {
    const row = document.createElement("article");
    row.className = "order-item";
    const name = document.createElement("h3");
    name.textContent = item.product_name || "Product";
    row.append(name);

    const details = document.createElement("p");
    details.textContent =
      `${item.quantity} × ${formatPrice(item.unit_price, currency)} each`;
    row.append(details);

    const amount = document.createElement("strong");
    amount.textContent = formatPrice(
      item.subtotal ?? item.line_total,
      currency,
    );
    row.append(amount);
    return row;
  });
  container.replaceChildren(...rows);
}

async function loadCustomerOrders(append = false) {
  const nextPage = append ? state.customerOrderPage + 1 : 1;
  customerOrdersStatus.textContent = "Loading your orders…";
  customerOrdersElement
    .querySelector(".load-more-orders")
    ?.remove();
  if (!append) {
    customerOrdersElement.replaceChildren();
    customerOrderDetail.hidden = true;
  }

  try {
    const result = await get("orders.get_my_orders", {
      page: String(nextPage),
      page_size: "20",
    });
    if (result.requires_login) {
      customerOrdersStatus.textContent = "Sign in to view your orders.";
      state.customerOrdersHasMore = false;
      return;
    }

    state.customerOrderPage = result.page;
    state.customerOrdersHasMore = result.has_more;
    customerOrdersStatus.textContent = result.orders.length
      ? ""
      : "You have not placed any orders yet.";
    appendOrderCards(customerOrdersElement, result.orders, false);
    addMoreOrdersButton(
      customerOrdersElement,
      state.customerOrdersHasMore,
      () => loadCustomerOrders(true),
    );
  } catch (error) {
    customerOrdersStatus.textContent = "Your orders could not be loaded.";
    showFeedback(feedbackElement, error.message);
  }
}

async function loadStaffOrders(append = false) {
  const nextPage = append ? state.staffOrderPage + 1 : 1;
  staffOrdersStatus.textContent = "Loading orders…";
  staffOrdersElement.querySelector(".load-more-orders")?.remove();
  if (!append) {
    staffOrdersElement.replaceChildren();
    staffOrderDetail.hidden = true;
  }

  try {
    const result = await get("orders.list_orders", {
      search: state.staffSearch,
      status: state.staffStatus,
      page: String(nextPage),
      page_size: "20",
    });
    state.staffOrderPage = result.page;
    state.staffOrdersHasMore = result.has_more;
    staffOrdersStatus.textContent = result.orders.length
      ? ""
      : "No orders match these filters.";
    appendOrderCards(staffOrdersElement, result.orders, true);
    addMoreOrdersButton(
      staffOrdersElement,
      state.staffOrdersHasMore,
      () => loadStaffOrders(true),
    );
  } catch (error) {
    staffOrdersStatus.textContent = "Orders could not be loaded.";
    showFeedback(feedbackElement, error.message);
  }
}

function appendOrderCards(container, orders, staffMode) {
  for (const order of orders) {
    const card = document.createElement("article");
    card.className = "order-card";
    const heading = document.createElement("h3");
    heading.textContent = order.name;
    card.append(heading);

    if (staffMode) {
      const customer = document.createElement("p");
      customer.textContent =
        `${order.customer_name_snapshot} · ${order.customer_phone_snapshot}`;
      card.append(customer);
    }

    const summary = document.createElement("p");
    summary.textContent =
      `${order.status} · ${formatDate(order.order_datetime)} · ` +
      formatPrice(order.total, order.currency);
    card.append(summary);

    const viewButton = document.createElement("button");
    viewButton.className = "secondary-button";
    viewButton.type = "button";
    viewButton.textContent = "View details";
    viewButton.addEventListener("click", () => {
      card.append(staffMode ? staffOrderDetail : customerOrderDetail);
      loadOrderDetail(order.name, staffMode);
    });
    card.append(viewButton);
    container.append(card);
  }
}

function addMoreOrdersButton(container, hasMore, action) {
  if (!hasMore) {
    return;
  }
  const button = document.createElement("button");
  button.className = "secondary-button";
  button.classList.add("load-more-orders");
  button.type = "button";
  button.textContent = "Load more orders";
  button.addEventListener("click", action, { once: true });
  container.append(button);
}

async function loadOrderDetail(orderName, staffMode) {
  const target = staffMode ? staffOrderDetail : customerOrderDetail;
  target.hidden = false;
  target.textContent = "Loading order details…";
  try {
    const order = await get("orders.get_order", { order_name: orderName });
    if (order.requires_login) {
      target.textContent = "Sign in to view order details.";
      return;
    }
    renderOrderDetail(target, order, staffMode);
  } catch (error) {
    target.textContent = "Order details could not be loaded.";
    showFeedback(feedbackElement, error.message);
  }
}

function renderOrderDetail(container, order, staffMode) {
  const content = document.createElement("article");
  content.className = "order-detail-card";
  const heading = document.createElement("h3");
  heading.textContent = `Order ${order.name}`;
  content.append(heading);

  const status = document.createElement("p");
  status.textContent = `Status: ${order.status}`;
  content.append(status);

  const date = document.createElement("p");
  date.textContent = `Placed: ${formatDate(order.order_datetime)}`;
  content.append(date);

  if (order.customer_name) {
    const customer = document.createElement("p");
    customer.textContent = `${order.customer_name} · ${order.customer_phone}`;
    content.append(customer);
  }
  if (order.delivery_address) {
    const address = document.createElement("p");
    address.textContent = `Delivery address: ${order.delivery_address}`;
    content.append(address);
  }

  const items = document.createElement("div");
  items.className = "order-items";
  renderOrderItems(items, order.items, order.currency);
  content.append(items);

  const total = document.createElement("p");
  const deliveryFee = document.createElement("p");
  deliveryFee.textContent =
    `Delivery${order.delivery_area ? ` (${order.delivery_area})` : ""}: ` +
    formatPrice(order.delivery_fee || 0, order.currency);
  content.append(deliveryFee);
  total.className = "order-detail-total";
  total.textContent = `Total: ${formatPrice(order.total, order.currency)}`;
  content.append(total);

  if (staffMode) {
    appendStatusForm(content, order);
  } else {
    mountOrderPayment(content, order);
  }
  container.replaceChildren(content);
}

function appendStatusForm(container, order) {
  const allowed = STATUS_TRANSITIONS[order.status] || [];
  const formElement = document.createElement("form");
  formElement.className = "status-update-form";
  const label = document.createElement("label");
  label.textContent = "Update status";
  const select = document.createElement("select");
  select.name = "status";
  select.required = true;
  select.add(new Option(`Current: ${order.status}`, ""));
  for (const status of allowed) {
    select.add(new Option(status, status));
  }
  label.append(select);
  const submit = document.createElement("button");
  submit.className = "primary-button";
  submit.type = "submit";
  submit.textContent = "Save status";
  submit.disabled = allowed.length === 0;
  formElement.append(label, submit);
  formElement.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!formElement.reportValidity()) {
      return;
    }
    submit.disabled = true;
    try {
      const updated = await post("orders.update_order_status", {
        order_name: order.name,
        status: select.value,
      });
      renderOrderDetail(container, updated, true);
      loadStaffOrders();
    } catch (error) {
      showFeedback(feedbackElement, error.message);
      submit.disabled = false;
    }
  });
  container.append(formElement);
}

async function loadInventoryDashboard() {
  inventoryStatus.textContent = "Loading inventory dashboard…";
  try {
    const result = await get("inventory.get_dashboard");
    renderInventorySummary(result.summary);
    inventoryStatus.textContent = "";
    renderMovementRows(inventoryMovements, result.recent_movements);
  } catch (error) {
    inventoryStatus.textContent = "Inventory dashboard could not be loaded.";
    showFeedback(feedbackElement, error.message);
  }
}

function renderInventorySummary(summary) {
  const cards = [
    ["Products", summary.total_products],
    ["Total stock", summary.total_stock],
    ["Available", summary.available_stock],
    ["Reserved", summary.reserved_stock],
    ["Low stock", summary.low_stock_products],
    ["Out of stock", summary.out_of_stock_products],
  ].map(([label, amount]) => {
    const card = document.createElement("article");
    card.className = "inventory-summary-card";
    const title = document.createElement("span");
    title.textContent = label;
    const value = document.createElement("strong");
    value.textContent = String(amount);
    card.append(title, value);
    return card;
  });
  inventorySummary.replaceChildren(...cards);
}

async function loadStock(append = false) {
  const page = append ? state.inventoryPage + 1 : 1;
  const values = new FormData(inventoryStockFilters);
  inventoryStatus.textContent = "Loading stock…";
  inventoryStockList.querySelector(".load-more-orders")?.remove();
  if (!append) {
    inventoryStockList.replaceChildren();
  }

  try {
    const result = await get("inventory.list_stock", {
      search: String(values.get("search") || "").trim(),
      warehouse: String(values.get("warehouse") || ""),
      availability: String(values.get("availability") || "all"),
      page: String(page),
      page_size: "20",
    });
    state.inventoryPage = result.page;
    state.inventoryHasMore = result.has_more;
    setWarehouseOptions(result.warehouses);
    setInventoryProductOptions(result.stock);
    renderStockRows(result.stock);
    inventoryStatus.textContent = result.stock.length ? "" : "No stock records match.";
    if (state.inventoryHasMore) {
      addMoreOrdersButton(inventoryStockList, true, () => loadStock(true));
    }
  } catch (error) {
    inventoryStatus.textContent = "Stock could not be loaded.";
    showFeedback(feedbackElement, error.message);
  }
}

function setWarehouseOptions(warehouses) {
  for (const select of document.querySelectorAll(
    "#inventory-stock-filters select[name='warehouse'], " +
      "#inventory-movement-filters select[name='warehouse'], " +
      "#inventory-adjustment-form select[name='warehouse'], " +
      "#inventory-return-form select[name='warehouse']",
  )) {
    const selected = select.value;
    const form = select.closest("form");
    const isFilter =
      form === inventoryStockFilters || form === inventoryMovementFilters;
    select.replaceChildren(
      new Option(isFilter ? "All warehouses" : "Select warehouse", ""),
    );
    for (const warehouse of warehouses) {
      select.add(new Option(warehouse.warehouse_name, warehouse.name));
    }
    if (warehouses.some((warehouse) => warehouse.name === selected)) {
      select.value = selected;
    }
  }
}

function renderStockRows(rows) {
  for (const row of rows) {
    const card = document.createElement("article");
    card.className = "inventory-stock-row";
    const details = document.createElement("div");
    const heading = document.createElement("h4");
    heading.textContent = `${row.product_name} (${row.sku})`;
    details.append(heading);
    const amounts = document.createElement("p");
    amounts.textContent =
      `${row.warehouse_name || "No warehouse stock"} · ` +
      `On hand ${row.quantity_on_hand} · Reserved ${row.reserved_quantity} · ` +
      `Available ${row.available_quantity}`;
    details.append(amounts);
    card.append(details);

    const useButton = document.createElement("button");
    useButton.className = "secondary-button";
    useButton.type = "button";
    useButton.textContent = "Adjust";
    useButton.disabled = !row.warehouse;
    useButton.addEventListener("click", () => {
      inventoryAdjustmentForm.elements.product.value = row.product;
      inventoryAdjustmentForm.elements.warehouse.value = row.warehouse || "";
      inventoryAdjustmentForm.scrollIntoView({ behavior: "smooth" });
    });
    card.append(useButton);
    inventoryStockList.append(card);
  }
}

function setInventoryProductOptions(rows) {
  const products = new Map(
    rows.map((row) => [row.product, `${row.product_name} (${row.sku})`]),
  );
  for (const select of [
    inventoryAdjustmentForm.elements.product,
    inventoryReturnForm.elements.product,
  ]) {
    const selected = select.value;
    select.replaceChildren(new Option("Select a product", ""));
    for (const [product, label] of products) {
      select.add(new Option(label, product));
    }
    if (products.has(selected)) {
      select.value = selected;
    }
  }
}

async function submitStockAdjustment(event) {
  event.preventDefault();
  if (!inventoryAdjustmentForm.reportValidity()) {
    return;
  }
  const values = new FormData(inventoryAdjustmentForm);
  const transactionType = String(values.get("transaction_type"));
  let quantity = Number(values.get("quantity"));
  if (transactionType === "Adjustment" && values.get("direction") === "decrease") {
    quantity *= -1;
  }
  const submit = inventoryAdjustmentForm.querySelector("button[type='submit']");
  submit.disabled = true;
  try {
    await post("inventory.adjust_stock", {
      product: String(values.get("product")),
      warehouse: String(values.get("warehouse")),
      transaction_type: transactionType,
      quantity: String(quantity),
      remarks: String(values.get("remarks") || ""),
    });
    inventoryAdjustmentForm.reset();
    showFeedback(feedbackElement, "Stock movement recorded.");
    loadInventoryDashboard();
    loadStock();
    loadStockMovements();
  } catch (error) {
    showFeedback(feedbackElement, error.message);
  } finally {
    submit.disabled = false;
  }
}

async function submitStockReturn(event) {
  event.preventDefault();
  if (!inventoryReturnForm.reportValidity()) {
    return;
  }
  const values = new FormData(inventoryReturnForm);
  const submit = inventoryReturnForm.querySelector("button[type='submit']");
  submit.disabled = true;
  try {
    await post("inventory.record_order_return", {
      order_name: String(values.get("order_name")).trim(),
      product: String(values.get("product")),
      warehouse: String(values.get("warehouse")),
      quantity: String(values.get("quantity")),
      remarks: String(values.get("remarks") || ""),
    });
    inventoryReturnForm.reset();
    showFeedback(feedbackElement, "Order stock return recorded.");
    loadInventoryDashboard();
    loadStock();
    loadStockMovements();
  } catch (error) {
    showFeedback(feedbackElement, error.message);
  } finally {
    submit.disabled = false;
  }
}

async function loadStockMovements(append = false) {
  const values = new FormData(inventoryMovementFilters);
  const page = append ? state.inventoryMovementPage + 1 : 1;
  inventoryMovements.querySelector(".load-more-orders")?.remove();
  if (!append) {
    inventoryMovements.replaceChildren();
  }
  try {
    const result = await get("inventory.list_movements", {
      product: String(values.get("product") || "").trim(),
      warehouse: String(values.get("warehouse") || ""),
      transaction_type: String(values.get("transaction_type") || ""),
      page: String(page),
      page_size: "20",
    });
    state.inventoryMovementPage = page;
    state.inventoryMovementsHasMore = result.has_more;
    renderMovementRows(inventoryMovements, result.movements, append);
    if (state.inventoryMovementsHasMore) {
      addMoreOrdersButton(inventoryMovements, true, () => {
        loadStockMovements(true);
      });
    }
  } catch (error) {
    inventoryMovements.textContent = "Stock movements could not be loaded.";
    showFeedback(feedbackElement, error.message);
  }
}

function renderMovementRows(container, movements, append = false) {
  const cards = movements.map((movement) => {
    const card = document.createElement("article");
    card.className = "inventory-movement-row";
    const heading = document.createElement("h4");
    heading.textContent =
      `${movement.transaction_type}: ${movement.product_name || movement.product}`;
    card.append(heading);
    const details = document.createElement("p");
    details.textContent =
      `${movement.warehouse_name || "Legacy location"} · ` +
      `Quantity ${movement.quantity} · On hand change ${movement.quantity_change} · ` +
      `Reserved change ${movement.reserved_change} · ${formatDate(movement.transaction_date)}`;
    card.append(details);
    if (movement.reference_document || movement.remarks) {
      const reference = document.createElement("p");
      reference.textContent = [
        movement.reference_document,
        movement.remarks,
      ].filter(Boolean).join(" · ");
      card.append(reference);
    }
    return card;
  });
  if (append) {
    container.append(...cards);
  } else {
    container.replaceChildren(...cards);
  }
}

function formatDate(value) {
  if (!value) {
    return "Date unavailable";
  }
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString();
}

function quantityButton(label, accessibleName, disabled, action) {
  const button = document.createElement("button");
  button.className = "quantity-button";
  button.type = "button";
  button.textContent = label;
  button.setAttribute("aria-label", accessibleName);
  button.disabled = disabled;
  button.addEventListener("click", action);
  return button;
}

function appendProductImage(container, url, productName) {
  if (url) {
    const image = document.createElement("img");
    image.className = "product-image";
    image.src = url;
    image.alt = productName;
    image.loading = "lazy";
    image.addEventListener("error", () => {
      image.replaceWith(imageFallback());
    }, { once: true });
    container.append(image);
  } else {
    container.append(imageFallback());
  }
}

function imageFallback() {
  const fallback = document.createElement("div");
  fallback.className = "product-image-fallback";
  fallback.textContent = "No image";
  return fallback;
}

function showRemovedProducts(products = []) {
  if (products.length > 0) {
    showFeedback(
      feedbackElement,
      `${products.length} unavailable product${
        products.length === 1 ? " was" : "s were"
      } removed from your cart.`,
    );
  }
}

function formatPrice(amount, currency) {
  const code = currency || "KES";
  try {
    return new Intl.NumberFormat(undefined, {
      style: "currency",
      currency: code,
    }).format(Number(amount));
  } catch {
    return `${code} ${Number(amount).toFixed(2)}`;
  }
}

initPaymentDashboard();
initDeliveryDashboard();
initAdministrationDashboard();
const scriptWarning = document.querySelector("#smarto-page-script-warning");
if (scriptWarning) scriptWarning.hidden = true;
loadCatalog();
if (window.location.hash === "#order-history") {
  loadCustomerOrders();
}
loadCart().then(() => {
  if (window.location.hash === "#checkout") {
    openCheckout();
  }
});
