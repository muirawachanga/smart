import { get, post } from "./api.js";
import { changeCart, loadCart } from "./cart-service.js";
import { formatPrice } from "./components/order-display.js";

const form = document.querySelector("#assistant-form");
const conversation = document.querySelector("#assistant-conversation");
const status = document.querySelector("#assistant-status");
const products = document.querySelector("#assistant-products");
const submit = form.querySelector('button[type="submit"]');
let history = [];
let cartBusy = false;

function text(tag, value) {
  const element = document.createElement(tag);
  element.textContent = value;
  return element;
}

function showProducts(container, items) {
  container.replaceChildren(...items.map((item) => {
    const card = document.createElement("article");
    card.className = "smarto-product-card";
    card.append(text("h2", item.product_name),
      text("p", `${formatPrice(item.price, item.currency)} · Suggested quantity: ${item.quantity}`));
    const add = text("button", "Add suggested quantity to cart");
    add.type = "button";
    add.className = "smarto-button";
    add.addEventListener("click", async () => {
      if (cartBusy) return;
      cartBusy = true;
      add.disabled = true;
      try {
        const cart = await loadCart();
        await changeCart("cart.add_item", { product: item.name, quantity: item.quantity }, cart.is_guest);
        status.textContent = "Added to cart. Review the cart before checkout.";
      } catch (error) {
        status.textContent = `Could not add to cart: ${error.message}`;
      } finally {
        cartBusy = false;
        add.disabled = false;
      }
    });
    card.append(add);
    return card;
  }));
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (submit.disabled || !form.reportValidity()) return;
  const message = form.elements.message.value.trim();
  if (!message) return;
  submit.disabled = true;
  status.textContent = "Asking the assistant...";
  try {
    const result = await post("assistant.converse", {
      message, history: JSON.stringify(history), consent: form.elements.consent.checked ? "1" : "0",
    });
    conversation.append(text("p", `You: ${message}`), text("p", `Assistant: ${result.reply}`));
    history = [...history, { role: "user", text: message }, { role: "assistant", text: result.reply }].slice(-8);
    form.elements.message.value = "";
    showProducts(products, result.products);
    status.textContent = result.notice || "Review suggestions before adding them to your cart.";
  } catch (error) {
    status.textContent = error.message;
  } finally {
    submit.disabled = false;
  }
});

const recommendations = document.querySelector("#assistant-recommendations");
recommendations.addEventListener("click", async () => {
  if (recommendations.disabled) return;
  recommendations.disabled = true;
  try {
    const result = await get("catalog.personalized_recommendations");
    showProducts(document.querySelector("#assistant-recommendation-products"),
      result.products.map((product) => ({ ...product, quantity: 1 })));
    status.textContent = result.products.length ? result.basis : "No personalized suggestions are available yet.";
  } catch (error) {
    status.textContent = error.message;
  } finally {
    recommendations.disabled = false;
  }
});

const warning = document.querySelector("#smarto-page-script-warning");
if (warning) warning.hidden = true;
