import { get, post } from "./api.js";

function text(tag, value) {
  const element = document.createElement(tag);
  element.textContent = value;
  return element;
}

function button(label, action) {
  const element = text("button", label);
  element.type = "button";
  element.className = "smarto-button smarto-button-secondary";
  element.addEventListener("click", action);
  return element;
}

function field(form, label, element) {
  const wrapper = text("label", label);
  wrapper.append(element);
  form.append(wrapper);
  return element;
}

function input(type, value = "") {
  const element = document.createElement("input");
  element.type = type;
  element.value = value;
  return element;
}

export function initDeliveryDashboard() {
  const feedback = document.querySelector("#delivery-feedback");
  const filters = document.querySelector("#delivery-filters");
  const results = document.querySelector("#delivery-list");
  const detail = document.querySelector("#delivery-detail");
  const manager = document.querySelector("#delivery-manager");
  const readyOrders = document.querySelector("#delivery-ready-orders");
  const areaForm = document.querySelector("#delivery-area-form");
  const previous = document.querySelector("#delivery-previous");
  const next = document.querySelector("#delivery-next");
  const readyPrevious = document.querySelector("#delivery-ready-previous");
  const readyNext = document.querySelector("#delivery-ready-next");
  let page = 1;
  let readyPage = 1;
  let dashboard = { manager: false, personnel: [], areas: [] };

  async function act(control, operation) {
    control.disabled = true;
    feedback.textContent = "";
    try {
      await operation();
    } catch (error) {
      feedback.textContent = error.message;
    } finally {
      control.disabled = false;
    }
  }

  async function loadDashboard() {
    dashboard = await get("deliveries.delivery_dashboard", { page: String(readyPage) });
    manager.hidden = !dashboard.manager;
    if (!dashboard.manager) return;
    document.querySelector("#delivery-workloads").replaceChildren(
      ...dashboard.personnel.map((person) =>
        text("p", `${person.full_name} (${person.name}): ${person.workload} active deliveries`)),
    );
    readyPrevious.disabled = readyPage === 1;
    readyNext.disabled = !dashboard.has_more;
    readyOrders.replaceChildren(...dashboard.ready_orders.map((order) => {
      const card = document.createElement("article");
      card.className = "smarto-order-item";
      card.append(text("h4", order.name), text("p", order.customer_name_snapshot),
        text("p", order.delivery_address_snapshot));
      const area = document.createElement("select");
      area.setAttribute("aria-label", `Routing area for ${order.name}`);
      if (!order.delivery_area) {
        area.add(new Option("Select routing area for this legacy order", ""));
        for (const rate of dashboard.areas.filter((rate) => rate.enabled && rate.currency === order.currency)) {
          area.add(new Option(rate.name, rate.name));
        }
        card.append(text("p", "Legacy total is preserved. No new delivery fee will be charged."), area);
      }
      const create = button("Create delivery", () => act(create, async () => {
        const delivery = await post("deliveries.create_delivery", {
          order_name: order.name, delivery_area: area.value,
        });
        await loadDashboard();
        await loadList();
        await showDetail(delivery.name);
      }));
      card.append(create);
      return card;
    }));
    if (!dashboard.ready_orders.length) readyOrders.append(text("p", "No unassigned ready orders."));
    document.querySelector("#delivery-areas").replaceChildren(...dashboard.areas.map((area) => {
      const row = document.createElement("article");
      row.className = "smarto-order-item";
      row.append(text("p", `${area.name}: ${area.currency} ${area.delivery_fee} (${area.enabled ? "Enabled" : "Disabled"})`));
      row.append(button("Edit area", () => {
        areaForm.elements.area_name.value = area.name;
        areaForm.elements.currency.value = area.currency;
        areaForm.elements.delivery_fee.value = area.delivery_fee;
        areaForm.elements.enabled.value = String(area.enabled);
        areaForm.scrollIntoView({ behavior: "smooth" });
      }));
      return row;
    }));
  }

  async function loadList() {
    const listing = await get("deliveries.list_deliveries", {
      ...Object.fromEntries(new FormData(filters)), page: String(page),
    });
    results.replaceChildren(...listing.deliveries.map((delivery) => {
      const card = document.createElement("article");
      card.className = "smarto-order-item";
      const view = button("View delivery", () => act(view, () => showDetail(delivery.name)));
      card.append(text("h4", `${delivery.name} / ${delivery.order}`),
        text("p", `${delivery.status} - ${delivery.delivery_area}`),
        text("p", `Scheduled: ${delivery.scheduled_delivery_date || "Not scheduled"}`), view);
      return card;
    }));
    if (!listing.deliveries.length) results.append(text("p", "No matching deliveries."));
    previous.disabled = page === 1;
    next.disabled = !listing.has_more;
  }

  async function showDetail(name) {
    const delivery = await get("deliveries.get_delivery", { delivery_name: name });
    detail.hidden = false;
    detail.replaceChildren(
      text("h3", `${delivery.name} - ${delivery.status}`),
      text("p", `Order: ${delivery.order}`),
      text("p", `${delivery.customer_name} - ${delivery.customer_phone}`),
      text("p", `${delivery.delivery_address} (${delivery.delivery_area})`),
      text("p", `Delivery fee: ${delivery.currency} ${delivery.delivery_fee}`),
      text("p", `Assigned: ${delivery.assigned_delivery_person || "Awaiting assignment"}`),
      text("p", `Scheduled: ${delivery.scheduled_delivery_date || "Not scheduled"}`),
      text("p", `Dispatched: ${delivery.dispatch_date || "Not dispatched"}`),
      text("p", `Completed: ${delivery.completion_date || "Not completed"}${delivery.completed_by ? ` by ${delivery.completed_by}` : ""}`),
      text("p", `Notes: ${delivery.delivery_notes || "None"}`),
    );
    if (dashboard.manager && !["Dispatched", "In Transit", "Delivered", "Cancelled"].includes(delivery.status)) {
      const assignment = document.createElement("form");
      assignment.className = "smarto-checkout-form";
      assignment.append(text("h4", "Assign / reassign delivery"));
      const person = document.createElement("select");
      person.required = true;
      person.add(new Option("Select delivery person", ""));
      for (const user of dashboard.personnel) {
        person.add(new Option(`${user.full_name} (${user.workload} active)`, user.name));
      }
      person.value = delivery.assigned_delivery_person || "";
      field(assignment, "Delivery person", person);
      const date = field(assignment, "Scheduled delivery date",
        input("date", delivery.scheduled_delivery_date || ""));
      date.required = true;
      const notes = field(assignment, "Assignment notes (reason required for reassignment)", input("text"));
      notes.maxLength = 1000;
      const save = text("button", "Save assignment");
      save.type = "submit";
      save.className = "smarto-button";
      assignment.append(save);
      assignment.addEventListener("submit", (event) => {
        event.preventDefault();
        if (!assignment.reportValidity()) return;
        act(save, async () => {
          await post("deliveries.assign_delivery", {
            delivery_name: name, assigned_person: person.value,
            scheduled_delivery_date: date.value, notes: notes.value,
          });
          await loadDashboard();
          await loadList();
          await showDetail(name);
        });
      });
      detail.append(assignment);
    }
    if (!["Delivered", "Cancelled"].includes(delivery.status)) {
      const update = document.createElement("form");
      update.className = "smarto-checkout-form";
      const status = document.createElement("select");
      status.add(new Option(`Keep ${delivery.status} (notes only)`, delivery.status));
      for (const allowed of delivery.allowed_statuses) status.add(new Option(allowed, allowed));
      field(update, "Update delivery status", status);
      const notes = field(update, "Delivery notes / failure or cancellation reason", input("text"));
      notes.maxLength = 1000;
      const confirmation = field(update, "I confirm the customer received this delivery", input("checkbox"));
      confirmation.closest("label").hidden = true;
      status.addEventListener("change", () => {
        confirmation.closest("label").hidden = status.value !== "Delivered";
        confirmation.required = status.value === "Delivered";
        confirmation.checked = false;
      });
      const save = text("button", "Save delivery update");
      save.type = "submit";
      save.className = "smarto-button";
      update.append(save);
      update.addEventListener("submit", (event) => {
        event.preventDefault();
        if (!update.reportValidity()) return;
        act(save, async () => {
          await post("deliveries.update_delivery", {
            delivery_name: name, status: status.value,
            notes: notes.value, confirmation: confirmation.checked ? "1" : "0",
          });
          await loadDashboard();
          await loadList();
          await showDetail(name);
        });
      });
      detail.append(update);
    }
    detail.append(text("h4", "Activity history"));
    for (const activity of delivery.activities) {
      detail.append(text("p",
        `${activity.activity_datetime} - ${activity.responsible_user}: ` +
        `${activity.from_status || "New"} -> ${activity.to_status}; ` +
        `${activity.previous_person || "Unassigned"} -> ${activity.assigned_person || "Unassigned"}; ` +
        `scheduled ${activity.scheduled_delivery_date || "Not scheduled"}. ${activity.notes || ""}`));
    }
  }

  async function refresh() {
    feedback.textContent = "Loading deliveries...";
    detail.hidden = true;
    try {
      await loadDashboard();
      await loadList();
      feedback.textContent = "";
    } catch (error) {
      results.replaceChildren();
      manager.hidden = true;
      feedback.textContent = error.message;
    }
  }

  areaForm.addEventListener("submit", (event) => {
    event.preventDefault();
    if (!areaForm.reportValidity()) return;
    act(areaForm.querySelector('button[type="submit"]'), async () => {
      await post("deliveries.save_delivery_area", Object.fromEntries(new FormData(areaForm)));
      await loadDashboard();
      feedback.textContent = "Delivery area saved. Existing orders have not changed.";
    });
  });
  filters.addEventListener("submit", (event) => { event.preventDefault(); page = 1; refresh(); });
  previous.addEventListener("click", () => { if (page > 1) { page -= 1; refresh(); } });
  next.addEventListener("click", () => { page += 1; refresh(); });
  readyPrevious.addEventListener("click", () => { if (readyPage > 1) { readyPage -= 1; refresh(); } });
  readyNext.addEventListener("click", () => { readyPage += 1; refresh(); });
  document.querySelector("#deliveries-link").addEventListener("click", refresh);
  if (window.location.hash === "#delivery-dashboard" || document.querySelector("[data-delivery-page]")) {
    refresh();
  }
}
