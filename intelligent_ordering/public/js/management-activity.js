import { get } from "./api.js";
import { formatPrice, text } from "./components/order-display.js";

if (document.querySelector("[data-management-activity]")) {
  const feedback = document.querySelector("#management-activity-feedback");
  const refresh = document.querySelector("#management-activity-refresh");
  function display(selector, rows, render, empty) {
    const container = document.querySelector(selector);
    container.replaceChildren(...rows.map(render));
    if (!rows.length) container.append(text("p", empty, "smarto-empty-state"));
  }
  async function load() {
    if (refresh.disabled) return;
    refresh.disabled = true;
    feedback.textContent = "Loading operational records...";
    try {
      const result = await get("administration.management_activity");
      display("#management-inventory-alerts", result.inventory_alerts,
        (row) => text("p", `${row.product_name} (${row.sku}) · ${row.available} available`),
        "No low or out-of-stock products.");
      display("#management-product-performance", result.products,
        (row) => text("p", `${row.product_name} · ${row.units_sold} units · ${row.orders} paid orders · ${formatPrice(row.item_sales, row.currency)}`),
        "No product performance records.");
      const delivery = result.delivery;
      display("#management-delivery-performance", delivery.personnel_performance,
        (row) => text("p", `${row.rider} · ${row.completed} completed · ${row.failed} failed · ${row.total} total`),
        "No rider performance records.");
      document.querySelector("#management-delivery-performance").prepend(
        text("p", `${delivery.completion_rate}% completed · ${delivery.delayed_deliveries} delayed · ${delivery.available_riders} available riders`));
      display("#management-staff-activity", result.events,
        (row) => text("p", `${row.event_datetime} · ${row.responsible_user} · ${row.event_type} · ${row.reference_name}: ${row.details}`),
        "No staff activity recorded.");
      feedback.textContent = "Operations updated from live records.";
    } catch (error) {
      feedback.textContent = `Operations could not be loaded: ${error.message}`;
    } finally {
      refresh.disabled = false;
    }
  }
  refresh.addEventListener("click", load);
  load();
}
