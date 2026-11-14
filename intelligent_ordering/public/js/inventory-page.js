import { get, post } from "./api.js";

const feedback = document.querySelector("#inventory-feedback");
const metrics = document.querySelector("#inventory-metrics");
const stockFilters = document.querySelector("#inventory-stock-filters");
const stockList = document.querySelector("#inventory-stock-list");
const productSearch = document.querySelector("#inventory-product-search");
const productSelect = document.querySelector("#inventory-product-options");
const adjustmentForm = document.querySelector("#inventory-adjustment-form");
const returnForm = document.querySelector("#inventory-return-form");
const movementFilters = document.querySelector("#inventory-movement-filters");
const movementList = document.querySelector("#inventory-movements");
let stockPage = 1;
let movementPage = 1;
let productPage = 1;
let stockHasMore = false;
let movementHasMore = false;
let productHasMore = false;
let productSearchValue = "";
let selectedProduct = "";

function node(tag, value, className = "") {
  const element = document.createElement(tag);
  element.textContent = value == null ? "" : String(value);
  if (className) element.className = className;
  return element;
}

function metricCard(label, value) {
  const card = node("article", null, "smarto-inventory-metric");
  card.append(node("span", label), node("strong", value));
  return card;
}

function setSelectOptions(select, rows, label) {
  const current = select.value;
  const isFilter = select.closest("form") === stockFilters || select.closest("form") === movementFilters;
  select.replaceChildren(new Option(isFilter ? "All warehouses" : "Select warehouse", ""));
  for (const row of rows) select.add(new Option(row.warehouse_name, row.name));
  if (rows.some((row) => row.name === current)) select.value = current;
  if (label) select.setAttribute("aria-label", label);
}

async function loadOverview() {
  const result = await get("inventory.get_dashboard");
  const summary = result.summary;
  metrics.replaceChildren(
    metricCard("Enabled products", summary.total_products),
    metricCard("On hand", summary.total_stock),
    metricCard("Available", summary.available_stock),
    metricCard("Reserved", summary.reserved_stock),
    metricCard(`Low stock (≤${result.low_stock_threshold})`, summary.low_stock_products),
    metricCard("Out of stock", summary.out_of_stock_products),
  );
}

async function loadStock() {
  feedback.textContent = "Loading stock balances...";
  stockList.replaceChildren();
  const result = await get("inventory.list_stock", {
    ...Object.fromEntries(new FormData(stockFilters)),
    page: String(stockPage),
    page_size: "20",
  });
  const filterWarehouse = stockFilters.elements.warehouse;
  setSelectOptions(filterWarehouse, result.warehouses);
  const adjustmentWarehouse = adjustmentForm.elements.warehouse;
  const returnWarehouse = returnForm.elements.warehouse;
  setSelectOptions(adjustmentWarehouse, result.warehouses);
  setSelectOptions(returnWarehouse, result.warehouses);
  for (const select of movementFilters.querySelectorAll('select[name="warehouse"]')) {
    setSelectOptions(select, result.warehouses);
  }
  stockHasMore = result.has_more;
  document.querySelector("#inventory-stock-previous").disabled = stockPage <= 1;
  document.querySelector("#inventory-stock-next").disabled = !stockHasMore;
  document.querySelector("#inventory-stock-page").textContent = `Page ${stockPage}`;
  if (!result.stock.length) {
    stockList.append(node("p", "No stock balances match these filters."));
  } else {
    stockList.replaceChildren(...result.stock.map(stockRow));
  }
  feedback.textContent = "";
}

function stockRow(row) {
  const card = node("article", null, "smarto-order-item");
  card.append(
    node("h3", `${row.product_name} (${row.sku})`),
    node("p", `${row.warehouse_name} · On hand ${row.quantity_on_hand} · Reserved ${row.reserved_quantity} · Available ${row.available_quantity}`),
  );
  const choose = node("button", "Select for stock movement", "smarto-button smarto-button-secondary");
  choose.type = "button";
  choose.addEventListener("click", async () => {
    productSearch.elements.search.value = row.sku;
    productSearchValue = row.sku;
    productPage = 1;
    try {
      await loadProductOptions();
      productSelect.value = row.product;
      selectedProduct = row.product;
      adjustmentForm.elements.warehouse.value = row.warehouse;
      returnForm.elements.warehouse.value = row.warehouse;
      document.querySelector("#inventory-adjustment-form").scrollIntoView({ behavior: "smooth" });
    } catch (error) {
      feedback.textContent = `Product options could not be loaded: ${error.message}`;
    }
  });
  card.append(choose);
  return card;
}

async function loadProductOptions(append = false) {
  const result = await get("inventory.list_product_options", {
    search: productSearchValue,
    page: String(productPage),
    page_size: "100",
  });
  productHasMore = result.has_more;
  const rows = append
    ? [...Array.from(productSelect.options).slice(1).map((option) => ({
      name: option.value,
      product_name: option.dataset.productName || option.textContent,
      sku: option.dataset.sku || "",
      enabled: option.dataset.enabled === "1",
    })), ...result.products]
    : result.products;
  productSelect.replaceChildren(new Option(
    rows.length ? "Select a product" : "No matching products",
    "",
  ));
  for (const product of rows) {
    const option = new Option(
      `${product.product_name} (${product.sku})${product.enabled ? "" : " — Disabled"}`,
      product.name,
    );
    option.dataset.productName = product.product_name;
    option.dataset.sku = product.sku;
    option.dataset.enabled = String(Boolean(product.enabled) ? 1 : 0);
    productSelect.add(option);
  }
  productSelect.value = rows.some((product) => product.name === selectedProduct)
    ? selectedProduct
    : "";
  document.querySelector("#inventory-product-next").disabled = !productHasMore;
}

async function loadMovements() {
  const result = await get("inventory.list_movements", {
    ...Object.fromEntries(new FormData(movementFilters)),
    page: String(movementPage),
    page_size: "20",
  });
  movementHasMore = result.has_more;
  document.querySelector("#inventory-movements-previous").disabled = movementPage <= 1;
  document.querySelector("#inventory-movements-next").disabled = !movementHasMore;
  document.querySelector("#inventory-movements-page").textContent = `Page ${movementPage}`;
  movementList.replaceChildren(...result.movements.map((entry) => {
    const card = node("article", null, "smarto-order-item");
    card.append(
      node("h3", `${entry.transaction_type}: ${entry.product_name || entry.product}`),
      node("p", `${entry.warehouse_name || "Legacy location"} · Quantity ${entry.quantity} · On-hand change ${entry.quantity_change} · Reserved change ${entry.reserved_change}`),
      node("p", `${entry.transaction_date || "Date unavailable"} · ${entry.user_responsible}`),
      node("p", [entry.reference_order, entry.remarks].filter(Boolean).join(" · ")),
    );
    return card;
  }));
  if (!result.movements.length) movementList.append(node("p", "No stock movements match these filters."));
}

async function refreshAfterMovement(message) {
  await Promise.all([loadOverview(), loadStock(), loadMovements()]);
  feedback.textContent = message;
}

stockFilters.addEventListener("submit", (event) => {
  event.preventDefault();
  stockPage = 1;
  loadStock().catch((error) => { feedback.textContent = `Stock could not be loaded: ${error.message}`; });
});
document.querySelector("#inventory-stock-previous").addEventListener("click", () => {
  if (stockPage <= 1) return;
  stockPage -= 1;
  loadStock().catch((error) => { feedback.textContent = error.message; });
});
document.querySelector("#inventory-stock-next").addEventListener("click", () => {
  if (!stockHasMore) return;
  stockPage += 1;
  loadStock().catch((error) => { feedback.textContent = error.message; });
});

productSearch.addEventListener("submit", (event) => {
  event.preventDefault();
  productSearchValue = productSearch.elements.search.value.trim();
  productPage = 1;
  selectedProduct = "";
  loadProductOptions().catch((error) => { feedback.textContent = `Products could not be loaded: ${error.message}`; });
});
productSelect.addEventListener("change", () => { selectedProduct = productSelect.value; });
document.querySelector("#inventory-product-next").addEventListener("click", () => {
  if (!productHasMore) return;
  productPage += 1;
  loadProductOptions(true).catch((error) => { feedback.textContent = error.message; });
});

adjustmentForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!adjustmentForm.reportValidity() || !selectedProduct) {
    feedback.textContent = "Select a product before recording stock.";
    return;
  }
  const values = Object.fromEntries(new FormData(adjustmentForm));
  let quantity = Number(values.quantity);
  if (values.transaction_type === "Adjustment" && values.direction === "decrease") quantity *= -1;
  const button = adjustmentForm.querySelector('button[type="submit"]');
  button.disabled = true;
  try {
    await post("inventory.adjust_stock", {
      product: selectedProduct,
      warehouse: values.warehouse,
      transaction_type: values.transaction_type,
      quantity: String(quantity),
      remarks: values.remarks || "",
    });
    adjustmentForm.reset();
    selectedProduct = "";
    await refreshAfterMovement("Stock movement recorded.");
  } catch (error) {
    feedback.textContent = `Stock movement failed: ${error.message}`;
  } finally {
    button.disabled = false;
  }
});

returnForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!returnForm.reportValidity() || !selectedProduct) {
    feedback.textContent = "Select a product before recording a return.";
    return;
  }
  const values = Object.fromEntries(new FormData(returnForm));
  const button = returnForm.querySelector('button[type="submit"]');
  button.disabled = true;
  try {
    await post("inventory.record_order_return", {
      order_name: values.order_name.trim(),
      product: selectedProduct,
      warehouse: values.warehouse,
      quantity: values.quantity,
      remarks: values.remarks || "",
    });
    returnForm.reset();
    selectedProduct = "";
    await refreshAfterMovement("Dispatched order stock return recorded.");
  } catch (error) {
    feedback.textContent = `Stock return failed: ${error.message}`;
  } finally {
    button.disabled = false;
  }
});

movementFilters.addEventListener("submit", (event) => {
  event.preventDefault();
  movementPage = 1;
  loadMovements().catch((error) => { feedback.textContent = error.message; });
});
document.querySelector("#inventory-movements-previous").addEventListener("click", () => {
  if (movementPage <= 1) return;
  movementPage -= 1;
  loadMovements().catch((error) => { feedback.textContent = error.message; });
});
document.querySelector("#inventory-movements-next").addEventListener("click", () => {
  if (!movementHasMore) return;
  movementPage += 1;
  loadMovements().catch((error) => { feedback.textContent = error.message; });
});

Promise.all([loadOverview(), loadStock(), loadMovements()])
  .catch((error) => { feedback.textContent = `Inventory workspace could not be loaded: ${error.message}`; });
