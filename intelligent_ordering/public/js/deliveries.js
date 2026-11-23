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

function canAssign(delivery) {
  return !["Picked Up", "Dispatched", "In Transit", "Delivered", "Cancelled"].includes(delivery.status);
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
    ["available_riders", "Idle riders"],
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
  const riderPage = Boolean(document.querySelector("[data-rider-page]"));
  const feedback = document.querySelector("#delivery-feedback");
  const filters = document.querySelector("#delivery-filters");
  const searchStatus = document.querySelector("#delivery-search-status");
  const searchButton = filters.querySelector('button[type="submit"]');
  const results = document.querySelector("#delivery-list");
  const detail = document.querySelector("#delivery-detail");
  const manager = document.querySelector("#delivery-manager");
  const readyOrders = document.querySelector("#delivery-ready-orders");
  const areaForm = document.querySelector("#delivery-area-form");
  const previous = document.querySelector("#delivery-previous");
  const next = document.querySelector("#delivery-next");
  const readyPrevious = document.querySelector("#delivery-ready-previous");
  const readyNext = document.querySelector("#delivery-ready-next");
  const riderLocation = document.querySelector("#delivery-location-share");
  const managerPlan = document.querySelector("#delivery-optimization-manager");
  const planForm = document.querySelector("#delivery-plan-form");
  const planResults = document.querySelector("#delivery-plan-results");
  const routeResults = document.querySelector("#delivery-my-route-results");
  const offersSection = document.querySelector("#delivery-offers-section");
  const offersStatus = document.querySelector("#delivery-offers-status");
  const offersList = document.querySelector("#delivery-offers-list");
  const onlineButton = document.querySelector("#delivery-online");
  const offlineButton = document.querySelector("#delivery-offline");
  const escalationsSection = document.querySelector("#delivery-escalations-section");
  const escalations = document.querySelector("#delivery-escalations");
  let offersOnline = false;
  let offerRefreshInProgress = false;
  let lastHeartbeat = 0;
  let page = 1;
  let readyPage = 1;
  let refreshing = false;
  let dashboard = { manager: false, personnel: [], areas: [] };
  let selectedArea = null;
  const requestedOrder = !riderPage && document.querySelector("[data-delivery-page]")
    ? new URLSearchParams(window.location.search).get("order") : null;
  let openRequestedOrder = Boolean(requestedOrder);
  if (requestedOrder) filters.elements.search.value = requestedOrder;
  if (areaForm) {
    areaForm.append(button("Add new area", () => {
      selectedArea = null;
      areaForm.reset();
      areaForm.elements.area_name.readOnly = false;
      areaForm.elements.currency.value = "KES";
      areaForm.elements.enabled.value = "1";
    }));
  }

  async function act(control, operation, message = feedback) {
    if (control.disabled) return;
    control.disabled = true;
    message.textContent = "";
    try {
      await operation();
    } catch (error) {
      message.textContent = error.message;
    } finally {
      control.disabled = control === onlineButton ? offersOnline
        : control === offlineButton ? !offersOnline : false;
    }
  }

  async function loadDashboard() {
    dashboard = riderPage
      ? await get("deliveries.my_delivery_dashboard")
      : await get("deliveries.delivery_dashboard", { page: String(readyPage) });
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
    if (manager) manager.hidden = !dashboard.manager;
    if (offersSection) offersSection.hidden = !dashboard.rider;
    if (escalationsSection) escalationsSection.hidden = !dashboard.manager;
    if (dashboard.rider && offersSection) await loadOffers();
    if (riderLocation) riderLocation.hidden = dashboard.manager;
    if (managerPlan) managerPlan.hidden = !dashboard.manager;
    if (!dashboard.manager) return;
    if (escalations) {
      escalations.replaceChildren(...(dashboard.escalated_broadcasts || []).map((delivery) => {
        const row = document.createElement("article");
        const view = button("Manage delivery", () => act(view, () => showDetail(delivery.name)));
        row.append(text("p", `${delivery.name} · ${delivery.order} · Expired ${delivery.broadcast_escalated_at}`), view);
        return row;
      }));
      if (!dashboard.escalated_broadcasts?.length) escalations.append(text("p", "No expired broadcasts."));
    }
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
    if (!dashboard.ready_orders.length) readyOrders.append(text("p",
      "No ready orders need a delivery record. Automatically broadcast orders are in Deliveries below; choose Assign / monitor delivery to select a rider."));
    document.querySelector("#delivery-areas").replaceChildren(...dashboard.areas.map((area) => {
      const row = document.createElement("article");
      row.className = "smarto-order-item";
      row.append(text("p", `${area.name}: ${area.currency} ${area.delivery_fee} (${area.enabled ? "Enabled" : "Disabled"})`));
      if (dashboard.can_manage_areas) row.append(button("Edit area", () => {
        selectedArea = area;
        areaForm.elements.area_name.value = area.name;
        areaForm.elements.area_name.readOnly = true;
        areaForm.elements.currency.value = area.currency;
        areaForm.elements.delivery_fee.value = area.delivery_fee;
        areaForm.elements.enabled.value = String(area.enabled);
        areaForm.scrollIntoView({ behavior: "smooth" });
      }));
      if (dashboard.can_delete_areas) {
        const remove = button("Delete unused area", () => {
          if (!window.confirm(`Permanently delete ${area.name}? Areas with history must be disabled instead.`)) return;
          act(remove, async () => {
            const result = await post("deliveries.delete_delivery_area", {
              area_name: area.name, modified: area.modified,
            });
            selectedArea = null;
            areaForm.reset();
            areaForm.elements.area_name.readOnly = false;
            areaForm.elements.currency.value = "KES";
            areaForm.elements.enabled.value = "1";
            try {
              await loadDashboard();
              feedback.textContent = result.message;
            } catch (error) {
              feedback.textContent = `${result.message} Display refresh failed; reload before continuing. ${error.message}`;
            }
          });
        });
        row.append(remove);
      }
      return row;
    }));
  }

  async function loadOffers() {
    if (!offersSection || !dashboard.rider || offerRefreshInProgress) return;
    offerRefreshInProgress = true;
    try {
      const data = await get("deliveries.delivery_offers");
      offersOnline = data.online;
      offersStatus.textContent = !data.online ? "Offline"
        : data.busy ? "Online, but unavailable while you have active deliveries."
          : "Online and available for offers.";
      onlineButton.disabled = data.online;
      offlineButton.disabled = !data.online;
      offersList.replaceChildren(...data.offers.map((offer) => {
        const card = document.createElement("article");
        card.className = "smarto-order-item";
        const accept = button("Accept offer", () => act(accept, async () => {
          await post("deliveries.accept_delivery_offer", {
            delivery_name: offer.name, round_number: String(offer.round_number),
          });
          await refresh();
          await showDetail(offer.name);
        }));
        const reject = button("Reject offer", () => act(reject, async () => {
          await post("deliveries.reject_delivery_offer", {
            delivery_name: offer.name, round_number: String(offer.round_number),
          });
          await loadOffers();
        }));
        card.append(text("h3", `${offer.name} · ${offer.order}`),
          text("p", `Order: ${offer.order_status} · ${offer.order_status === "Ready for Delivery" ? "Ready for pickup" : "Preparing; pickup is not yet available"}`),
          text("p", `Area: ${offer.delivery_area || "Not specified"} · Round ${offer.round_number} expires: ${offer.expires_at}`),
          accept, reject);
        return card;
      }));
      if (!data.offers.length) offersList.append(text("p", "No delivery offers."));
    } finally {
      offerRefreshInProgress = false;
    }
  }

  if (offersSection) {
    onlineButton.addEventListener("click", () => act(onlineButton, async () => {
      await post("deliveries.set_offer_presence", { online: "1" });
      lastHeartbeat = Date.now();
      await loadOffers();
    }));
    offlineButton.addEventListener("click", () => act(offlineButton, async () => {
      await post("deliveries.set_offer_presence", { online: "0" });
      await loadOffers();
    }));
    const updateOffers = async () => {
      // A hidden dashboard stops heartbeats, allowing stale rider presence to expire.
      if (!dashboard.rider || document.visibilityState === "hidden") return;
      try {
        if (offersOnline && Date.now() - lastHeartbeat >= 30000) {
          await post("deliveries.set_offer_presence", { online: "heartbeat" });
          lastHeartbeat = Date.now();
        }
        await loadOffers();
      } catch (error) {
        offersOnline = false;
        onlineButton.disabled = false;
        offlineButton.disabled = true;
        offersList.replaceChildren();
        offersStatus.textContent = error.message;
      }
    };
    if (window.setInterval) window.setInterval(updateOffers, 5000);
    if (window.frappe?.realtime) window.frappe.realtime.on("delivery_offers_changed", updateOffers);
  }

  async function loadList() {
    const listing = await get(riderPage ? "deliveries.my_deliveries" : "deliveries.list_deliveries", {
      ...Object.fromEntries(new FormData(filters)), page: String(page),
    });
    results.replaceChildren(...listing.deliveries.map((delivery) => {
      const card = document.createElement("article");
      card.className = "smarto-order-item";
      const view = button(dashboard.manager && canAssign(delivery) ? "Assign / monitor delivery" : "View delivery",
        () => act(view, () => showDetail(delivery.name)));
      card.append(text("h4", `${delivery.order} · ${delivery.status}`),
        text("p", `${delivery.name} · ${delivery.customer_name} · ${delivery.customer_phone}`),
        text("p", `${delivery.delivery_address} · ${delivery.delivery_area}`),
        text("p", `Scheduled: ${delivery.scheduled_delivery_date || "Not scheduled"}`), view);
      if (dashboard.manager && planForm && delivery.status === "Awaiting Assignment") {
        card.append(button("Plan group from this delivery", () => {
          planForm.elements.delivery_name.value = delivery.name;
          planResults.replaceChildren();
          managerPlan.scrollIntoView({ behavior: "smooth" });
        }));
      }
      return card;
    }));
    if (!listing.deliveries.length) results.append(text("p", "No matching deliveries."));
    previous.disabled = page === 1;
    next.disabled = !listing.has_more;
    return listing.deliveries;
  }

  async function showDetail(name, updateFeedback = text("p", "")) {
    const delivery = await get(riderPage ? "deliveries.get_my_delivery" : "deliveries.get_delivery", {
      delivery_name: name,
    });
    const assignmentPersonnel = delivery.assignment_personnel;
    const detailManager = !riderPage && Array.isArray(assignmentPersonnel);
    detail.hidden = false;
    detail.replaceChildren(
      text("h3", `${delivery.name} - ${delivery.status}`),
      text("p", `Order: ${delivery.order}`),
      text("p", `${delivery.customer_name} - ${delivery.customer_phone}`),
      text("p", `${delivery.delivery_address} (${delivery.delivery_area})`),
      text("p", `Delivery fee: ${delivery.currency} ${delivery.delivery_fee}`),
      text("p", `Payment: ${delivery.payment_method || "Unavailable"} · ${delivery.payment_status || "Unavailable"}`),
      ...(delivery.order_status ? [text("p", `Order status: ${delivery.order_status}${delivery.order_status !== "Ready for Delivery" ? " · Wait until preparation is complete before pickup." : ""}`)] : []),
      ...(delivery.payment_method === "Cash on Delivery" ? [
        text("p", `Cash collected: ${delivery.cash_collected ? `${delivery.currency} ${delivery.cash_collected_amount} · ${delivery.cash_collected_at} by ${delivery.cash_collected_by}` : "Not recorded; finance confirmation required after delivery"}`),
      ] : []),
      text("p", `Assignment date: ${delivery.assignment_date || "Not recorded"}`),
      text("p", `Assigned: ${delivery.assigned_delivery_person || "Awaiting assignment"}`),
      text("p", `Scheduled: ${delivery.scheduled_delivery_date || "Not scheduled"}`),
      text("p", `Dispatched: ${delivery.dispatch_date || "Not dispatched"}`),
      text("p", `Completed: ${delivery.completion_date || "Not completed"}${delivery.completed_by ? ` by ${delivery.completed_by}` : ""}`),
      text("p", `Notes: ${delivery.delivery_notes || "None"}`),
    );
    updateFeedback.setAttribute("role", "status");
    if (delivery.location_set) {
      detail.append(text("p", `Delivery coordinates: ${delivery.latitude}, ${delivery.longitude}`));
    }
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
    if (!detailManager && delivery.status === "Assigned") {
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
    if (detailManager && canAssign(delivery)) {
      const assignment = document.createElement("form");
      assignment.className = "smarto-checkout-form";
      assignment.append(text("h4", "Assign / reassign delivery"));
      const person = document.createElement("select");
      person.required = true;
      person.add(new Option("Select delivery person", ""));
      for (const user of assignmentPersonnel) {
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
      if (!assignmentPersonnel.length) {
        save.disabled = true;
        assignment.append(text("p",
          "No enabled riders are available. Ask an Administrator or System Manager to register a Delivery Staff (Rider) account at /dashboard/accounts."));
      }
      assignment.append(save);
      assignment.addEventListener("submit", (event) => {
        event.preventDefault();
        if (!assignment.reportValidity()) return;
        act(save, async () => {
          await post("deliveries.assign_delivery", {
            delivery_name: name, assigned_person: person.value,
            scheduled_delivery_date: date.value, notes: notes.value,
          });
          try {
            await loadList();
            await showDetail(name);
            await loadDashboard();
            feedback.textContent = "Delivery assigned. The rider must accept it.";
          } catch (error) {
            feedback.textContent = `Delivery assigned, but the display could not refresh. Reload before continuing. ${error.message}`;
          }
        });
      });
      detail.append(assignment);
    }
    if (!detailManager && !riderPage && canAssign(delivery)) {
      detail.append(text("p", "Only a delivery manager can assign this delivery. Sign in with a manager account."));
    }
    if (detailManager && !["Delivered", "Cancelled"].includes(delivery.status)) {
      const coordinates = document.createElement("form");
      coordinates.className = "smarto-checkout-form";
      coordinates.append(text("h4", "Set delivery coordinates"));
      const latitude = field(coordinates, "Latitude", input("number", delivery.location_set ? delivery.latitude : ""));
      latitude.min = "-90";
      latitude.max = "90";
      latitude.step = "any";
      latitude.required = true;
      const longitude = field(coordinates, "Longitude", input("number", delivery.location_set ? delivery.longitude : ""));
      longitude.min = "-180";
      longitude.max = "180";
      longitude.step = "any";
      longitude.required = true;
      const save = text("button", "Save delivery coordinates");
      save.type = "submit";
      save.className = "smarto-button";
      coordinates.append(save);
      if (delivery.location_set) {
        const clear = button("Clear delivery coordinates", () => act(clear, async () => {
          await post("deliveries.clear_delivery_coordinates", { delivery_name: name });
          if (planResults) planResults.replaceChildren();
          await showDetail(name);
          feedback.textContent = "Delivery coordinates cleared.";
        }));
        coordinates.append(clear);
      }
      coordinates.addEventListener("submit", (event) => {
        event.preventDefault();
        if (!coordinates.reportValidity()) return;
        act(save, async () => {
          await post("deliveries.set_delivery_coordinates", {
            delivery_name: name, latitude: latitude.value, longitude: longitude.value,
          });
          if (planResults) planResults.replaceChildren();
          await showDetail(name);
          feedback.textContent = "Delivery coordinates saved.";
        });
      });
      detail.append(coordinates);
    }
    if (!["Delivered", "Cancelled"].includes(delivery.status)) {
      const update = document.createElement("form");
      update.className = "smarto-checkout-form";
      const status = document.createElement("select");
      status.add(new Option("Add a note without changing status", delivery.status));
      for (const allowed of delivery.allowed_statuses) {
        const label = allowed === "Preparing" ? "Start delivery preparation"
          : allowed === "Ready for Dispatch" ? "Mark ready for dispatch"
          : allowed === "Picked Up" ? "Start delivery / pick up order"
          : allowed === "In Transit" ? "Mark in transit"
            : allowed === "Delivered" ? "Mark delivered"
              : allowed === "Failed" ? "Report failed delivery" : allowed;
        status.add(new Option(label, allowed));
      }
      status.value = delivery.status;
      field(update, "Delivery action", status);
      const notes = field(update, "Delivery notes / failure or cancellation reason", input("text"));
      notes.maxLength = 1000;
      const confirmation = field(update, "I confirm the customer received this delivery", input("checkbox"));
      confirmation.closest("label").hidden = true;
      const cashConfirmation = field(update, "I confirm I collected the full order amount in cash", input("checkbox"));
      cashConfirmation.closest("label").hidden = true;
      const proofInput = document.createElement("input");
      proofInput.type = "file";
      proofInput.accept = "image/png,image/jpeg,image/webp";
      const proof = field(update, "Proof photo (PNG, JPEG or WebP; maximum 5 MB)", proofInput);
      proof.closest("label").hidden = true;
      status.addEventListener("change", () => {
        confirmation.closest("label").hidden = status.value !== "Delivered";
        confirmation.required = status.value === "Delivered";
        confirmation.checked = false;
        cashConfirmation.closest("label").hidden = delivery.payment_method !== "Cash on Delivery" || status.value !== "Delivered";
        cashConfirmation.required = delivery.payment_method === "Cash on Delivery" && status.value === "Delivered";
        cashConfirmation.checked = false;
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
        return act(save, async () => {
          if (status.value === delivery.status && !notes.value.trim()) {
            updateFeedback.textContent = "Choose a delivery action or enter a note before saving.";
            return;
          }
          updateFeedback.textContent = "Saving delivery update...";
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
            cash_collected: cashConfirmation.checked ? "1" : "0",
          });
          updateFeedback.textContent = "Delivery update saved.";
          const refreshed = await Promise.allSettled([
            showDetail(name, updateFeedback), loadList(), loadDashboard(),
          ]);
          const failure = refreshed.find((result) => result.status === "rejected");
          if (failure) {
            updateFeedback.textContent = `Delivery update saved, but some information could not refresh. ${failure.reason.message}`;
          }
        }, updateFeedback);
      });
      detail.append(update);
    }
    detail.append(updateFeedback);
    detail.append(text("h4", "Activity history"));
    for (const activity of delivery.activities) {
      detail.append(text("p",
        `${activity.activity_datetime} - ${activity.responsible_user}: ` +
        `${activity.from_status || "New"} -> ${activity.to_status}; ` +
        `${activity.previous_person || "Unassigned"} -> ${activity.assigned_person || "Unassigned"}; ` +
        `scheduled ${activity.scheduled_delivery_date || "Not scheduled"}. ${activity.notes || ""}`));
    }
    detail.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  async function refresh({ listOnly = false } = {}) {
    if (refreshing) return false;
    refreshing = true;
    if (searchButton) searchButton.disabled = true;
    if (searchStatus) searchStatus.textContent = "Searching deliveries...";
    if (!listOnly) feedback.textContent = "Loading deliveries...";
    detail.hidden = true;
    try {
      if (!listOnly) {
        try {
          await loadDashboard();
          feedback.textContent = "";
        } catch (error) {
          if (manager) manager.hidden = true;
          if (offersSection) offersSection.hidden = true;
          if (riderLocation) riderLocation.hidden = true;
          if (managerPlan) managerPlan.hidden = true;
          feedback.textContent = `Delivery overview could not be loaded: ${error.message}`;
        }
      }
      const deliveries = await loadList();
      if (searchStatus) searchStatus.textContent = deliveries.length
        ? `Showing ${deliveries.length} ${deliveries.length === 1 ? "delivery" : "deliveries"} on page ${page}.`
        : "No deliveries match your filters.";
      if (openRequestedOrder) {
        openRequestedOrder = false;
        const delivery = deliveries.find((row) => row.order === requestedOrder);
        if (delivery) await showDetail(delivery.name);
        else feedback.textContent =
          `No delivery record found for ${requestedOrder}. If the order is ready, use Create delivery above; otherwise wait for preparation to finish.`;
      }
      return true;
    } catch (error) {
      results.replaceChildren();
      previous.disabled = next.disabled = true;
      (searchStatus || feedback).textContent = `Deliveries could not be loaded: ${error.message}`;
      return false;
    } finally {
      refreshing = false;
      if (searchButton) searchButton.disabled = false;
    }
  }

  function renderRoute(container, data) {
    container.replaceChildren(
      text("p", `Suggested straight-line route: approximately ${data.total_distance_km} km. This is not a road route.`),
    );
    for (const [index, stop] of data.route.entries()) {
      container.append(text("p",
        `${index + 1}. ${stop.name} · Order ${stop.order} · ${stop.status} · ${stop.delivery_address} · ${stop.distance_km} km from previous stop`));
    }
    if (!data.route.length) container.append(text("p", "No located active deliveries."));
    if (data.missing_coordinates) {
      container.append(text("p", `${data.missing_coordinates} assigned deliveries have no coordinates and are not included.`));
    }
  }

  if (riderLocation) {
    const share = document.querySelector("#delivery-share-location");
    const clear = document.querySelector("#delivery-clear-location");
    const route = document.querySelector("#delivery-my-route");
    const locationFeedback = document.querySelector("#delivery-location-feedback");
    share.addEventListener("click", () => act(share, async () => {
      if (window.isSecureContext === false) {
        throw new Error("Location sharing requires HTTPS. Open the rider page using your secure HTTPS address.");
      }
      if (!window.navigator?.geolocation) throw new Error("Location sharing is unavailable in this browser or connection.");
      const position = await new Promise((resolve, reject) => {
        window.navigator.geolocation.getCurrentPosition(resolve,
          () => reject(new Error("Location could not be obtained. Check browser permissions and try again.")),
          { enableHighAccuracy: true, timeout: 15000, maximumAge: 0 });
      });
      await post("deliveries.share_rider_location", {
        latitude: position.coords.latitude, longitude: position.coords.longitude,
        accuracy_meters: position.coords.accuracy,
      });
      routeResults.replaceChildren();
      locationFeedback.textContent = "Current location shared for delivery planning.";
    }, locationFeedback));
    clear.addEventListener("click", () => act(clear, async () => {
      await post("deliveries.clear_rider_location");
      routeResults.replaceChildren();
      locationFeedback.textContent = "Your shared location was cleared.";
    }, locationFeedback));
    route.addEventListener("click", () => act(route, async () => {
      renderRoute(routeResults, await get("deliveries.my_delivery_route"));
    }, locationFeedback));
  }

  if (planForm) {
    planForm.addEventListener("input", () => planResults.replaceChildren());
    planForm.addEventListener("submit", (event) => {
      event.preventDefault();
      if (!planForm.reportValidity()) return;
      const values = Object.fromEntries(new FormData(planForm));
      act(planForm.querySelector('button[type="submit"]'), async () => {
        const plan = await get("deliveries.suggest_delivery_group", {
          delivery_name: values.delivery_name, radius_km: values.radius_km, max_stops: values.max_stops,
        });
        if (Object.entries(values).some(([key, value]) => planForm.elements[key].value !== value)) {
          throw new Error("Planning inputs changed. Request a new suggestion.");
        }
        renderRoute(planResults, plan);
        planResults.prepend(text("p",
          `Suggested rider: ${plan.rider_name} (${plan.rider}). Location shared ${plan.location_updated_at}; reported accuracy ±${plan.accuracy_meters} m.`));
        const assign = button("Assign this group", () => act(assign, async () => {
          await post("deliveries.assign_delivery_group", {
            rider: plan.rider, delivery_names: JSON.stringify(plan.route.map((stop) => stop.name)),
            scheduled_delivery_date: values.scheduled_delivery_date, plan_token: plan.plan_token,
          });
          planResults.replaceChildren();
          const refreshed = await refresh();
          feedback.textContent = refreshed
            ? "Delivery group assigned. The rider must accept each delivery."
            : `Delivery group assigned, but the display could not refresh. Reload before continuing. ${feedback.textContent}`;
        }));
        planResults.append(assign);
      });
    });
  }

  if (areaForm) areaForm.addEventListener("submit", (event) => {
    event.preventDefault();
    if (!areaForm.reportValidity()) return;
    act(areaForm.querySelector('button[type="submit"]'), async () => {
      await post("deliveries.save_delivery_area", {
        ...Object.fromEntries(new FormData(areaForm)), modified: selectedArea?.modified || "",
      });
      selectedArea = null;
      areaForm.reset();
      areaForm.elements.area_name.readOnly = false;
      areaForm.elements.currency.value = "KES";
      areaForm.elements.enabled.value = "1";
      try {
        await loadDashboard();
        feedback.textContent = "Delivery area saved. Existing orders have not changed.";
      } catch (error) {
        feedback.textContent = `Delivery area saved, but display refresh failed; reload before continuing. ${error.message}`;
      }
    });
  });
  filters.addEventListener("submit", (event) => {
    event.preventDefault();
    if (refreshing) return;
    page = 1;
    openRequestedOrder = false;
    return refresh({ listOnly: true });
  });
  previous.addEventListener("click", () => {
    if (!refreshing && page > 1) { page -= 1; return refresh({ listOnly: true }); }
  });
  next.addEventListener("click", () => {
    if (!refreshing) { page += 1; return refresh({ listOnly: true }); }
  });
  if (readyPrevious) readyPrevious.addEventListener("click", () => {
    if (!refreshing && readyPage > 1) { readyPage -= 1; refresh(); }
  });
  if (readyNext) readyNext.addEventListener("click", () => {
    if (!refreshing) { readyPage += 1; refresh(); }
  });
  document.querySelector("#deliveries-link")?.addEventListener("click", () => refresh());
  if (riderPage || document.querySelector("[data-delivery-page]")) {
    const warning = document.querySelector("#smarto-page-script-warning");
    if (warning) warning.hidden = true;
  }
  if (riderPage || window.location.hash === "#delivery-dashboard" || document.querySelector("[data-delivery-page]")) {
    refresh();
  }
}
