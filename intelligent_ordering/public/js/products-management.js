import { get, post, readResponse } from "./api.js";
import { text, formatPrice } from "./components/order-display.js";

const find = (id) => document.querySelector(`#products-${id}`);
const form = find("form");
const fields = find("fields");
const status = find("status");
const error = find("error");
const list = find("list");
const editor = find("editor");
const imageFile = find("image-file");
const imageUpload = find("image-upload");
let page = 1;
let search = "";
let selected = null;
let categories = [];
let loading = false;
let saving = false;
let ready = false;
let requestId = 0;
const keys = ["sku", "product_name", "category", "description", "price", "currency", "enabled"];
const input = (key) => form.elements.namedItem(key);

function categoryOptions() {
  const current = input("category").value;
  input("category").replaceChildren(new Option("Select category", ""),
    ...categories.map((category) => new Option(category.category_name, category.name)));
  if (categories.some((category) => category.name === current)) input("category").value = current;
}

function edit(product = null) {
  if (saving || loading || !ready) return;
  selected = product;
  editor.hidden = false;
  form.reset();
  for (const key of keys) input(key).value = String(product?.[key] ?? ({
    currency: "KES", enabled: 1, price: "",
  }[key] ?? ""));
  input("sku").readOnly = Boolean(product);
  imageFile.value = "";
  imageFile.disabled = imageUpload.disabled = !product;
  find("editor-heading").textContent = product ? `Edit ${product.sku}` : "Add product";
  find("save-status").textContent = "";
  find("save-error").textContent = "";
  find("image-status").textContent = "";
  fields.disabled = false;
  input("product_name").focus();
}

async function load() {
  const request = ++requestId;
  loading = true;
  status.textContent = "Loading products...";
  error.textContent = "";
  try {
    const data = await get("products.list_products", { search, page: String(page), page_size: "20" });
    if (request !== requestId) return false;
    categories = data.categories;
    categoryOptions();
    find("category-section").hidden = !data.can_create_category;
    find("inventory-link").hidden = !data.can_receive_stock;
    list.replaceChildren(...data.products.map((product) => {
      const card = text("article", "", "smarto-order-item");
      card.append(text("h2", `${product.product_name} (${product.sku})`),
        text("p", `${formatPrice(product.price, product.currency)} · ${product.enabled ? "Enabled" : "Disabled"}`),
        text("p", product.category || "No category"));
      const button = text("button", "Edit product", "smarto-button smarto-button-secondary");
      button.type = "button";
      button.addEventListener("click", () => edit(product));
      card.append(button);
      return card;
    }));
    find("previous").disabled = page <= 1;
    find("next").disabled = !data.has_more;
    find("page").textContent = `Page ${page}`;
    status.textContent = data.products.length ? "" : "No matching products.";
    ready = true;
    return true;
  } catch (failure) {
    if (request !== requestId) return false;
    list.replaceChildren();
    fields.disabled = true;
    ready = false;
    imageFile.disabled = imageUpload.disabled = true;
    find("category-section").hidden = true;
    find("inventory-link").hidden = true;
    status.textContent = "Product data could not be loaded.";
    error.textContent = failure.message;
    return false;
  } finally {
    if (request === requestId) loading = false;
  }
}

function values() {
  return {
    ...Object.fromEntries(keys.map((key) => [key, input(key).value])),
    image: selected?.image || "", product: selected?.name || "", modified: selected?.modified || "",
  };
}

function updateSavedValues() {
  for (const key of keys) input(key).value = String(selected[key] ?? "");
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (saving || loading || fields.disabled || !form.reportValidity()) return;
  saving = true;
  fields.disabled = true;
  imageUpload.disabled = true;
  find("save-status").textContent = "Saving...";
  find("save-error").textContent = "";
  try {
    const result = await post("products.save_product", values());
    selected = result.product;
    updateSavedValues();
    input("sku").readOnly = true;
    find("editor-heading").textContent = `Edit ${selected.sku}`;
    const refreshed = await load();
    find("save-status").textContent = refreshed
      ? "Product saved. Stock is received separately by inventory personnel."
      : "Product saved, but the list could not be refreshed. Reload before making further changes.";
    fields.disabled = !refreshed;
    imageFile.disabled = imageUpload.disabled = !refreshed;
  } catch (failure) {
    find("save-status").textContent = "Save not confirmed. Reopen or refresh the product before retrying.";
    find("save-error").textContent = failure.message;
    fields.disabled = false;
    imageFile.disabled = imageUpload.disabled = !selected;
  } finally {
    saving = false;
  }
});

find("image-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (saving || loading || !selected || imageUpload.disabled) return;
  const file = imageFile.files?.[0];
  if (keys.some((key) => String(selected[key] ?? "") !== input(key).value)) {
    find("image-status").textContent = "Save your product changes before uploading an image.";
    return;
  }
  if (!file || !["image/png", "image/jpeg", "image/webp", "image/gif"].includes(file.type)) {
    find("image-status").textContent = "Choose a PNG, JPEG, WebP or GIF image.";
    return;
  }
  saving = true;
  fields.disabled = imageFile.disabled = imageUpload.disabled = true;
  let uploaded = false;
  let refreshed = true;
  find("image-status").textContent = "Uploading public image...";
  try {
    const body = new FormData();
    body.append("file", file);
    body.append("is_private", "0");
    body.append("doctype", "Product");
    body.append("docname", selected.name);
    const response = await fetch("/api/method/upload_file", {
      method: "POST", credentials: "same-origin", body,
      headers: { "X-Frappe-CSRF-Token": window.frappe?.csrf_token || "", Accept: "application/json" },
    });
    const payload = await readResponse(response, "upload_file");
    if (!payload.message?.file_url) throw new Error("Upload did not return an image reference.");
    uploaded = true;
    const result = await post("products.save_product", { ...values(), image: payload.message.file_url });
    selected = result.product;
    updateSavedValues();
    imageFile.value = "";
    refreshed = await load();
    find("image-status").textContent = refreshed
      ? "Public image uploaded and linked to this product."
      : "Image uploaded and linked, but the list could not be refreshed. Reload before continuing.";
  } catch (failure) {
    find("image-status").textContent = `${uploaded
      ? "Image uploaded, but linking was not confirmed. Reopen the product before retrying."
      : "Image upload not confirmed."} ${failure.message}`;
  } finally {
    saving = false;
    fields.disabled = imageFile.disabled = imageUpload.disabled = !refreshed;
  }
});

const categoryForm = find("category-form");
categoryForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (saving || loading || !categoryForm.reportValidity()) return;
  saving = true;
  const button = categoryForm.querySelector('button[type="submit"]');
  button.disabled = true;
  try {
    await post("products.create_category", Object.fromEntries(new FormData(categoryForm)));
    categoryForm.reset();
    const refreshed = await load();
    find("category-status").textContent = refreshed
      ? "Category created." : "Category created, but refreshing failed. Reload the page.";
  } catch (failure) {
    find("category-status").textContent = `Category save not confirmed: ${failure.message}`;
  } finally {
    saving = false;
    button.disabled = false;
  }
});
find("new").addEventListener("click", () => edit());
find("search").addEventListener("submit", (event) => {
  event.preventDefault();
  if (saving) return;
  search = find("search").elements.search.value.trim();
  page = 1;
  load();
});
for (const [direction, offset] of [["previous", -1], ["next", 1]]) {
  find(direction).addEventListener("click", () => {
    if (saving || loading || find(direction).disabled) return;
    page += offset;
    load();
  });
}
const warning = document.querySelector("#smarto-page-script-warning");
if (warning) warning.hidden = true;
load();
