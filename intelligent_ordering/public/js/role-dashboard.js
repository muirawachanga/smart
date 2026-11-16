import { get } from "./api.js";
import { formatPrice, text } from "./components/order-display.js";
import { initPaymentDashboard } from "./payments.js";

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

  async function loadFinance() {
    const container = document.querySelector("#finance-overview-metrics");
    if (!container) return;
    const result = await get("payments.finance_overview");
    const currencies = new Map(result.payments.map((row) => [row.currency, { ...row }]));
    for (const row of result.outstanding) {
      currencies.set(row.currency, { ...currencies.get(row.currency), ...row });
    }
    const fields = [
      ["collected", "Total collected / verified sales"], ["pending", "Pending payment attempts"],
      ["failed", "Failed payment attempts"], ["reversed", "Reversed payments"],
      ["outstanding", "Outstanding order balances"], ["daily_revenue", "Today's revenue"],
      ["weekly_revenue", "This week's revenue"], ["monthly_revenue", "This month's revenue"],
    ];
    container.replaceChildren(...[...currencies].flatMap(([currency, values]) =>
      fields.map(([key, label]) => {
        const card = text("article", "", "smarto-admin-metric");
        card.append(text("span", `${label} (${currency})`), text("strong", formatPrice(values[key] || 0, currency)));
        return card;
      })));
    if (!currencies.size) container.append(text("p", "No financial records yet.", "smarto-empty-state"));
    const methods = document.querySelector("#finance-method-report");
    if (methods) {
      methods.replaceChildren(...result.methods.map((row) =>
        text("p", `${row.payment_method} · ${row.status} · ${row.currency}: ${row.transactions} transactions · ${formatPrice(row.amount, row.currency)}`)));
      if (!result.methods.length) methods.append(text("p", "No payment method records.", "smarto-empty-state"));
    }
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
      if (document.querySelector("#role-dashboard-weekly")) {
        renderBars("#role-dashboard-weekly", analytics.weekly, "period", "sales");
      }
      await loadFinance();
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
if (document.querySelector("[data-finance-workspace]")) initPaymentDashboard();
