import { get } from "./api.js";
import { formatPrice, text } from "./components/order-display.js";

const page = document.querySelector("[data-role-dashboard]");
if (page) {
  const role = page.dataset.roleDashboard;
  const status = document.querySelector("#role-dashboard-status");
  const feedback = document.querySelector("#role-dashboard-error");
  const refresh = document.querySelector("#role-dashboard-refresh");
  const metricFields = role === "sales"
    ? [
      ["total_sales", "Verified sales", true],
      ["successful_payments", "Successful payments"],
      ["pending_payments", "Pending payments"],
      ["total_orders", "Total orders"],
      ["pending_orders", "Pending orders"],
    ]
    : [
      ["total_sales", "Verified sales", true],
      ["total_orders", "Total orders"],
      ["pending_orders", "Pending orders"],
      ["completed_orders", "Completed orders"],
      ["total_customers", "Customers"],
      ["total_products", "Products"],
      ["successful_payments", "Successful payments"],
      ["pending_payments", "Pending payments"],
    ];

  function renderMetrics(dashboard) {
    const business = dashboard.business || {};
    const metrics = metricFields
      .filter(([key]) => Object.hasOwn(business, key))
      .map(([key, label, currency]) => {
        const card = text("article", "", "smarto-admin-metric");
        card.append(text("span", label), text(
          "strong",
          currency ? formatPrice(business[key], "KES") : business[key],
        ));
        return card;
      });
    document.querySelector("#role-dashboard-metrics").replaceChildren(...metrics);
  }

  function renderBars(selector, rows, labelField, valueField) {
    const container = document.querySelector(selector);
    if (!rows.length) {
      container.replaceChildren(text("p", "No records for this period.", "smarto-empty-state"));
      return;
    }
    const values = rows.map((row) => Math.max(0, Number(row[valueField]) || 0));
    const maximum = Math.max(...values, 1);
    container.replaceChildren(...rows.slice(-8).map((row) => {
      const value = Math.max(0, Number(row[valueField]) || 0);
      const item = text("div", "", "smarto-bar-row");
      const label = text("span", row[labelField] || "Unspecified", "smarto-bar-label");
      const bar = document.createElement("progress");
      bar.max = maximum;
      bar.value = value;
      bar.setAttribute("aria-label", `${label.textContent}: ${formatPrice(value, "KES")}`);
      item.append(label, bar, text("strong", formatPrice(value, "KES")));
      return item;
    }));
  }

  async function load() {
    if (refresh.disabled) return;
    refresh.disabled = true;
    status.textContent = "Refreshing live dashboard data...";
    feedback.textContent = "";
    try {
      const [dashboard, analytics] = await Promise.all([
        get("administration.dashboard"),
        get("administration.sales_analytics"),
      ]);
      renderMetrics(dashboard);
      renderBars("#role-dashboard-daily", analytics.daily, "period", "sales");
      renderBars("#role-dashboard-monthly", analytics.monthly, "period", "sales");
      renderBars("#role-dashboard-products", analytics.by_product, "product_name", "item_sales");
      status.textContent = "Dashboard updated from live SmartO records.";
    } catch (error) {
      status.textContent = "The dashboard could not be refreshed.";
      feedback.textContent = error.message;
    } finally {
      refresh.disabled = false;
    }
  }

  refresh.addEventListener("click", load);
  const warning = document.querySelector("#smarto-page-script-warning");
  if (warning) warning.hidden = true;
  load();
}
