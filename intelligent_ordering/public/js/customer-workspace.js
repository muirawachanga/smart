import { get } from "./api.js";
import { formatPrice, text } from "./components/order-display.js";

if (document.querySelector("[data-customer-workspace]")) {
  const form = document.querySelector("#customer-workspace-search");
  const feedback = document.querySelector("#customer-workspace-feedback");
  const results = document.querySelector("#customer-workspace-results");
  const detail = document.querySelector("#customer-workspace-detail");
  const previous = document.querySelector("#customer-workspace-previous");
  const next = document.querySelector("#customer-workspace-next");
  const historyPrevious = document.querySelector("#customer-history-previous");
  const historyNext = document.querySelector("#customer-history-next");
  const historyPagination = document.querySelector("#customer-history-pagination");
  let page = 1;
  let historyPage = 1;
  let customer = "";
  let listRequest = 0;
  let detailRequest = 0;

  async function loadHistory(name) {
    const request = ++detailRequest;
    customer = name;
    detail.textContent = "Loading customer history...";
    historyPagination.hidden = true;
    try {
      const result = await get("administration.customer_activity", {
        customer: name, page: String(historyPage),
      });
      if (request !== detailRequest) return;
      const profile = result.customer;
      detail.replaceChildren(text("h3", profile.full_name),
        text("p", `${profile.name} · ${profile.phone || "No phone"} · ${profile.email || "No email"} · ${profile.enabled ? "Active" : "Disabled"}`));
      for (const order of result.orders) {
        const card = text("article", "", "smarto-order-item");
        const link = text("a", "View order", "smarto-button smarto-button-secondary");
        const support = document.querySelector("[data-orders-page]")?.dataset.ordersPage === "support";
        link.href = `${support ? "/dashboard/support" : "/dashboard/orders"}?order=${encodeURIComponent(order.name)}`;
        card.append(text("h4", order.name),
          text("p", `${order.order_datetime} · ${order.status} · Payment: ${order.payment_status} · ${formatPrice(order.total, order.currency)}`), link);
        detail.append(card);
      }
      if (!result.orders.length) detail.append(text("p", "No orders for this customer."));
      historyPrevious.disabled = historyPage === 1;
      historyNext.disabled = !result.has_more;
      historyPagination.hidden = historyPage === 1 && !result.has_more;
    } catch (error) {
      if (request === detailRequest) detail.textContent = `Customer history could not be loaded: ${error.message}`;
    }
  }

  async function load() {
    const request = ++listRequest;
    feedback.textContent = "Loading customers...";
    try {
      const result = await get("administration.list_customers", {
        search: form.elements.search.value, page: String(page),
      });
      if (request !== listRequest) return;
      results.replaceChildren(...result.customers.map((profile) => {
        const card = text("article", "", "smarto-order-item");
        const view = text("button", "View profile and orders", "smarto-button smarto-button-secondary");
        view.type = "button";
        view.addEventListener("click", () => { historyPage = 1; loadHistory(profile.name); });
        card.append(text("h3", profile.full_name),
          text("p", `${profile.phone || "No phone"} · ${profile.email || "No email"} · ${profile.total_orders} orders`), view);
        return card;
      }));
      previous.disabled = page === 1;
      next.disabled = !result.has_more;
      feedback.textContent = result.customers.length ? "" : "No matching customers.";
    } catch (error) {
      if (request === listRequest) {
        results.replaceChildren();
        detailRequest += 1;
        detail.replaceChildren();
        historyPagination.hidden = true;
        feedback.textContent = `Customers could not be loaded: ${error.message}`;
      }
    }
  }
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    page = 1;
    detailRequest += 1;
    detail.replaceChildren();
    historyPagination.hidden = true;
    load();
  });
  previous.addEventListener("click", () => { if (page > 1) { page -= 1; load(); } });
  next.addEventListener("click", () => { if (!next.disabled) { page += 1; load(); } });
  historyPrevious.addEventListener("click", () => { if (historyPage > 1) { historyPage -= 1; loadHistory(customer); } });
  historyNext.addEventListener("click", () => { if (!historyNext.disabled) { historyPage += 1; loadHistory(customer); } });
  load();
}
