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

function renderMetrics(summary) {
  const labels = [
    ["total", summary?.manager ? "Total deliveries" : "Assigned deliveries"],
    ["pending", "Pending acceptance"],
    ["accepted", "Accepted"],
    ["picked_up", "Picked up"],
    ["in_progress", "In progress"],
    ["delivered", "Successfully delivered"],
    ["failed", "Failed"],
    ["unassigned", "Unassigned"],
    ["assigned", "Assigned"],
    ["completed", "Completed"],
    ["available_riders", "Available riders"],
  ];
  const container = document.querySelector("#delivery-metrics");
  container.replaceChildren(...labels
    .filter(([key]) => Object.hasOwn(summary || {}, key))
    .map(([key, label]) => {
      const card = document.createElement("article");
      card.className = "smarto-admin-metric";
      card.append(text("span", label), text("strong", summary[key]));
      return card;
    }));
}

function readProof(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result).split(",", 2)[1] || "");
    reader.onerror = () => reject(new Error("The proof photo could not be read. Try another image."));
    reader.readAsDataURL(file);
  });
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
    if (control.disabled) return;
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
    const summary = dashboard.manager
      ? { ...dashboard.summary, available_riders: dashboard.available_riders }
      : dashboard.summary;
    renderMetrics({ ...summary, manager: dashboard.manager });
    document.querySelector("#delivery-delayed").textContent =
      `${dashboard.delayed_deliveries || 0} delayed ${dashboard.delayed_deliveries === 1 ? "delivery" : "deliveries"}.`;
    const heading = document.querySelector("#delivery-workspace-heading");
    if (heading) heading.textContent = dashboard.manager ? "Delivery management" : "My deliveries";
    const completion = document.querySelector("#delivery-completion-rate");
    if (completion) completion.textContent = dashboard.manager
      ? `${dashboard.completion_rate}% of all deliveries completed.` : "";
    manager.hidden = !dashboard.manager;
    if (!dashboard.manager) return;
    document.querySelector("#delivery-workloads").replaceChildren(
      ...dashboard.personnel.map((person) =>
        text("p", `${person.full_name} (${person.name}): ${person.workload} active deliveries`)),
    );
    const performance = document.querySelector("#delivery-performance");
    performance.replaceChildren(...dashboard.personnel_performance.map((person) => {
      const rate = Number(person.total) ? (100 * Number(person.completed) / Number(person.total)).toFixed(1) : "0.0";
      return text("p", `${person.rider}: ${person.completed} completed · ${person.failed} failed · ${person.total} total · ${rate}% completion`);
    }));
    if (!dashboard.personnel_performance.length) {
      performance.append(text("p", "No delivery performance history."));
    }
    document.querySelector("#delivery-area-management").hidden = false;
    areaForm.hidden = !dashboard.can_manage_areas;
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
      if (dashboard.can_manage_areas) row.append(button("Edit area", () => {
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
      card.append(text("h4", `${delivery.order} · ${delivery.status}`),
        text("p", `${delivery.name} · ${delivery.customer_name} · ${delivery.customer_phone}`),
        text("p", `${delivery.delivery_address} · ${delivery.delivery_area}`),
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
      text("p", `Payment status: ${delivery.payment_status || "Unavailable"}`),
      text("p", `Assignment date: ${delivery.assignment_date || "Not recorded"}`),
      text("p", `Assigned: ${delivery.assigned_delivery_person || "Awaiting assignment"}`),
      text("p", `Scheduled: ${delivery.scheduled_delivery_date || "Not scheduled"}`),
      text("p", `Dispatched: ${delivery.dispatch_date || "Not dispatched"}`),
      text("p", `Completed: ${delivery.completion_date || "Not completed"}${delivery.completed_by ? ` by ${delivery.completed_by}` : ""}`),
      text("p", `Notes: ${delivery.delivery_notes || "None"}`),
    );
    const items = document.createElement("ul");
    items.setAttribute("aria-label", "Order items");
    for (const item of delivery.items || []) {
      items.append(text("li", `${item.product_name_snapshot} (${item.product_sku_snapshot}) × ${item.quantity}`));
    }
    if (!items.childElementCount) items.append(text("li", "No order item details available."));
    detail.append(text("h4", "Order items"), items);
    if (delivery.proof_files?.length) {
      detail.append(text("h4", "Private proof of delivery"));
      for (const file of delivery.proof_files) {
        const link = text("a", `${file.file_name} · ${file.creation}`);
        link.href = file.file_url;
        link.rel = "noreferrer";
        detail.append(link);
      }
    }
    if (!dashboard.manager && delivery.status === "Assigned") {
      const accept = button("Accept delivery", () => act(accept, async () => {
        await post("deliveries.update_delivery", { delivery_name: name, status: "Accepted" });
        await refresh();
        await showDetail(name);
      }));
      const rejectForm = document.createElement("form");
      rejectForm.className = "smarto-checkout-form";
      const reason = document.createElement("textarea");
      reason.required = true;
      reason.maxLength = 1000;
      field(rejectForm, "Reason for rejecting assignment", reason);
      const reject = text("button", "Reject assignment");
      reject.type = "submit";
      reject.className = "smarto-button smarto-button-secondary";
      rejectForm.append(reject);
      rejectForm.addEventListener("submit", (event) => {
        event.preventDefault();
        if (!rejectForm.reportValidity()) return;
        act(reject, async () => {
          await post("deliveries.reject_delivery", { delivery_name: name, reason: reason.value });
          detail.hidden = true;
          await refresh();
        });
      });
      detail.append(accept, rejectForm);
    }
    if (dashboard.manager && !["Picked Up", "Dispatched", "In Transit", "Delivered", "Cancelled"].includes(delivery.status)) {
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
      status.add(new Option("Add a note without changing status", delivery.status));
      for (const allowed of delivery.allowed_statuses) {
        const label = allowed === "Preparing" ? "Start delivery preparation"
          : allowed === "Picked Up" ? "Start delivery / pick up order"
          : allowed === "In Transit" ? "Mark in transit"
            : allowed === "Delivered" ? "Mark delivered"
              : allowed === "Failed" ? "Report failed delivery" : allowed;
        status.add(new Option(label, allowed));
      }
      field(update, "Delivery action", status);
      const notes = field(update, "Delivery notes / failure or cancellation reason", input("text"));
      notes.maxLength = 1000;
      const confirmation = field(update, "I confirm the customer received this delivery", input("checkbox"));
      confirmation.closest("label").hidden = true;
      const proofInput = document.createElement("input");
      proofInput.type = "file";
      proofInput.accept = "image/png,image/jpeg,image/webp";
      const proof = field(update, "Proof photo (PNG, JPEG or WebP; maximum 5 MB)", proofInput);
      proof.closest("label").hidden = true;
      status.addEventListener("change", () => {
        confirmation.closest("label").hidden = status.value !== "Delivered";
        confirmation.required = status.value === "Delivered";
        confirmation.checked = false;
        proof.closest("label").hidden = status.value !== "Delivered";
        proof.required = status.value === "Delivered";
      });
      const save = text("button", "Save delivery update");
      save.type = "submit";
      save.className = "smarto-button";
      update.append(save);
      update.addEventListener("submit", (event) => {
        event.preventDefault();
        if (!update.reportValidity()) return;
        act(save, async () => {
          if (status.value === "Delivered") {
            const file = proof.files?.[0];
            if (!file || file.size > 5 * 1024 * 1024) {
              throw new Error("Choose a proof photo no larger than 5 MB before marking delivered.");
            }
            const fileData = await readProof(file);
            await post("deliveries.upload_delivery_proof", {
              delivery_name: name, file_data: fileData,
            });
          }
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
  if (document.querySelector("[data-delivery-page]")) {
    const warning = document.querySelector("#smarto-page-script-warning");
    if (warning) warning.hidden = true;
  }
  if (window.location.hash === "#delivery-dashboard" || document.querySelector("[data-delivery-page]")) {
    refresh();
  }
}
