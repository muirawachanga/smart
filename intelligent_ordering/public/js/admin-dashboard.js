import { get } from "./api.js";
import { formatPrice, text } from "./components/order-display.js";

const page = document.querySelector("[data-admin-dashboard]");
if (page) {
  const status = document.querySelector("#admin-dashboard-status");
  const feedback = document.querySelector("#admin-dashboard-error");
  const refresh = document.querySelector("#admin-dashboard-refresh");

  function badge(value) {
    const node = text("span", value || "Unknown", "smarto-status-badge");
    node.dataset.status = String(value || "").toLowerCase().replaceAll(" ", "-");
    return node;
  }

  function table(container, columns, rows, emptyMessage) {
    if (!rows.length) {
      container.replaceChildren(text("p", emptyMessage, "smarto-empty-state"));
      return;
    }
    const wrapper = document.createElement("table");
    wrapper.className = "smarto-data-table";
    const head = document.createElement("thead");
    const header = document.createElement("tr");
    for (const column of columns) {
      const cell = text("th", column.label);
      cell.scope = "col";
      header.append(cell);
    }
    head.append(header);
    const body = document.createElement("tbody");
    for (const row of rows) {
      const line = document.createElement("tr");
      for (const column of columns) {
        const cell = document.createElement("td");
        const value = column.render ? column.render(row) : row[column.key];
        if (value instanceof Node) cell.append(value);
        else cell.textContent = value == null ? "" : String(value);
        line.append(cell);
      }
      body.append(line);
    }
    wrapper.append(head, body);
    container.replaceChildren(wrapper);
  }

  function renderMetrics(dashboard) {
    const business = dashboard.business || {};
    const inventory = dashboard.inventory || {};
    const delivery = dashboard.delivery || {};
    const metrics = [
      ["total_sales", "Verified sales", "currency"],
      ["total_orders", "Total orders"],
      ["pending_orders", "Pending orders"],
      ["completed_orders", "Completed orders"],
      ["total_customers", "Customers"],
      ["total_products", "Products"],
      ["successful_payments", "Successful payments"],
      ["pending_payments", "Pending payments"],
      ["low_stock_products", "Low-stock products", null, inventory],
      ["out_of_stock_products", "Out of stock", null, inventory],
      ["pending_deliveries", "Pending deliveries", null, delivery],
      ["dispatched_deliveries", "In transit", null, delivery],
    ];
    const container = document.querySelector("#admin-dashboard-metrics");
    container.replaceChildren(...metrics
      .filter(([key, , , source]) => Object.hasOwn(source || business, key))
      .map(([key, label, type, source]) => {
        const values = source || business;
        const card = text("article", "", "smarto-admin-metric");
        card.append(text("span", label), text(
          "strong",
          type === "currency" ? formatPrice(values[key], "KES") : values[key],
        ));
        return card;
      }));
  }

  function renderBars(selector, rows, labelField, valueField, currency = true) {
    const container = document.querySelector(selector);
    if (!rows.length) {
      container.replaceChildren(text("p", "No records for this period.", "smarto-empty-state"));
      return;
    }
    const values = rows.map((row) => Math.max(0, Number(row[valueField]) || 0));
    const maximum = Math.max(...values, 1);
    const visible = rows.slice(-8);
    container.replaceChildren(...visible.map((row) => {
      const value = Math.max(0, Number(row[valueField]) || 0);
      const item = text("div", "", "smarto-bar-row");
      const label = text("span", row[labelField] || "Unspecified", "smarto-bar-label");
      const bar = document.createElement("progress");
      bar.max = maximum;
      bar.value = value;
      bar.setAttribute("aria-label", `${label.textContent}: ${
        currency ? formatPrice(value, "KES") : value
      }`);
      const amount = text("strong", currency ? formatPrice(value, "KES") : value);
      item.append(label, bar, amount);
      return item;
    }));
  }

  function renderOrders(orders) {
    table(document.querySelector("#admin-dashboard-orders"), [
      { key: "name", label: "Order" },
      { key: "customer_name_snapshot", label: "Customer" },
      { label: "Status", render: (order) => badge(order.status) },
      { label: "Total", render: (order) => formatPrice(order.total, order.currency) },
    ], orders, "No orders have been placed.");
  }

  function renderPayments(payments) {
    table(document.querySelector("#admin-dashboard-payments"), [
      { key: "order", label: "Order" },
      { key: "transaction_date", label: "Date" },
      { label: "Status", render: (payment) => badge(payment.status) },
      { label: "Amount", render: (payment) => formatPrice(payment.amount, "KES") },
    ], payments, "No payment transactions are recorded.");
  }

  function renderStock(stockRows) {
    const container = document.querySelector("#admin-dashboard-stock");
    if (!stockRows.length) {
      container.replaceChildren(text("p", "No low or out-of-stock products.", "smarto-empty-state"));
      return;
    }
    container.replaceChildren(...stockRows.map((row) => {
      const item = text("article", "", "smarto-stock-alert");
      const info = text("div", "", "smarto-stock-alert-info");
      info.append(text("h3", row.product_name), text("p", `${row.sku} · ${row.warehouse_name}`));
      item.append(info, badge(Number(row.available_quantity) === 0 ? "Out of stock" : "Low stock"),
        text("strong", `${row.available_quantity} available`));
      return item;
    }));
  }

  async function load() {
    if (refresh.disabled) return;
    refresh.disabled = true;
    status.textContent = "Refreshing live dashboard data...";
    feedback.textContent = "";
    try {
      const [dashboard, analytics, orderResult, paymentResult, lowStock, outOfStock] = await Promise.all([
        get("administration.dashboard"),
        get("administration.sales_analytics"),
        get("orders.list_orders", { page: "1", page_size: "5" }),
        get("payments.list_transactions", { page: "1", page_size: "5" }),
        get("inventory.list_stock", { availability: "low", page: "1", page_size: "5" }),
        get("inventory.list_stock", { availability: "out_of_stock", page: "1", page_size: "5" }),
      ]);
      renderMetrics(dashboard);
      renderBars("#admin-dashboard-daily", analytics.daily, "period", "sales");
      renderBars("#admin-dashboard-monthly", analytics.monthly, "period", "sales");
      renderBars("#admin-dashboard-products", analytics.by_product, "product_name", "item_sales");
      renderOrders(orderResult.orders);
      renderPayments(paymentResult.transactions);
      renderStock([...outOfStock.stock, ...lowStock.stock]);
      status.textContent = "Dashboard updated from live SmartO records.";
    } catch (error) {
      status.textContent = "The dashboard could not be refreshed.";
      feedback.textContent = error.message;
    } finally {
      refresh.disabled = false;
    }
  }

  refresh.addEventListener("click", load);
  load();
}
