import { ApiError, get } from "./api.js";
import { changeCart, loadCart } from "./cart-service.js";
import { formatPrice } from "./components/order-display.js";
import { productImage } from "./components/product-image.js";
import { displayError, ERROR_MESSAGES } from "./error-messages.js";

const page = document.querySelector("[data-catalog-page]");
const kind = page.dataset.catalogPage;
const cartFeedback = document.querySelector("#cart-feedback");
let cartReady = false;
let cartBusy = false;
let cart = null;
let products = [];
let relatedProducts = [];

function productUrl(id) {
  if (id.includes("/") || id === "." || id === "..") {
    return `/product-details?${new URLSearchParams({ product: id })}`;
  }
  return `/products/${encodeURIComponent(id)}`;
}

function categoryUrl(id) {
  return `/products?${new URLSearchParams({ category: id })}`;
}

function element(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== null) node.textContent = text;
  if (className) node.className = className;
  return node;
}

function productCard(product, withCart, detailed = false) {
  const card = element("article", null, "smarto-product-card");
  card.append(productImage(
    product.image,
    product.product_name,
    detailed ? "smarto-product-image smarto-product-image-detail" : "smarto-product-image",
  ));

  const heading = element("h2", null, "smarto-product-heading");
  const link = element("a", product.product_name);
  link.href = productUrl(product.name);
  heading.append(link);
  card.append(heading, element("p", `SKU: ${product.sku}`, "smarto-product-sku"));
  if (product.category) card.append(element("p", product.category, "smarto-product-category"));
  if (detailed && product.description) card.append(element("p", product.description, "smarto-product-description"));
  card.append(element("p", formatPrice(product.price, product.currency), "smarto-product-price"));
  const available = Number(product.available_quantity);
  const stock = element(
    "p",
    available > 0 ? `${available} available` : "Out of stock",
    "smarto-stock-status",
  );
  stock.dataset.available = String(available > 0);
  card.append(stock);

  if (withCart) {
    let quantity;
    if (detailed) {
      const label = element("label", "Quantity ", "smarto-product-quantity");
      quantity = document.createElement("input");
      quantity.type = "number";
      quantity.min = "1";
      quantity.max = String(Math.min(available, cart?.max_quantity || 9999));
      quantity.step = "1";
      quantity.value = "1";
      quantity.disabled = !cartReady || cartBusy || !(available > 0);
      label.append(quantity);
      card.append(label);
    }
    const button = element("button", "Add to cart", "smarto-button");
    button.type = "button";
    button.disabled = !cartReady || cartBusy || !(available > 0);
    button.setAttribute("aria-label", `Add ${product.product_name} to cart`);
    button.addEventListener("click", () => {
      if (quantity && !quantity.reportValidity()) return;
      return addToCart(product.name, quantity ? quantity.value : "1");
    });
    card.append(button);
  }
  return card;
}

function renderProducts() {
  const selector = kind === "detail"
    ? "#product-detail"
    : kind === "home"
      ? "#home-products"
      : "#catalog-products";
  const target = document.querySelector(selector);
  if (target) target.replaceChildren(...products.map((product) =>
    productCard(product, true, kind === "detail")));
  renderRelatedProducts();
}

function renderRelatedProducts() {
  const target = document.querySelector("#related-products");
  if (!target) return;
  target.replaceChildren(...relatedProducts.map((product) => productCard(product, true)));
}

async function initializeCart() {
  try {
    const result = await loadCart();
    cart = result;
    cartReady = true;
    if (result.removed_products?.length) {
      cartFeedback.textContent = `${result.removed_products.length} unavailable item(s) were removed from your cart.`;
    }
  } catch (error) {
    cartFeedback.textContent = `Cart unavailable: ${displayError(error)} Open your cart to resolve cart issues.`;
  } finally {
    renderProducts();
  }
}

async function addToCart(product, quantity) {
  if (!cartReady || cartBusy) return;
  cartBusy = true;
  renderProducts();
  cartFeedback.textContent = "Adding to cart...";
  try {
    const result = await changeCart("cart.add_item", {
      product,
      quantity,
    }, cart.is_guest);
    cart = result;
    cartFeedback.textContent = result.removed_products?.length
      ? `Added to cart. ${result.removed_products.length} unavailable item(s) were removed.`
      : "Added to cart.";
    const nextStep = element("a", "View cart and continue to checkout", "smarto-button");
    nextStep.href = "/cart";
    cartFeedback.append(element("span", " "), nextStep);
  } catch (error) {
    cartFeedback.textContent = `Could not add to cart: ${displayError(error)}`;
  } finally {
    cartBusy = false;
    renderProducts();
  }
}

function renderCategories(categories) {
  const container = document.querySelector("#categories-list");
  const status = document.querySelector("#categories-status");
  container.replaceChildren(...categories.map((category) => {
    const link = element("a", category.category_name, "smarto-category-link");
    link.href = categoryUrl(category.name);
    return link;
  }));
  status.textContent = categories.length ? "" : "No categories are available.";
}

async function loadHomeOrCategories() {
  try {
    const result = await get("catalog.get_catalog", {
      page_size: "4",
      ...(kind === "home" ? { sort: "best_selling" } : {}),
    });
    renderCategories(result.categories);
    if (kind === "home") {
      products = result.products;
      renderProducts();
      document.querySelector("#home-products-status").textContent = result.products.length
        ? ""
        : "Best-selling products will appear here after completed orders are recorded.";
    }
  } catch (error) {
    document.querySelector("#categories-status").textContent = `Categories could not be loaded: ${displayError(error)}`;
    if (kind === "home") {
      document.querySelector("#home-products-status").textContent = `Products could not be loaded: ${displayError(error)}`;
    }
  }
}

async function loadDetail() {
  const status = document.querySelector("#product-status");
  try {
    const path = window.location.pathname.replace(/\/$/, "");
    const id = path.startsWith("/products/")
      ? decodeURIComponent(path.slice("/products/".length))
      : new URLSearchParams(window.location.search).get("product");
    if (!id) throw new ApiError(ERROR_MESSAGES.missing);
    products = [await get("catalog.get_product", { product: id })];
    renderProducts();
    status.textContent = "";
    await loadRelatedProducts(products[0]);
  } catch (error) {
    products = [];
    renderProducts();
    status.textContent = `Product could not be loaded: ${displayError(error)}`;
  }
}

async function loadRelatedProducts(product) {
  const status = document.querySelector("#related-products-status");
  const section = document.querySelector("#related-products-section");
  if (!status || !section || !product.category_id) return;
  section.hidden = false;
  status.textContent = "Loading related products...";
  try {
    const result = await get("catalog.get_catalog", {
      category: product.category_id,
      page_size: "5",
    });
    relatedProducts = result.products.filter((item) => item.name !== product.name);
    renderRelatedProducts();
    status.textContent = relatedProducts.length ? "" : "No related products are available.";
  } catch (error) {
    status.textContent = `Related products could not be loaded: ${displayError(error)}`;
  }
}

function setupProductListing() {
  const form = document.querySelector("#catalog-form");
  const status = document.querySelector("#catalog-status");
  const pagination = document.querySelector("#catalog-pagination");
  const previous = document.querySelector("#catalog-previous");
  const next = document.querySelector("#catalog-next");
  const params = new URLSearchParams(window.location.search);
  form.elements.search.value = params.get("search") || "";
  form.elements.sort.value = params.get("sort") || "name_asc";
  let category = params.get("category") || "";
  let currentPage = 1;
  let requestId = 0;

  async function load() {
    const id = ++requestId;
    const filters = {
      search: form.elements.search.value.trim(),
      category,
      sort: form.elements.sort.value,
      page: String(currentPage),
      page_size: "20",
    };
    status.textContent = "Loading products...";
    pagination.hidden = true;
    products = [];
    renderProducts();
    try {
      const result = await get("catalog.get_catalog", filters);
      if (id !== requestId) return;
      if (!result.products.length && result.total > 0 && currentPage > 1) {
        currentPage = Math.ceil(result.total / result.page_size);
        return load();
      }
      const select = form.elements.category;
      select.replaceChildren(new Option("All categories", ""));
      for (const item of result.categories) select.add(new Option(item.category_name, item.name));
      select.value = category;
      products = result.products;
      renderProducts();
      status.textContent = result.total
        ? `Showing ${(result.page - 1) * result.page_size + 1}-${(result.page - 1) * result.page_size + result.products.length} of ${result.total} products.`
        : "No products match your search.";
      previous.disabled = result.page <= 1;
      next.disabled = !result.has_more;
      document.querySelector("#catalog-page").textContent = `Page ${result.page}`;
      pagination.hidden = result.total === 0;
    } catch (error) {
      if (id !== requestId) return;
      status.textContent = `Products could not be loaded: ${displayError(error)}`;
    }
  }

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    category = form.elements.category.value;
    currentPage = 1;
    const query = new URLSearchParams();
    if (form.elements.search.value.trim()) query.set("search", form.elements.search.value.trim());
    if (category) query.set("category", category);
    if (form.elements.sort.value !== "name_asc") query.set("sort", form.elements.sort.value);
    history.replaceState(null, "", query.size ? `/products?${query}` : "/products");
    load();
  });
  previous.addEventListener("click", () => { if (currentPage > 1) { currentPage -= 1; load(); } });
  next.addEventListener("click", () => { currentPage += 1; load(); });
  load();
}

if (kind === "home" || kind === "categories") {
  loadHomeOrCategories();
  if (kind === "home") initializeCart();
} else if (kind === "detail") {
  loadDetail();
  initializeCart();
} else if (kind === "products") {
  setupProductListing();
  initializeCart();
}
