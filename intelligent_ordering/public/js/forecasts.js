import { get } from "./api.js";
import { formatPrice } from "./components/order-display.js";

function text(tag, value) {
  const element = document.createElement(tag);
  element.textContent = value;
  return element;
}

async function load(kind) {
  const container = document.querySelector(`#${kind}-forecast-results`);
  const status = document.querySelector(`#${kind}-forecast-status`);
  if (!container || !status) return;
  status.textContent = "Calculating forecast...";
  try {
    const data = await get(`administration.${kind}_forecast`);
    const groups = kind === "sales" ? data.series : data.products;
    container.replaceChildren(...groups.map((group) => {
      const card = document.createElement("article");
      const label = kind === "sales"
        ? `${group.currency} · ${group.environment}` : `${group.product_name} (${group.product})`;
      card.append(text("h3", label));
      if (!group.available) {
        card.append(text("p", `Insufficient history (${group.history_days} days, ${group.active_days} active days).`));
      } else {
        const list = document.createElement("ul");
        for (const point of group.forecast) {
          const value = kind === "sales" ? formatPrice(point.estimate, group.currency) : `${point.estimate} units`;
          list.append(text("li", `${point.date}: ${value}`));
        }
        card.append(list);
      }
      return card;
    }));
    status.textContent = groups.length ? `${data.basis} ${data.model}` : "Not enough completed history to forecast.";
  } catch (error) {
    container.replaceChildren();
    status.textContent = `Forecast unavailable: ${error.message}`;
  }
}

load("sales");
load("demand");
