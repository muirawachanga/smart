import { get, post } from "./api.js";
import { formatPrice, text } from "./components/order-display.js";

const kind = document.querySelector("[data-customer-page]").dataset.customerPage;
const status = document.querySelector("#customer-status");
const feedback = document.querySelector("#customer-feedback");
const form = document.querySelector("#customer-form");
const list = document.querySelector("#customer-list");
const pagination = document.querySelector("#customer-pagination");
const previous = document.querySelector("#customer-previous");
const next = document.querySelector("#customer-next");
let page = 1;
let busy = false;
let requestId = 0;
let hasMore = false;
const paymentSearch = document.querySelector("#customer-payment-search");
let paymentFilters = { search: "", search_by: "phone" };

function showError(error) {
  feedback.textContent = error.message;
  if (error.status === 403 || error.status === 401) {
    const login = document.querySelector("#customer-login");
    if (login) login.hidden = false;
  }
}

function renderAddresses(addresses) {
  list.replaceChildren(...addresses.map((address) => {
    const card = text("article", "", "smarto-order-item");
    card.append(
      text("h2", `${address.address_label || "Delivery address"}${address.is_default ? " (Default)" : ""}`),
      text("p", [address.address_line_1, address.address_line_2, address.city, address.region, address.postal_code].filter(Boolean).join(", ")),
    );
    const edit = text("button", "Edit", "smarto-button smarto-button-secondary");
    edit.type = "button";
    edit.addEventListener("click", () => {
      if (busy) return;
      for (const key of ["address_label", "address_line_1", "address_line_2", "city", "region", "postal_code"]) {
        form.elements[key].value = address[key] || "";
      }
      form.elements.address_name.value = address.name;
      form.elements.is_default.checked = Boolean(address.is_default);
      document.querySelector("#address-form-title").textContent = "Edit address";
      form.elements.address_line_1.focus();
    });
    const remove = text("button", "Delete", "smarto-button smarto-button-secondary");
    remove.type = "button";
    remove.addEventListener("click", async () => {
      if (busy || !window.confirm("Delete this saved address? Addresses referenced by orders cannot be deleted.")) return;
      busy = true;
      remove.disabled = true;
      feedback.textContent = "";
      try {
        renderAddresses(await post("customers.delete_address", { address_name: address.name }));
        resetAddress();
        status.textContent = "Address deleted.";
      } catch (error) {
        showError(error);
      } finally {
        busy = false;
        remove.disabled = false;
      }
    });
    card.append(edit, remove);
    return card;
  }));
}

function resetAddress() {
  form.reset();
  form.elements.address_name.value = "";
  document.querySelector("#address-form-title").textContent = "Add an address";
}

function renderPayments(transactions) {
  list.replaceChildren(...transactions.map((payment) => {
    const card = text("article", "", "smarto-order-item");
    const heading = text("div", "", "smarto-order-item-heading");
    const badge = text("span", payment.status, "smarto-status-badge");
    badge.dataset.status = payment.status.toLowerCase();
    heading.append(text("h2", payment.order), badge);
    card.append(
      heading,
      text("p", `${payment.payment_method} · ${payment.status} · ${formatPrice(payment.amount, payment.currency)}`),
      text("p", `${payment.transaction_date || payment.creation || ""} · Receipt: ${payment.mpesa_receipt_number || "Not available"}`),
      text("p", `Payment phone: ${payment.phone_number || "Not recorded"}`),
    );
    return card;
  }));
}

function renderNotifications(notifications) {
  list.replaceChildren(...notifications.map((notification) => {
    const card = text("article", "", `smarto-order-item smarto-notification${notification.read ? " is-read" : ""}`);
    const heading = text("div", "", "smarto-order-item-heading");
    heading.append(text("h2", notification.subject));
    if (!notification.read) {
      const badge = text("span", "New", "smarto-status-badge");
      badge.dataset.status = "unread";
      heading.append(badge);
    }
    card.append(heading, text("p", notification.creation));
    const order = text("a", "View my orders");
    order.href = "/account";
    card.append(order);
    if (!notification.read) {
      const button = text("button", "Mark read", "smarto-button smarto-button-secondary");
      button.type = "button";
      button.addEventListener("click", async () => {
        button.disabled = true;
        feedback.textContent = "";
        try {
          await post("customers.read_notification", { name: notification.name });
          await load();
        } catch (error) {
          showError(error);
          button.disabled = false;
        }
      });
      card.append(button);
    }
    return card;
  }));
}

async function load() {
  const request = ++requestId;
  status.textContent = "Loading...";
  feedback.textContent = "";
  if (pagination) pagination.hidden = true;
  try {
    if (kind === "profile") {
      const profile = await get("customers.get_profile");
      form.elements.full_name.value = profile.full_name || "";
      form.elements.phone.value = profile.phone || "";
      document.querySelector("#customer-email").textContent = profile.email;
      form.hidden = false;
      status.textContent = "";
      return;
    }
    if (kind === "addresses") {
      const addresses = await get("customers.list_addresses");
      renderAddresses(addresses);
      form.hidden = false;
      status.textContent = addresses.length ? "" : "No saved addresses.";
      return;
    }
    const result = await get(kind === "payments" ? "customers.payment_history" : "customers.notifications", {
      page: String(page), page_size: "20",
      ...(kind === "payments" ? paymentFilters : {}),
    });
    if (request !== requestId) return;
    const rows = kind === "payments" ? result.transactions : result.notifications;
    if (kind === "payments") renderPayments(rows);
    else renderNotifications(rows);
    status.textContent = rows.length ? "" : kind === "payments" && paymentFilters.search
      ? "No matching payments for your orders." : `No ${kind} found.`;
    hasMore = result.has_more;
    previous.disabled = page <= 1;
    next.disabled = !hasMore;
    document.querySelector("#customer-page").textContent = `Page ${page}`;
    pagination.hidden = page === 1 && !hasMore;
  } catch (error) {
    if (request !== requestId) return;
    status.textContent = "This account page could not be loaded.";
    if (kind === "payments") list.replaceChildren();
    showError(error);
  }
}

if (form) form.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (busy || !form.reportValidity()) return;
  busy = true;
  const button = form.querySelector('button[type="submit"]');
  button.disabled = true;
  feedback.textContent = "";
  status.textContent = "Saving...";
  try {
    const values = Object.fromEntries(new FormData(form));
    if (kind === "addresses") {
      values.is_default = form.elements.is_default.checked ? "1" : "0";
      renderAddresses(await post("customers.save_address", values));
      resetAddress();
      status.textContent = "Address saved.";
    } else if (kind === "profile") {
      await post("customers.save_profile", values);
      status.textContent = "Profile saved.";
    }
  } catch (error) {
    status.textContent = "Could not save.";
    showError(error);
  } finally {
    busy = false;
    button.disabled = false;
  }
});

paymentSearch?.addEventListener("submit", (event) => {
  event.preventDefault();
  if (!paymentSearch.reportValidity()) return;
  paymentFilters = {
    search: paymentSearch.elements.search.value.trim(),
    search_by: paymentSearch.elements.search_by.value,
  };
  page = 1;
  load();
});
document.querySelector("#customer-payment-clear")?.addEventListener("click", () => {
  paymentSearch.reset();
  paymentFilters = { search: "", search_by: "phone" };
  page = 1;
  load();
});

if (kind === "addresses") document.querySelector("#address-new").addEventListener("click", () => {
  if (!busy) resetAddress();
});
if (pagination) {
  previous.addEventListener("click", () => { if (page > 1) { page -= 1; load(); } });
  next.addEventListener("click", () => { if (hasMore) { page += 1; load(); } });
}
const refresh = document.querySelector("#customer-refresh");
if (refresh) refresh.addEventListener("click", load);
const warning = document.querySelector("#smarto-page-script-warning");
if (warning) warning.hidden = true;
load();
