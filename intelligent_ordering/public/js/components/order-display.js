export function text(tag, value, className = "") {
  const node = document.createElement(tag);
  node.textContent = value;
  if (className) node.className = className;
  return node;
}

export function formatPrice(amount, currency) {
  const code = currency || "KES";
  try {
    return new Intl.NumberFormat(undefined, { style: "currency", currency: code }).format(Number(amount));
  } catch {
    return `${code} ${Number(amount).toFixed(2)}`;
  }
}

export function orderConfirmationUrl(id) {
  if (id.includes("/") || id === "." || id === "..") {
    return `/order-confirmation?${new URLSearchParams({ order: id })}`;
  }
  return `/order-confirmation/${encodeURIComponent(id)}`;
}

export function orderPaymentUrl(id) {
  return `/payment?${new URLSearchParams({ order: id })}`;
}

export function orderTrackingUrl(id) {
  return `/track-order?${new URLSearchParams({ order: id })}`;
}

export function renderOrderItems(container, items, currency) {
  container.replaceChildren(...items.map((item) => {
    const row = text("article", "", "smarto-order-item");
    const amount = item.subtotal ?? item.line_total;
    row.append(
      text("h3", item.product_name),
      text("p", `${item.quantity} × ${formatPrice(item.unit_price, currency)}`),
      text("strong", formatPrice(amount, currency)),
    );
    return row;
  }));
}
