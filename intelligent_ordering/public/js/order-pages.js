import { get, post } from "./api.js";
import { formatPrice, renderOrderItems, text } from "./components/order-display.js";
import { mountOrderPayment } from "./payments.js";
import { FINGERPRINT_KEY, ORDER_KEY, TOKEN_KEY } from "./checkout-recovery.js";

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
  Confirmed: ["Cancelled"],
  Processing: ["Cancelled"],
  "Ready for Delivery": ["Cancelled"],
};
let page = 1;
let hasMore = false;
let listRequest = 0;
let detailRequest = 0;
let trackingTimer = null;
let selectedOrder = null;
const orderCards = new Map();

function clearDetail() {
  selectedOrder = null;
  detailRequest += 1;
  if (trackingTimer !== null) {
    window.clearInterval(trackingTimer);
    trackingTimer = null;
  }
  detail.replaceChildren();
  detail.remove();
}

async function loadOrders() {
  const request = ++listRequest;
  status.textContent = "Loading orders...";
  pagination.hidden = true;
  detail.remove();
  orderCards.clear();
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
      const login = document.querySelector("#orders-login");
      const requestedOrder = new URLSearchParams(window.location.search).get("order");
      if (requestedOrder) {
        login.href = `/login?${new URLSearchParams({
          "redirect-to": `${window.location.pathname}${window.location.search}`,
        })}`;
      }
      login.hidden = false;
      status.textContent = "Sign in to view your orders.";
      return;
    }
    hasMore = result.has_more;
    if (!result.orders.some((order) => order.name === selectedOrder)) clearDetail();
    status.textContent = result.orders.length ? "" : "No orders found.";
    list.replaceChildren(...result.orders.map(orderCard));
    previous.disabled = page <= 1;
    next.disabled = !hasMore;
    pageLabel.textContent = `Page ${page}`;
    pagination.hidden = page === 1 && !hasMore;
    const requestedOrder = new URLSearchParams(window.location.search).get("order");
    if (!selectedOrder && requestedOrder && result.orders.some((order) => order.name === requestedOrder)) {
      await loadDetail(requestedOrder);
    }
  } catch (error) {
    if (request === listRequest) {
      clearDetail();
      status.textContent = `Orders could not be loaded: ${error.message}`;
    }
  }
}

function orderCard(order) {
  const card = text("article", "", "smarto-order-item");
  orderCards.set(order.name, card);
  const heading = text("div", "", "smarto-order-item-heading");
  const badge = text("span", order.status, "smarto-status-badge");
  badge.dataset.status = order.status.toLowerCase().replaceAll(" ", "-");
  heading.append(text("h2", order.name), badge);
  card.append(heading);
  if (staff) card.append(text("p", `${order.customer_name_snapshot} · ${order.customer_phone_snapshot}`));
  card.append(text("p", `${order.status} · ${order.order_datetime || ""} · ${formatPrice(order.total, order.currency)}`));
  const button = text("button", "View details", "smarto-button smarto-button-secondary");
  button.type = "button";
  button.addEventListener("click", () => loadDetail(order.name));
  card.append(button);
  if (selectedOrder === order.name) card.append(detail);
  return card;
}

async function loadDetail(name) {
  selectedOrder = name;
  const selectedCard = orderCards.get(name);
  if (selectedCard) selectedCard.append(detail);
  else list.prepend(detail);
  if (trackingTimer !== null) {
    window.clearInterval(trackingTimer);
    trackingTimer = null;
  }
  const request = ++detailRequest;
  detail.textContent = "Loading order details...";
  try {
    const order = await get(staff ? "orders.get_order" : "orders.get_my_order", { order_name: name });
    if (request !== detailRequest) return;
    if (order.requires_login) {
      detail.textContent = "Sign in to view order details.";
      return;
    }
    if (!staff) {
      try {
        if (sessionStorage.getItem(ORDER_KEY) === order.name) {
          sessionStorage.removeItem(TOKEN_KEY);
          sessionStorage.removeItem(ORDER_KEY);
          sessionStorage.removeItem(FINGERPRINT_KEY);
        }
      } catch (error) {
        console.error("Could not clear the completed checkout recovery state:", error);
      }
    }
    renderDetail(order);
  } catch (error) {
    if (request === detailRequest) detail.textContent = `Order could not be loaded: ${error.message}`;
  }
}

function renderDetail(order) {
  const card = text("article", "", "smarto-order-item");
  const orderStatus = text("p", `Order status: ${order.status}`);
  const paymentStatus = text("p", `Payment status: ${order.payment_status}`);
  card.append(
    text("h2", `Order ${order.name}`),
    orderStatus,
    paymentStatus,
    text("p", `Customer: ${order.customer_name} · ${order.customer_phone}`),
    text("p", `Delivery address: ${order.delivery_address}`),
    text("p", `Delivery area: ${order.delivery_area || "Not specified"}`),
  );
  const items = text("div", "", "smarto-cart-items");
  renderOrderItems(items, order.items, order.currency);
  card.append(
    items,
    text("p", `Subtotal: ${formatPrice(order.subtotal, order.currency)}`),
    text("p", `Delivery: ${formatPrice(order.delivery_fee, order.currency)}`),
    text("p", `Total: ${formatPrice(order.total, order.currency)}`),
  );
  if (mode === "staff") {
    addStatusForm(card, order);
    addCancellationReview(card, order);
  }
  else if (mode === "support") {
    card.append(text("p", "Read-only customer support view."));
    if (order.cancellation_request_status) card.append(text("p",
      `Cancellation: ${order.cancellation_request_status} · ${order.cancellation_reason || ""} · ${order.cancellation_response || ""}`));
  }
  else {
    const updatePayment = mountOrderPayment(card, order);
    addCustomerTracking(card, order, (result) => {
      orderStatus.textContent = `Order status: ${result.order_status}`;
      paymentStatus.textContent = `Payment status: ${result.payment_status}`;
      updatePayment({ status: result.order_status, payment_status: result.payment_status });
    });
  }
  if (staff) {
    card.append(text("h3", "Order history"));
    for (const entry of order.history || []) card.append(text("p",
      `${entry.event_datetime} · ${entry.responsible_user} · ${entry.event_type}: ${entry.details}`));
    if (!order.history?.length) card.append(text("p", "No recorded status changes."));
    for (const delivery of order.deliveries || []) {
      card.append(text("p",
        `${delivery.name} · ${delivery.status} · Rider: ${delivery.assigned_delivery_person || "Unassigned"} · ${delivery.scheduled_delivery_date || "Not scheduled"}`));
    }
    if (mode === "staff" && order.status === "Ready for Delivery") {
      const link = text("a", "Assign or monitor delivery", "smarto-button smarto-button-secondary");
      link.href = "/dashboard/delivery";
      card.append(link);
    }
  }
  detail.replaceChildren(card);
}

function addCustomerTracking(card, order, updateStatus) {
  const request = detailRequest;
  const tracking = text("section", "");
  const state = text("p", "Loading delivery progress...");
  state.setAttribute("role", "status");
  const history = text("div", "");
  const refresh = text("button", "Refresh order status", "smarto-button smarto-button-secondary");
  refresh.type = "button";
  const cancellation = document.createElement("form");
  cancellation.className = "smarto-checkout-form";
  cancellation.hidden = true;
  const label = text("label", "Reason for cancellation request");
  const reason = document.createElement("textarea");
  reason.required = true;
  reason.maxLength = 1000;
  label.append(reason);
  const send = text("button", "Request cancellation", "smarto-button smarto-button-secondary");
  send.type = "submit";
  const feedback = text("p", "");
  feedback.setAttribute("role", "alert");
  cancellation.append(label, send);
  let refreshing = false;

  function display(result) {
    updateStatus(result);
    state.textContent = `Order: ${result.order_status} · Payment: ${result.payment_status} · Delivery: ${result.delivery?.status || "Not assigned"} · Area: ${result.delivery?.delivery_area || "Not specified"} · Rider: ${result.delivery?.assigned_rider || "Not assigned"} · Scheduled: ${result.delivery?.scheduled_delivery_date || "Not scheduled"} · Updated: ${result.delivery?.modified || result.updated_at || ""}`;
    history.replaceChildren(...result.timeline.map((entry) =>
      text("p", `${entry.activity_datetime}: ${entry.from_status || "Created"} → ${entry.to_status}`)));
    cancellation.hidden = ["Requested", "Approved"].includes(result.cancellation_request_status)
      || ["Completed", "Cancelled"].includes(result.order_status);
    if (result.cancellation_request_status) {
      history.append(text("p", `Cancellation request: ${result.cancellation_request_status}. ${result.cancellation_response || "Awaiting staff review."}`));
    }
  }

  async function refreshTracking() {
    if (refreshing || request !== detailRequest) return;
    refreshing = true;
    refresh.disabled = true;
    try {
      const result = await get("customers.track_order", { order_name: order.name });
      if (request === detailRequest) display(result);
    } catch (error) {
      if (request === detailRequest) state.textContent = `Order status could not be refreshed: ${error.message}`;
    } finally {
      refreshing = false;
      refresh.disabled = false;
    }
  }
  refresh.addEventListener("click", refreshTracking);
  cancellation.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (send.disabled || !cancellation.reportValidity()
      || !window.confirm("Submit a cancellation request for staff approval? This will not cancel or refund the order immediately.")) return;
    send.disabled = true;
    feedback.textContent = "";
    try {
      const result = await post("customers.request_cancellation", { order_name: order.name, reason: reason.value });
      if (request === detailRequest) {
        display(result);
        feedback.textContent = "Cancellation requested. Staff must approve it; no payment has been refunded.";
      }
    } catch (error) {
      if (request === detailRequest) feedback.textContent = `Request could not be submitted: ${error.message}`;
    } finally {
      send.disabled = false;
    }
  });
  tracking.append(text("h3", "Live order progress"), state, refresh, history, cancellation, feedback);
  card.append(tracking);
  refreshTracking();
  trackingTimer = window.setInterval(() => {
    if (!document.hidden) refreshTracking();
  }, 15000);
}

function addCancellationReview(card, order) {
  if (!order.cancellation_request_status) return;
  card.append(text("p", `Cancellation request: ${order.cancellation_request_status} · ${order.cancellation_reason}`));
  if (order.cancellation_request_status !== "Requested" || ["Completed", "Cancelled"].includes(order.status)) return;
  const form = document.createElement("form");
  form.className = "smarto-checkout-form";
  const decision = document.createElement("select");
  decision.add(new Option("Approve cancellation", "Approved"));
  decision.add(new Option("Reject cancellation", "Rejected"));
  const response = document.createElement("textarea");
  response.required = true;
  response.maxLength = 1000;
  const label = text("label", "Response to customer");
  label.append(response);
  const save = text("button", "Resolve cancellation request", "smarto-button");
  save.type = "submit";
  const feedback = text("p", "");
  feedback.setAttribute("role", "alert");
  form.append(decision, label, save, feedback);
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (save.disabled || !form.reportValidity() || !window.confirm(`${decision.value} cancellation? Stock and delivery rules still apply; this does not issue a refund.`)) return;
    save.disabled = true;
    const request = detailRequest;
    try {
      const updated = await post("customers.resolve_cancellation", {
        order_name: order.name, decision: decision.value, response: response.value,
      });
      if (request === detailRequest) renderDetail(updated);
      loadOrders();
      loadOrderOverview();
    } catch (error) {
      feedback.textContent = error.message;
      save.disabled = false;
    }
  });
  card.append(form);
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
      if (request === detailRequest) await loadDetail(updated.name);
      loadOrders();
      loadOrderOverview();
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
  clearDetail();
  loadOrders();
});
previous.addEventListener("click", () => { if (page > 1) { page -= 1; loadOrders(); } });
next.addEventListener("click", () => { if (hasMore) { page += 1; loadOrders(); } });
const warning = document.querySelector("#smarto-page-script-warning");
if (warning) warning.hidden = true;
loadOrders().then(() => {
  const requestedOrder = new URLSearchParams(window.location?.search || "").get("order");
  if (staff && requestedOrder) loadDetail(requestedOrder);
});
const overview = document.querySelector("#order-workspace-metrics");
function loadOrderOverview() {
  if (!overview) return;
  get("orders.order_overview").then((result) => {
    const counts = new Map(result.statuses.map((row) => [row.status, row.count]));
    overview.replaceChildren(...["Pending", "Confirmed", "Processing", "Ready for Delivery", "Completed", "Cancelled"]
      .map((value) => {
        const card = text("article", "", "smarto-admin-metric");
        card.append(text("span", value), text("strong", counts.get(value) || 0));
        return card;
      }));
  }).catch((error) => { status.textContent = `Order overview could not be loaded: ${error.message}`; });
}
loadOrderOverview();
