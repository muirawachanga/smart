import { get, post } from "./api.js";
import { formatPrice, renderOrderItems, text } from "./components/order-display.js";
import { mountOrderPayment } from "./payments.js";

const mode = document.querySelector("[data-orders-page]").dataset.ordersPage;
const staff = mode === "staff" || mode === "support";
const status = document.querySelector("#orders-status");
const list = document.querySelector("#orders-list");
const detail = document.querySelector("#order-detail");
const pagination = document.querySelector("#orders-pagination");
const previous = document.querySelector("#orders-previous");
const next = document.querySelector("#orders-next");
const pageLabel = document.querySelector("#orders-page");
const filters = staff ? document.querySelector("#orders-filters") : null;
const transitions = {
  Pending: ["Confirmed", "Cancelled"],
  Confirmed: ["Processing", "Cancelled"],
  Processing: ["Ready for Delivery", "Cancelled"],
  "Ready for Delivery": ["Cancelled"],
};
let page = 1;
let hasMore = false;
let listRequest = 0;
let detailRequest = 0;

async function loadOrders() {
  const request = ++listRequest;
  status.textContent = "Loading orders...";
  pagination.hidden = true;
  list.replaceChildren();
  const parameters = { page: String(page), page_size: "20" };
  if (staff) {
    parameters.search = filters.elements.search.value;
    parameters.status = filters.elements.status.value;
    parameters.payment_status = filters.elements.payment_status.value;
  }
  try {
    const result = await get(staff ? "orders.list_orders" : "orders.get_my_orders", parameters);
    if (request !== listRequest) return;
    if (result.requires_login) {
      document.querySelector("#orders-login").hidden = false;
      status.textContent = "Sign in to view your orders.";
      return;
    }
    hasMore = result.has_more;
    status.textContent = result.orders.length ? "" : "No orders found.";
    list.replaceChildren(...result.orders.map(orderCard));
    previous.disabled = page <= 1;
    next.disabled = !hasMore;
    pageLabel.textContent = `Page ${page}`;
    pagination.hidden = page === 1 && !hasMore;
  } catch (error) {
    if (request === listRequest) status.textContent = `Orders could not be loaded: ${error.message}`;
  }
}

function orderCard(order) {
  const card = text("article", "", "smarto-order-item");
  card.append(text("h2", order.name));
  if (staff) card.append(text("p", `${order.customer_name_snapshot} · ${order.customer_phone_snapshot}`));
  card.append(text("p", `${order.status} · ${order.order_datetime || ""} · ${formatPrice(order.total, order.currency)}`));
  const button = text("button", "View details", "smarto-button smarto-button-secondary");
  button.type = "button";
  button.addEventListener("click", () => loadDetail(order.name));
  card.append(button);
  return card;
}

async function loadDetail(name) {
  const request = ++detailRequest;
  detail.textContent = "Loading order details...";
  try {
    const order = await get(staff ? "orders.get_order" : "orders.get_my_order", { order_name: name });
    if (request !== detailRequest) return;
    if (order.requires_login) {
      detail.textContent = "Sign in to view order details.";
      return;
    }
    renderDetail(order);
  } catch (error) {
    if (request === detailRequest) detail.textContent = `Order could not be loaded: ${error.message}`;
  }
}

function renderDetail(order) {
  const card = text("article", "", "smarto-order-item");
  card.append(
    text("h2", `Order ${order.name}`),
    text("p", `Order status: ${order.status}`),
    text("p", `Payment status: ${order.payment_status}`),
    text("p", `Customer: ${order.customer_name} · ${order.customer_phone}`),
    text("p", `Delivery address: ${order.delivery_address}`),
  );
  const items = text("div", "", "smarto-cart-items");
  renderOrderItems(items, order.items, order.currency);
  card.append(
    items,
    text("p", `Subtotal: ${formatPrice(order.subtotal, order.currency)}`),
    text("p", `Delivery: ${formatPrice(order.delivery_fee, order.currency)}`),
    text("p", `Total: ${formatPrice(order.total, order.currency)}`),
  );
  if (mode === "staff") addStatusForm(card, order);
  else if (mode === "support") card.append(text("p", "Read-only customer support view."));
  else mountOrderPayment(card, order);
  detail.replaceChildren(card);
}

function addStatusForm(card, order) {
  const allowed = transitions[order.status] || [];
  if (!allowed.length) return;
  const form = document.createElement("form");
  form.className = "smarto-catalog-form";
  const label = text("label", "Update order status");
  const select = document.createElement("select");
  select.required = true;
  select.add(new Option("Select a status", ""));
  for (const value of allowed) select.add(new Option(value, value));
  label.append(select);
  const button = text("button", "Save status", "smarto-button");
  button.type = "submit";
  const feedback = text("p", "");
  feedback.setAttribute("role", "status");
  form.append(label, button);
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!form.reportValidity()) return;
    button.disabled = true;
    const request = detailRequest;
    try {
      const updated = await post("orders.update_order_status", { order_name: order.name, status: select.value });
      if (request === detailRequest) renderDetail(updated);
      loadOrders();
    } catch (error) {
      if (request === detailRequest) {
        feedback.textContent = `Status could not be updated: ${error.message}`;
        button.disabled = false;
      }
    }
  });
  card.append(form, feedback);
}

if (filters) filters.addEventListener("submit", (event) => {
  event.preventDefault();
  page = 1;
  detailRequest += 1;
  detail.replaceChildren();
  loadOrders();
});
previous.addEventListener("click", () => { if (page > 1) { page -= 1; loadOrders(); } });
next.addEventListener("click", () => { if (hasMore) { page += 1; loadOrders(); } });
loadOrders();
