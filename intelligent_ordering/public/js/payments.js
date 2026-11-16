import { get, post } from "./api.js";

function text(tag, value) {
  const element = document.createElement(tag);
  element.textContent = value;
  return element;
}

function formatCurrency(value, currency = "KES") {
  const amount = Number(value || 0);
  return `${currency} ${Number.isFinite(amount) ? amount.toLocaleString(undefined, {
    minimumFractionDigits: 2, maximumFractionDigits: 2,
  }) : "0.00"}`;
}

function statusBadge(value) {
  const badge = text("span", value || "Unknown");
  badge.className = "smarto-status-badge";
  badge.dataset.status = String(value || "").toLowerCase().replaceAll(" ", "-");
  return badge;
}

export function mountOrderPayment(container, order) {
  const paymentStatus = text("p", `Payment: ${order.payment_status || "Unpaid"}`);
  container.append(paymentStatus);
  if (order.payment_status === "Paid" || ["Cancelled", "Completed"].includes(order.status)) {
    return (current) => { paymentStatus.textContent = `Payment: ${current.payment_status}`; };
  }
  const form = document.createElement("form");
  form.className = "status-update-form";
  const label = text("label", "M-Pesa mobile number");
  const phone = document.createElement("input");
  phone.type = "tel";
  phone.autocomplete = "tel";
  phone.required = true;
  phone.maxLength = 20;
  phone.value = order.customer_phone || "";
  label.append(phone);
  const pay = text("button", "Pay with M-Pesa");
  pay.type = "submit";
  pay.className = "primary-button";
  pay.disabled = true;
  const refresh = text("button", "Refresh payment status");
  refresh.type = "button";
  refresh.className = "secondary-button";
  const feedback = text("p", "");
  feedback.setAttribute("role", "status");
  const history = document.createElement("div");
  async function load() {
    const transactions = await get("payments.get_order_payments", { order_name: order.name });
    history.replaceChildren(...transactions.map((transaction) => text(
      "p",
      `${transaction.status} - KES ${transaction.amount}` +
        (transaction.mpesa_receipt_number ? ` - ${transaction.mpesa_receipt_number}` : "") +
        (transaction.failure_description ? ` - ${transaction.failure_description}` : ""),
    )));
    pay.disabled = order.payment_status === "Paid" || ["Cancelled", "Completed"].includes(order.status)
      || transactions.some((transaction) =>
      ["Initiated", "Pending", "Successful"].includes(transaction.status),
    );
    if (transactions.some((transaction) => transaction.status === "Successful")) {
      feedback.textContent = "Payment verified. Staff will confirm your order separately.";
    }
  }
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (pay.disabled || !form.reportValidity()) return;
    pay.disabled = true;
    try {
      const transaction = await post("payments.initiate_payment", {
        order_name: order.name, phone: phone.value,
      });
      feedback.textContent = transaction.status === "Pending"
        ? "Check your phone for the M-Pesa prompt. Never share your PIN."
        : transaction.failure_description || `Payment: ${transaction.status}`;
      await load();
    } catch (error) {
      // An interrupted response may still have initiated a charge. Refresh the
      // existing attempt rather than automatically sending another STK push.
      feedback.textContent = error.message;
      try {
        await load();
      } catch (refreshError) {
        feedback.textContent = `${error.message} Payment status could not be refreshed: ${refreshError.message}`;
      }
    }
  });
  refresh.addEventListener("click", async () => {
    refresh.disabled = true;
    try {
      await load();
    } catch (error) {
      feedback.textContent = error.message;
    } finally {
      refresh.disabled = false;
    }
  });
  form.append(label, pay, refresh);
  container.append(form, feedback, history);
  load().catch((error) => { feedback.textContent = error.message; });
  return (current) => {
    order.status = current.status;
    order.payment_status = current.payment_status;
    paymentStatus.textContent = `Payment: ${order.payment_status}`;
    const closed = order.payment_status === "Paid" || ["Cancelled", "Completed"].includes(order.status);
    form.hidden = closed;
    if (closed) pay.disabled = true;
  };
}

export function initPaymentDashboard() {
  const form = document.querySelector("#payment-filters");
  const summary = document.querySelector("#payment-summary");
  const results = document.querySelector("#payment-transactions");
  const detail = document.querySelector("#payment-detail");
  const feedback = document.querySelector("#payment-feedback");
  let detailRequest = 0;
  let selectedPayment = null;
  let page = 1;
  let hasMore = false;
  const previous = document.querySelector("#payments-previous");
  const next = document.querySelector("#payments-next");
  async function load() {
    feedback.textContent = "Loading payments...";
    try {
      const values = Object.fromEntries(new FormData(form));
      const [listing, totals] = await Promise.all([
        get("payments.list_transactions", { ...values, page: String(page) }),
        get("payments.payment_summary"),
      ]);
      const selectedVisible = selectedPayment && listing.transactions.some(
        (transaction) => transaction.name === selectedPayment,
      );
      detail.remove();
      if (!selectedVisible) {
        selectedPayment = null;
        detailRequest += 1;
        detail.replaceChildren();
      }
      summary.replaceChildren(...totals.map((row) => {
        const card = document.createElement("article");
        card.className = "smarto-admin-metric";
        card.append(
          text("span", `${row.environment} · ${row.status}`),
          text("strong", `${row.transactions} transactions`),
          text("strong", `${formatCurrency(row.amount, row.currency)} · ${row.currency || "KES"}`),
        );
        return card;
      }));
      results.replaceChildren(...listing.transactions.map((transaction) => {
        const card = document.createElement("article");
        card.className = "smarto-order-item";
        const heading = document.createElement("div");
        heading.className = "section-heading";
        heading.append(text("h3", transaction.order), statusBadge(transaction.status));
        card.append(
          heading,
          text("p", `Payment reference: ${transaction.name}`),
          text("p", `${formatCurrency(transaction.amount)} · ${transaction.phone_number || "No phone number"}`),
          text("p", `Receipt: ${transaction.mpesa_receipt_number || "Not received"} · ` +
            `${transaction.transaction_date || "No transaction date"}`),
        );
        const view = text("button", "View payment");
        view.type = "button";
        view.className = "smarto-button smarto-button-secondary";
        view.addEventListener("click", async () => {
          selectedPayment = transaction.name;
          card.append(detail);
          view.disabled = true;
          view.textContent = "Opening payment...";
          try {
            await showDetail(transaction.name);
          } finally {
            view.disabled = false;
            view.textContent = "View payment";
          }
        });
        card.append(view);
        if (transaction.name === selectedPayment) card.append(detail);
        return card;
      }));
      hasMore = listing.has_more;
      previous.disabled = page === 1;
      next.disabled = !hasMore;
      feedback.textContent = listing.transactions.length ? "" : "No matching payments.";
    } catch (error) {
      selectedPayment = null;
      detailRequest += 1;
      results.replaceChildren();
      detail.replaceChildren();
      feedback.textContent = error.message;
    }
  }
  async function showDetail(name) {
    const request = ++detailRequest;
    detail.replaceChildren(text("p", "Loading payment details..."));
    try {
      const transaction = await get("payments.get_transaction", { payment_name: name });
      if (request !== detailRequest) return;
      const output = document.createElement("article");
      output.className = "smarto-order-item";
      const heading = document.createElement("div");
      heading.className = "section-heading";
      heading.append(text("h3", transaction.order), statusBadge(transaction.status));
      output.append(
        heading,
        text("p", `Payment reference: ${transaction.name}`),
        text("p", `Amount: ${formatCurrency(transaction.amount)}`),
        text("p", `Method: ${transaction.payment_method || "M-Pesa"} · Phone: ${transaction.phone_number || "Not recorded"}`),
        text("p", `Receipt: ${transaction.mpesa_receipt_number || "Not received"} · ` +
          `Transaction date: ${transaction.transaction_date || "Not recorded"}`),
        text("p", `Created: ${transaction.creation || "Not recorded"}`),
      );
      if (transaction.order_summary) {
        const order = transaction.order_summary;
        output.append(text("h4", "Associated order"),
          text("p", `${order.name} · ${order.status} · Payment: ${order.payment_status}`),
          text("p", `Order total: ${order.currency} ${order.total} · Placed: ${order.order_datetime}`));
      }
      if (transaction.failure_description) {
        output.append(text("p", `Failure details: ${transaction.failure_description}`));
      }
      const diagnosticFields = [
        "merchant_request_id", "checkout_request_id", "callback_response", "query_response",
      ];
      if (diagnosticFields.some((field) => transaction[field])) {
        const diagnostics = document.createElement("details");
        diagnostics.append(
          text("summary", "Technical transaction data"),
          text("pre", JSON.stringify(Object.fromEntries(
            diagnosticFields.filter((field) => transaction[field])
              .map((field) => [field, transaction[field]]),
          ), null, 2)),
        );
        output.append(diagnostics);
      }
      const reconcile = text("button", "Check with Safaricom");
      reconcile.className = "smarto-button";
      reconcile.type = "button";
      reconcile.addEventListener("click", async () => {
        if (reconcile.disabled) return;
        reconcile.disabled = true;
        try {
          await post("payments.reconcile_payment", { payment_name: name });
          await showDetail(name);
          await load();
        } catch (error) {
          feedback.textContent = error.message;
          reconcile.disabled = false;
        }
      });
      detail.replaceChildren(output);
      if (transaction.can_reconcile) detail.prepend(reconcile);
    } catch (error) {
      if (request !== detailRequest) return;
      const message = text("p", error.message);
      message.setAttribute("role", "alert");
      detail.replaceChildren(message);
      feedback.textContent = error.message;
    }
  }
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    page = 1;
    load();
  });
  previous.addEventListener("click", () => { if (page > 1) { page -= 1; load(); } });
  next.addEventListener("click", () => { if (hasMore) { page += 1; load(); } });
  document.querySelector("#payments-link").addEventListener("click", () => {
    if (window.location.hash === "#payment-dashboard") load();
  });
  window.addEventListener("hashchange", () => {
    if (window.location.hash === "#payment-dashboard") load();
  });
  if (window.location.hash === "#payment-dashboard" || document.querySelector("[data-finance-workspace]")) load();
}
