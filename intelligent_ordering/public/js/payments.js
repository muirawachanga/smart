import { get, post } from "./api.js";

function text(tag, value) {
  const element = document.createElement(tag);
  element.textContent = value;
  return element;
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
        feedback.textContent = refreshError.message;
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
      summary.replaceChildren(...totals.map((row) => text(
        "p", `${row.environment} - ${row.status}: ${row.transactions} transactions, KES ${row.amount}`,
      )));
      results.replaceChildren(...listing.transactions.map((transaction) => {
        const card = document.createElement("article");
        card.className = "order-card";
        card.append(text("h3", transaction.order), text(
          "p", `${transaction.status} - KES ${transaction.amount} - ${transaction.mpesa_receipt_number || "No receipt"}`,
        ));
        const view = text("button", "View and reconcile");
        view.type = "button";
        view.className = "secondary-button";
        view.addEventListener("click", () => showDetail(transaction.name));
        card.append(view);
        return card;
      }));
      hasMore = listing.has_more;
      previous.disabled = page === 1;
      next.disabled = !hasMore;
      feedback.textContent = listing.transactions.length ? "" : "No matching payments.";
    } catch (error) {
      feedback.textContent = error.message;
    }
  }
  async function showDetail(name) {
    try {
      const transaction = await get("payments.get_transaction", { payment_name: name });
      const output = text("pre", JSON.stringify(transaction, null, 2));
      const reconcile = text("button", "Query Safaricom and reconcile");
      reconcile.className = "primary-button";
      reconcile.type = "button";
      reconcile.addEventListener("click", async () => {
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
      detail.replaceChildren(output, reconcile);
    } catch (error) {
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
  document.querySelector("#payments-link").addEventListener("click", () => load());
}
