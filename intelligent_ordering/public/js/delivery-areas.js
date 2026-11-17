import { get, post } from "./api.js";
import { text } from "./components/order-display.js";

const find = (id) => document.querySelector(`#areas-${id}`);
const form = find("form");
const status = find("status");
const error = find("error");
const list = find("list");
const add = find("new");
const save = form.querySelector('button[type="submit"]');
let selected = null;
let busy = false;
let ready = false;
let permissions = {};

function edit(area = null) {
  if (busy || !ready) return;
  selected = area;
  form.reset();
  for (const [key, value] of Object.entries({
    area_name: area?.name || "", currency: area?.currency || "KES",
    delivery_fee: area?.delivery_fee ?? "", enabled: area?.enabled ?? 1,
  })) form.elements[key].value = String(value);
  form.elements.area_name.readOnly = Boolean(area);
  find("heading").textContent = area ? `Edit ${area.name}` : "Add delivery area";
  form.hidden = false;
}

function control(label, action) {
  const button = text("button", label, "smarto-button smarto-button-secondary");
  button.type = "button";
  button.addEventListener("click", action);
  return button;
}

async function mutate(operation, values, message) {
  if (busy || !ready) return;
  busy = true;
  save.disabled = add.disabled = true;
  error.textContent = "";
  status.textContent = "Saving changes...";
  try {
    await post(operation, values);
    selected = null;
    form.hidden = true;
    const refreshed = await load();
    status.textContent = refreshed ? message : `${message} Display refresh failed; reload before continuing.`;
  } catch (failure) {
    status.textContent = "";
    error.textContent = failure.message;
  } finally {
    busy = false;
    save.disabled = add.disabled = !ready;
  }
}

async function load() {
  ready = false;
  try {
    const data = await get("deliveries.list_delivery_areas");
    permissions = data;
    add.hidden = !data.can_create;
    list.replaceChildren(...data.areas.map((area) => {
      const card = text("article", "", "smarto-order-item");
      card.append(text("h2", area.name),
        text("p", `${area.currency} ${area.delivery_fee} · ${area.enabled ? "Enabled" : "Disabled"}`));
      if (data.can_write) card.append(control("Edit area", () => edit(area)));
      if (data.can_delete) card.append(control("Delete unused area", () => {
        if (busy || !window.confirm(`Permanently delete ${area.name}? Areas with history must be disabled instead.`)) return;
        mutate("deliveries.delete_delivery_area", { area_name: area.name, modified: area.modified },
          "Unused delivery area deleted.");
      }));
      return card;
    }));
    status.textContent = data.areas.length ? "" : "No delivery areas configured. Add an area to enable checkout for its currency.";
    ready = true;
    return true;
  } catch (failure) {
    list.replaceChildren();
    form.hidden = add.hidden = true;
    status.textContent = "Delivery areas could not be loaded.";
    error.textContent = failure.message;
    return false;
  }
}

add.addEventListener("click", () => { if (permissions.can_create) edit(); });
form.addEventListener("submit", (event) => {
  event.preventDefault();
  if (!form.reportValidity()) return;
  mutate("deliveries.save_delivery_area", {
    ...Object.fromEntries(new FormData(form)), modified: selected?.modified || "",
  }, "Delivery area saved. Existing orders have not changed.");
});
const warning = document.querySelector("#smarto-page-script-warning");
if (warning) warning.hidden = true;
load();
