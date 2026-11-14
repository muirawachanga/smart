import { get, post } from "./api.js";
import { clearGuestCart, readGuestCart, writeGuestCart } from "./cart-storage.js";

const page = document.querySelector("[data-catalog-page]");
const kind = page.dataset.catalogPage;
const cartFeedback = document.querySelector("#cart-feedback");
let cartReady = false;
let cartBusy = false;
let cart = null;
let products = [];

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

function formatPrice(amount, currency) {
  const code = currency || "KES";
  try {
    return new Intl.NumberFormat(undefined, { style: "currency", currency: code }).format(Number(amount));
  } catch {
    return `${code} ${Number(amount).toFixed(2)}`;
  }
}

function productCard(product, withCart) {
  const card = element("article", null, "smarto-product-card");
  if (product.image) {
    const image = element("img", null, "smarto-product-image");
    image.src = product.image;
    image.alt = product.product_name;
    image.loading = "lazy";
    image.addEventListener("error", () => image.replaceWith(element("div", "No image", "smarto-image-fallback")), { once: true });
    card.append(image);
  } else {
    card.append(element("div", "No image", "smarto-image-fallback"));
  }

  const heading = element("h2", null);
  const link = element("a", product.product_name);
  link.href = productUrl(product.name);
  heading.append(link);
  card.append(heading, element("p", `SKU: ${product.sku}`));
  if (product.category) card.append(element("p", product.category));
  if (kind === "detail" && product.description) card.append(element("p", product.description));
  card.append(element("p", formatPrice(product.price, product.currency), "smarto-product-price"));
  const available = Number(product.available_quantity);
  card.append(element("p", available > 0 ? `${available} available` : "Out of stock"));

  if (withCart) {
    const button = element("button", "Add to cart", "smarto-button");
    button.type = "button";
    button.disabled = !cartReady || cartBusy || !(available > 0);
    button.setAttribute("aria-label", `Add ${product.product_name} to cart`);
    button.addEventListener("click", () => addToCart(product.name));
    card.append(button);
  }
  return card;
}

function renderProducts() {
  const target = document.querySelector(kind === "detail" ? "#product-detail" : "#catalog-products");
  target.replaceChildren(...products.map((product) => productCard(product, true)));
}

function notifyCart(cartResult) {
  document.dispatchEvent(new CustomEvent("smarto:cart-updated", { detail: cartResult.item_count }));
}

async function initializeCart() {
  try {
    const guestItems = readGuestCart();
    let result = await post("cart.get_cart", { guest_items: JSON.stringify(guestItems) });
    if (!result.is_guest) {
      if (guestItems.length) {
        result = await post("cart.merge_guest_cart", { guest_items: JSON.stringify(guestItems) });
      }
      clearGuestCart();
    } else {
      writeGuestCart(result.items);
    }
    cart = result;
    cartReady = true;
    notifyCart(result);
    if (result.removed_products?.length) {
      cartFeedback.textContent = `${result.removed_products.length} unavailable item(s) were removed from your cart.`;
    }
  } catch (error) {
    cartFeedback.textContent = `Cart unavailable: ${error.message} Open the existing storefront to resolve cart issues.`;
  } finally {
    renderProducts();
  }
}

async function addToCart(product) {
  if (!cartReady || cartBusy) return;
  cartBusy = true;
  renderProducts();
  cartFeedback.textContent = "Adding to cart...";
  try {
    const result = await post("cart.add_item", {
      product,
      quantity: "1",
      guest_items: JSON.stringify(cart.is_guest ? readGuestCart() : []),
    });
    if (result.is_guest) writeGuestCart(result.items);
    cart = result;
    notifyCart(result);
    cartFeedback.textContent = result.removed_products?.length
      ? `Added to cart. ${result.removed_products.length} unavailable item(s) were removed.`
      : "Added to cart.";
  } catch (error) {
    cartFeedback.textContent = `Could not add to cart: ${error.message}`;
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
    const result = await get("catalog.get_catalog", { page_size: "4" });
    renderCategories(result.categories);
    if (kind === "home") {
      document.querySelector("#home-products").replaceChildren(
        ...result.products.map((product) => productCard(product, false)),
      );
      document.querySelector("#home-products-status").textContent =
        result.products.length ? "" : "No products are available.";
    }
  } catch (error) {
    document.querySelector("#categories-status").textContent = `Categories could not be loaded: ${error.message}`;
    if (kind === "home") {
      document.querySelector("#home-products-status").textContent = `Products could not be loaded: ${error.message}`;
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
    if (!id) throw new Error("A product reference is required.");
    products = [await get("catalog.get_product", { product: id })];
    renderProducts();
    status.textContent = "";
  } catch (error) {
    products = [];
    renderProducts();
    status.textContent = `Product could not be loaded: ${error.message}`;
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
      status.textContent = `Products could not be loaded: ${error.message}`;
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
} else if (kind === "detail") {
  loadDetail();
  initializeCart();
} else if (kind === "products") {
  setupProductListing();
  initializeCart();
}
