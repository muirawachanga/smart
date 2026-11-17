import { get, post } from "./api.js";

function text(tag, value) {
  const element = document.createElement(tag);
  element.textContent = value == null ? "" : String(value);
  return element;
}

function action(label, callback, className = "secondary-button") {
  const element = text("button", label);
  element.className = className;
  element.type = "button";
  element.addEventListener("click", async () => {
    if (element.disabled) return;
    element.disabled = true;
    try {
      await callback();
    } catch (error) {
      document.querySelector("#admin-feedback").textContent = error.message;
    } finally {
      element.disabled = false;
    }
  });
  return element;
}

function setMetrics(container, values, names) {
  container.replaceChildren(...names
    .filter(([key]) => Object.hasOwn(values || {}, key))
    .map(([key, label]) => {
      const card = document.createElement("article");
      card.className = "admin-metric";
      const value = key === "total_sales" ? formatCurrency(values[key]) : values[key];
      card.append(text("span", label), text("strong", value));
      return card;
    }));
  if (!container.childElementCount) {
    container.append(text("p", "This role has no access to these metrics."));
  }
}

function formatCurrency(value, currency = "KES") {
  const amount = Number(value || 0);
  return `${currency} ${Number.isFinite(amount) ? amount.toLocaleString(undefined, {
    minimumFractionDigits: 2, maximumFractionDigits: 2,
  }) : "0.00"}`;
}

function safeNumber(value) {
  const number = Number(value);
  return Number.isFinite(number) ? number : 0;
}

function drawChart(canvas, rows, labelField, valueField, currency = true, hoveredIndex = -1) {
  const width = Math.max(canvas.clientWidth || 320, 260);
  const height = 190;
  const scale = window.devicePixelRatio || 1;
  canvas.width = width * scale;
  canvas.height = height * scale;
  canvas.style.width = "100%";
  canvas.style.height = `${height}px`;
  const context = canvas.getContext("2d");
  if (!context) return;
  context.scale(scale, scale);
  context.clearRect(0, 0, width, height);
  const values = rows.map((row) => safeNumber(row[valueField]));
  const maximum = values.reduce((max, value) => Math.max(max, value), 0);
  const chartRows = rows.slice(-Math.max(1, Math.floor(width / 58)));
  const chartValues = chartRows.map((row) => safeNumber(row[valueField]));
  const chartMax = chartValues.reduce((max, value) => Math.max(max, value), 0);
  const left = 44;
  const top = 14;
  const bottom = height - 31;
  const chartWidth = Math.max(1, width - left - 12);
  context.font = "11px system-ui, sans-serif";
  context.fillStyle = "#526078";
  context.strokeStyle = "#dce3ed";
  context.beginPath();
  context.moveTo(left, top);
  context.lineTo(left, bottom);
  context.lineTo(width - 8, bottom);
  context.stroke();
  if (!chartRows.length || maximum <= 0) {
    context.fillText("No matching verified sales", left + 6, top + 24);
    return;
  }
  const slot = chartWidth / chartRows.length;
  const barWidth = Math.max(3, Math.min(34, slot * 0.62));
  chartRows.forEach((row, index) => {
    const value = chartValues[index];
    const barHeight = (value / chartMax) * Math.max(1, bottom - top - 8);
    const x = left + index * slot + (slot - barWidth) / 2;
    const y = bottom - barHeight;
    context.fillStyle = index === hoveredIndex ? "#174d80" : "#2671b8";
    context.fillRect(x, y, barWidth, barHeight);
    context.fillStyle = "#526078";
    const label = String(row[labelField] || "").slice(-9);
    context.save();
    context.translate(x + barWidth / 2, bottom + 12);
    context.rotate(-0.25);
    context.textAlign = "center";
    context.fillText(label, 0, 0);
    context.restore();
  });
  context.textAlign = "left";
  context.fillStyle = "#172033";
  context.fillText(currency ? formatCurrency(chartMax) : String(chartMax), 4, top + 8);
}

function renderChart(name, rows, labelField, valueField, currency = true) {
  const canvas = document.querySelector(`#chart-${name}`);
  const table = document.querySelector(`#table-${name}`);
  const values = rows || [];
  let hoveredIndex = -1;
  const visibleRows = () => {
    const width = Math.max(canvas.clientWidth || 320, 260);
    return values.slice(-Math.max(1, Math.floor(width / 58)));
  };
  const draw = () => drawChart(canvas, values, labelField, valueField, currency, hoveredIndex);
  const showValue = (index) => {
    const chartRows = visibleRows();
    hoveredIndex = chartRows.length ? (index + chartRows.length) % chartRows.length : -1;
    const row = chartRows[hoveredIndex];
    canvas.title = row
      ? `${row[labelField]}: ${currency ? formatCurrency(row[valueField]) : row[valueField]}`
      : "";
    canvas.setAttribute("aria-valuetext", canvas.title);
    draw();
  };
  draw();
  canvas.tabIndex = 0;
  canvas.onpointermove = (event) => {
    const rect = canvas.getBoundingClientRect();
    const width = Math.max(canvas.clientWidth || 320, 260);
    const left = 44;
    const count = visibleRows().length;
    if (!count) return;
    const slot = Math.max(1, width - left - 12) / count;
    const index = Math.floor((event.clientX - rect.left - left) / slot);
    if (index >= 0 && index < count && index !== hoveredIndex) showValue(index);
  };
  canvas.onpointerleave = () => {
    hoveredIndex = -1;
    canvas.title = "";
    canvas.setAttribute("aria-valuetext", "");
    draw();
  };
  canvas.onkeydown = (event) => {
    if (event.key === "ArrowRight" || event.key === "ArrowLeft") {
      event.preventDefault();
      const direction = event.key === "ArrowRight" ? 1 : -1;
      const start = direction > 0 ? 0 : visibleRows().length - 1;
      showValue(hoveredIndex < 0 ? start : hoveredIndex + direction);
    }
  };
  if (!values.length) {
    table.replaceChildren(text("p", "No records for the selected filters."));
    return;
  }
  const list = document.createElement("ul");
  for (const row of values.slice(0, 10)) {
    list.append(text("li", `${row[labelField]}: ${
      currency ? formatCurrency(row[valueField]) : row[valueField]
    }`));
  }
  table.replaceChildren(list);
}

function fillOptions(select, rows, labelField) {
  const first = select.options[0]?.cloneNode(true);
  select.replaceChildren();
  if (first) select.append(first);
  for (const row of rows) {
    select.add(new Option(`${row[labelField]} (${row.name})`, row.name));
  }
}

export function initAdministrationDashboard() {
  const feedback = document.querySelector("#admin-feedback");
  const analyticsForm = document.querySelector("#sales-analytics-filters");
  const reportForm = document.querySelector("#admin-report-filters");
  const orderForm = document.querySelector("#admin-order-filters");
  const customerForm = document.querySelector("#admin-customer-search");
  const productForm = document.querySelector("#admin-product-search");
  const auditForm = document.querySelector("#admin-audit-search");
  let selectedCustomer = "";
  let customerActivityPage = 1;
  let customerActivityHasMore = false;
  let orderPage = 1;
  let customerPage = 1;
  let productPage = 1;
  let auditPage = 1;
  let filterOptions = { products: [], categories: [] };
  let access = {};

  async function loadDashboard() {
    const result = await get("administration.dashboard");
    access = result.access || {};
    for (const link of document.querySelectorAll("[data-admin-access]")) {
      const groups = link.dataset.adminAccess.split(/\s+/);
      link.hidden = !groups.some((group) => access[group]);
    }
    for (const [selector, allowed] of [
      ["#business-metrics-heading", access.store || access.finance],
      ["#sales-analytics-filters", access.finance],
      ["#admin-orders-heading", access.store],
      ["#admin-customers-heading", access.store],
      ["#admin-products-heading", access.store],
      ["#report-export-heading", access.store || access.finance || access.payment_export
        || access.inventory || access.delivery],
      ["#admin-audit-search", access.audit],
      ["#inventory-metrics-heading", access.inventory],
      ["#delivery-metrics-heading", access.delivery],
    ]) {
      document.querySelector(selector).closest(".admin-panel, section").hidden = !allowed;
    }
    setMetrics(document.querySelector("#admin-business-metrics"), result.business, [
      ["total_sales", "Verified sales"],
      ["total_orders", "Total orders"],
      ["total_customers", "Customers"],
      ["total_products", "Total products"],
      ["successful_payments", "Successful payments"],
      ["pending_payments", "Pending payments"],
      ["pending_orders", "Pending orders"],
      ["completed_orders", "Completed orders"],
      ["cancelled_orders", "Cancelled orders"],
    ]);
    setMetrics(document.querySelector("#admin-inventory-metrics"), result.inventory, [
      ["total_stock", "Total stock quantity"],
      ["available_stock", "Available stock"],
      ["reserved_stock", "Reserved stock"],
      ["low_stock_products", "Low-stock products (≤5)"],
      ["out_of_stock_products", "Out-of-stock products"],
    ]);
    setMetrics(document.querySelector("#admin-delivery-metrics"), result.delivery, [
      ["pending_deliveries", "Pending deliveries"],
      ["assigned_deliveries", "Assigned / preparing"],
      ["dispatched_deliveries", "Dispatched / in transit"],
      ["completed_deliveries", "Delivered"],
      ["failed_deliveries", "Failed deliveries"],
    ]);
  }

  async function loadOptions() {
    filterOptions = await get("administration.filter_options");
    for (const selector of [
      '#sales-analytics-filters select[name="product"]',
      '#admin-report-filters select[name="product"]',
    ]) fillOptions(document.querySelector(selector), filterOptions.products, "product_name");
    for (const selector of [
      '#sales-analytics-filters select[name="category"]',
      '#admin-report-filters select[name="category"]',
      '#admin-product-search select[name="category"]',
    ]) fillOptions(document.querySelector(selector), filterOptions.categories, "category_name");
  }

  async function loadAnalytics() {
    const submit = analyticsForm.querySelector('button[type="submit"]');
    submit.disabled = true;
    try {
      const filters = Object.fromEntries(new FormData(analyticsForm));
      const data = await get("administration.sales_analytics", filters);
      renderChart("daily", data.daily, "period", "sales");
      renderChart("weekly", data.weekly, "period", "sales");
      renderChart("monthly", data.monthly, "period", "sales");
      renderChart("yearly", data.yearly, "period", "sales");
      renderChart("by-product", data.by_product, "product_name", "item_sales");
      renderChart("by-category", data.by_category, "category", "item_sales");
      renderChart("by-delivery-area", data.by_delivery_area, "delivery_area", "sales");
    } finally {
      submit.disabled = false;
    }
  }

  async function loadOrders() {
    const values = Object.fromEntries(new FormData(orderForm));
    const result = await get("orders.list_orders", {
      ...values, page: String(orderPage), page_size: "20",
    });
    document.querySelector("#admin-orders-previous").disabled = orderPage <= 1;
    document.querySelector("#admin-orders-next").disabled = !result.has_more;
    const list = document.querySelector("#admin-orders");
    list.replaceChildren(...result.orders.map((order) => {
      const card = document.createElement("article");
      card.className = "order-card";
      card.append(text("h4", order.name),
        text("p", `${order.customer_name_snapshot} · ${order.customer_phone_snapshot}`),
        text("p", `${order.status} · ${formatCurrency(order.total, order.currency)}`),
        action("View order, payment and delivery", () => loadOrderDetail(order.name)));
      return card;
    }));
    if (!result.orders.length) list.append(text("p", "No matching orders."));
  }

  async function loadOrderDetail(name) {
    const detail = document.querySelector("#admin-order-detail");
    const order = await get("administration.admin_order_detail", { order_name: name });
    detail.hidden = false;
    detail.replaceChildren(
      text("h4", `${order.name} · ${order.status}`),
      text("p", `${order.customer_name} · ${order.customer_phone}`),
      text("p", order.delivery_address),
      text("p", `Subtotal: ${formatCurrency(order.subtotal, order.currency)} · ` +
        `Delivery: ${formatCurrency(order.delivery_fee, order.currency)} · ` +
        `Total: ${formatCurrency(order.total, order.currency)}`),
    );
    const items = document.createElement("ul");
    for (const item of order.items) {
      items.append(text("li", `${item.product_name} · ${item.quantity} × ` +
        `${formatCurrency(item.unit_price, order.currency)} · category at order: ${item.category || "Uncategorized"}`));
    }
    detail.append(items, text("h5", "Payment history"));
    if (!order.payments.length) detail.append(text("p", "No payment attempts."));
    for (const payment of order.payments) {
      detail.append(text("p", `${payment.status} · ${formatCurrency(payment.amount)} · ` +
        `${payment.phone_number || "No phone"} · ${payment.mpesa_receipt_number || "No receipt"} · ` +
        `${payment.transaction_date || "No transaction date"}`));
    }
    detail.append(text("h5", "Delivery"));
    detail.append(text("p", order.delivery
      ? `${order.delivery.name} · ${order.delivery.status} · ${order.delivery.delivery_area || "No area"} · ` +
        `${order.delivery.assigned_delivery_person || "Unassigned"} · ${order.delivery.delivery_address || ""} · ` +
        `${formatCurrency(order.delivery.delivery_fee, order.delivery.currency)} · ` +
        `completed by ${order.delivery.completed_by || "not completed"}`
      : "No delivery record."));
    const transitions = {
      Pending: ["Confirmed", "Cancelled"],
      Confirmed: ["Processing", "Cancelled"],
      Processing: ["Ready for Delivery", "Cancelled"],
      "Ready for Delivery": ["Cancelled"],
    }[order.status] || [];
    if (transitions.length) {
      const form = document.createElement("form");
      form.className = "status-update-form";
      const select = document.createElement("select");
      select.required = true;
      select.add(new Option("Select order status", ""));
      for (const status of transitions) select.add(new Option(status, status));
      const save = text("button", "Update order status");
      save.type = "submit";
      save.className = "primary-button";
      form.append(select, save);
      form.addEventListener("submit", async (event) => {
        event.preventDefault();
        save.disabled = true;
        try {
          await post("orders.update_order_status", { order_name: order.name, status: select.value });
          await loadOrders();
          await loadOrderDetail(order.name);
          await loadDashboard();
        } catch (error) {
          feedback.textContent = error.message;
          save.disabled = false;
        }
      });
      detail.append(form);
    }
  }

  async function loadCustomers() {
    const search = String(new FormData(customerForm).get("search") || "");
    const result = await get("administration.list_customers", {
      search, page: String(customerPage), page_size: "20",
    });
    document.querySelector("#admin-customers-previous").disabled = customerPage <= 1;
    document.querySelector("#admin-customers-next").disabled = !result.has_more;
    const list = document.querySelector("#admin-customers");
    list.replaceChildren(...result.customers.map((customer) => {
      const card = document.createElement("article");
      card.className = "order-card";
      card.append(text("h4", customer.full_name),
        text("p", `${customer.name} · ${customer.phone || "No phone"} · ${customer.email || "No email"}`),
        text("p", `${customer.total_orders} orders · ${formatCurrency(customer.successful_payments)} paid · ` +
          `Last order ${customer.last_order || "Never"}`),
        action("View customer and order history", () => loadCustomerActivity(customer.name)));
      return card;
    }));
    if (!result.customers.length) list.append(text("p", "No matching customers."));
  }

  async function loadCustomerActivity(name, append = false) {
    if (!append) {
      selectedCustomer = name;
      customerActivityPage = 1;
    }
    const result = await get("administration.customer_activity", {
      customer: name, page: String(customerActivityPage), page_size: "20",
    });
    const detail = document.querySelector("#admin-customer-detail");
    detail.hidden = false;
    detail.querySelector(".load-more-customer-orders")?.remove();
    if (!append) {
      detail.replaceChildren(
        text("h4", result.customer.full_name),
        text("p", `${result.customer.email || ""} · ${result.customer.phone || "No phone"} · ` +
          `${result.customer.enabled ? "Enabled" : "Disabled"}`),
        text("h5", "Order history"),
      );
    }
    for (const order of result.orders) {
      detail.append(text("p", `${order.name} · ${order.order_datetime} · ${order.status} · ` +
        `${order.payment_status} · ${formatCurrency(order.total, order.currency)}`));
    }
    if (!append && !result.orders.length) detail.append(text("p", "No order activity."));
    customerActivityHasMore = result.has_more;
    if (customerActivityHasMore) {
      const more = action("Load more order history", async () => {
        customerActivityPage += 1;
        await loadCustomerActivity(selectedCustomer, true);
      });
      more.classList.add("load-more-customer-orders");
      detail.append(more);
    }
  }

  async function loadProducts() {
    const values = Object.fromEntries(new FormData(productForm));
    const result = await get("administration.product_performance", {
      ...values, page: String(productPage), page_size: "50",
    });
    document.querySelector("#admin-products-previous").disabled = productPage <= 1;
    document.querySelector("#admin-products-next").disabled = !result.has_more;
    const list = document.querySelector("#admin-products");
    list.replaceChildren(...result.products.map((product) => {
      const card = document.createElement("article");
      card.className = "order-card";
      const link = document.createElement("a");
      link.href = "/dashboard/products";
      link.textContent = `${product.product_name} (${product.sku})`;
      card.append(link,
        text("p", `${product.enabled ? "Enabled" : "Disabled"} · ${product.category || "Uncategorized"} · ` +
          `${formatCurrency(product.price, product.currency)}`),
        text("p", `${product.units_sold} units · ${product.orders} orders · ` +
          `${formatCurrency(product.item_sales, product.currency)} item sales`));
      return card;
    }));
    if (!result.products.length) list.append(text("p", "No matching products."));
  }

  async function loadAudit() {
    const search = String(new FormData(auditForm).get("search") || "");
    const pageSize = String(new FormData(auditForm).get("page_size") || "5");
    const result = await get("administration.audit_events", {
      search, page: String(auditPage), page_size: pageSize,
    });
    document.querySelector("#admin-audit-previous").disabled = auditPage <= 1;
    document.querySelector("#admin-audit-next").disabled = !result.has_more;
    const list = document.querySelector("#admin-audit-events");
    list.replaceChildren(...result.events.map((event) => {
      const card = document.createElement("article");
      card.className = "order-card";
      card.append(text("h4", `${event.event_type} · ${event.reference_doctype} ${event.reference_name}`),
        text("p", `${event.responsible_user} · ${event.event_datetime}`),
        text("p", event.details));
      return card;
    }));
    if (!result.events.length) list.append(text("p", "No matching audit events."));
  }

  async function refresh() {
    feedback.textContent = "Loading administration data...";
    try {
      await loadDashboard();
      const results = await Promise.allSettled([
        ...(access.store ? [loadOrders(), loadCustomers(), loadProducts()] : []),
        ...(access.store || access.finance ? [loadOptions()] : []),
        ...(access.audit ? [loadAudit()] : []),
        ...(access.finance ? [loadAnalytics()] : []),
      ]);
      const errors = results.filter((result) => result.status === "rejected");
      feedback.textContent = errors.length
        ? errors.map((result) => result.reason.message).join(" ")
        : "";
      for (const buttonElement of document.querySelectorAll("[data-report][data-format]")) {
        const group = {
          sales: access.finance, payments: access.payment_export,
          orders: access.store, customers: access.store,
          inventory: access.inventory, deliveries: access.delivery,
        }[buttonElement.dataset.report];
        buttonElement.hidden = !group;
      }
    } catch (error) {
      feedback.textContent = error.message;
    }
  }

  analyticsForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      await loadAnalytics();
      feedback.textContent = "";
    } catch (error) {
      feedback.textContent = error.message;
    }
  });
  orderForm.addEventListener("submit", (event) => {
    event.preventDefault();
    orderPage = 1;
    loadOrders().catch((error) => { feedback.textContent = error.message; });
  });
  customerForm.addEventListener("submit", (event) => {
    event.preventDefault();
    customerPage = 1;
    loadCustomers().catch((error) => { feedback.textContent = error.message; });
  });
  productForm.addEventListener("submit", (event) => {
    event.preventDefault();
    productPage = 1;
    loadProducts().catch((error) => { feedback.textContent = error.message; });
  });
  auditForm.addEventListener("submit", (event) => {
    event.preventDefault();
    auditPage = 1;
    loadAudit().catch((error) => { feedback.textContent = error.message; });
  });
  for (const [prefix, load, getPage, setPage] of [
    ["admin-orders", loadOrders, () => orderPage, (value) => { orderPage = value; }],
    ["admin-customers", loadCustomers, () => customerPage, (value) => { customerPage = value; }],
    ["admin-products", loadProducts, () => productPage, (value) => { productPage = value; }],
    ["admin-audit", loadAudit, () => auditPage, (value) => { auditPage = value; }],
  ]) {
    document.querySelector(`#${prefix}-previous`).addEventListener("click", () => {
      if (getPage() > 1) {
        setPage(getPage() - 1);
        load().catch((error) => { feedback.textContent = error.message; });
      }
    });
    document.querySelector(`#${prefix}-next`).addEventListener("click", () => {
      setPage(getPage() + 1);
      load().catch((error) => { feedback.textContent = error.message; });
    });
  }
  for (const buttonElement of document.querySelectorAll("[data-report][data-format]")) {
    buttonElement.addEventListener("click", () => {
      const filters = Object.fromEntries(new FormData(reportForm));
      const query = new URLSearchParams({
        ...filters,
        report: buttonElement.dataset.report,
        file_format: buttonElement.dataset.format,
      });
      window.location.assign(
        `/api/method/intelligent_ordering.api.administration.export_report?${query}`,
      );
    });
  }
  document.querySelector("#admin-dashboard-link").addEventListener("click", () => {
    if (window.location.hash === "#admin-dashboard") refresh();
  });
  window.addEventListener("hashchange", () => {
    if (window.location.hash === "#admin-dashboard") refresh();
  });
  if (window.location.hash === "#admin-dashboard") refresh();
}
