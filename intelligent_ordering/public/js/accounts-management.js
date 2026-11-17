import { get, post } from "./api.js";
import { text } from "./components/order-display.js";

const find = (id) => document.querySelector(`#accounts-${id}`);
const create = find("create");
const createButton = create.querySelector('button[type="submit"]');
const list = find("list");
const status = find("status");
const error = find("error");
let roles = [];
let page = 1;
let search = "";
let loading = false;
let busy = false;
let ready = false;

function roleOptions(select, values, current) {
  select.replaceChildren(...values.map((role) => new Option(
    role === "Delivery Staff" ? "Delivery Staff (Rider)" : role, role)));
  if (current && values.includes(current)) select.value = current;
}

function accountCard(account) {
  const card = text("article", "", "smarto-order-item");
  card.append(text("h2", account.full_name || account.email),
    text("p", `${account.email} · ${account.enabled ? "Enabled" : "Disabled"} · ${account.roles.join(", ")}`));
  if (!account.can_manage) {
    card.append(text("p", "Protected or advanced account: manage in Desk."));
    return card;
  }
  const form = document.createElement("form");
  form.className = "smarto-catalog-form";
  const roleLabel = text("label", "Intended role");
  const role = document.createElement("select");
  roleOptions(role, account.roles[0] === "Customer" ? ["Customer"] : roles.filter((value) => value !== "Customer"),
    account.roles[0]);
  roleLabel.append(role);
  const enabledLabel = text("label", "Account access");
  const enabled = document.createElement("select");
  enabled.replaceChildren(new Option("Enabled", "1"), new Option("Disabled", "0"));
  enabled.value = String(Number(Boolean(account.enabled)));
  enabledLabel.append(enabled);
  const save = text("button", "Update access", "smarto-button");
  save.type = "submit";
  const invite = text("button", "Resend password-setup email", "smarto-button smarto-button-secondary");
  invite.type = "button";
  invite.disabled = !account.enabled;
  const feedback = text("p", "");
  feedback.setAttribute("role", "status");
  feedback.setAttribute("aria-live", "polite");
  form.append(roleLabel, enabledLabel, save);
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (busy || loading || !window.confirm(
      `Update access for ${account.email}? Existing sessions will be revoked.`,
    )) return;
    busy = true;
    save.disabled = invite.disabled = true;
    feedback.textContent = "Updating access...";
    try {
      const result = await post("accounts.update_access", {
        user_name: account.name, role: role.value, enabled: enabled.value, modified: account.modified,
      });
      const refreshed = await load();
      status.textContent = refreshed ? result.message : `${result.message} List refresh failed; reload before continuing.`;
    } catch (failure) {
      feedback.textContent = failure.message;
    } finally {
      busy = false;
      save.disabled = false;
      invite.disabled = !account.enabled;
    }
  });
  invite.addEventListener("click", async () => {
    if (busy || loading || invite.disabled || !window.confirm(
      `Send password-setup instructions to ${account.email}? Previous setup links may no longer work.`,
    )) return;
    busy = true;
    save.disabled = invite.disabled = true;
    feedback.textContent = "Requesting setup email...";
    try {
      const result = await post("accounts.send_invitation", { user_name: account.name });
      feedback.textContent = result.message;
    } catch (failure) {
      feedback.textContent = `Email request failed: ${failure.message}`;
    } finally {
      busy = false;
      save.disabled = false;
      invite.disabled = !account.enabled;
    }
  });
  card.append(form, invite, feedback);
  return card;
}

async function load() {
  loading = true;
  createButton.disabled = true;
  error.textContent = "";
  status.textContent = "Loading accounts...";
  try {
    const data = await get("accounts.list_accounts", { search, page: String(page), page_size: "20" });
    roles = data.roles;
    roleOptions(find("role"), roles, find("role").value);
    list.replaceChildren(...data.accounts.map(accountCard));
    find("previous").disabled = page <= 1;
    find("next").disabled = !data.has_more;
    find("page").textContent = `Page ${page}`;
    status.textContent = data.accounts.length ? "" : "No matching accounts.";
    ready = true;
    return true;
  } catch (failure) {
    ready = false;
    list.replaceChildren();
    status.textContent = "Account administration is unavailable.";
    error.textContent = failure.message;
    return false;
  } finally {
    loading = false;
    createButton.disabled = !ready;
  }
}

create.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (busy || loading || !ready || !create.reportValidity()) return;
  busy = true;
  createButton.disabled = true;
  const feedback = find("create-feedback");
  feedback.textContent = "Creating account and requesting setup email...";
  try {
    const result = await post("accounts.create_account", Object.fromEntries(new FormData(create)));
    create.reset();
    const refreshed = await load();
    feedback.textContent = refreshed ? result.message : `${result.message} List refresh failed; reload the page.`;
  } catch (failure) {
    feedback.textContent = `Creation not confirmed. Search the email before retrying. ${failure.message}`;
  } finally {
    busy = false;
    createButton.disabled = !ready;
  }
});
find("search").addEventListener("submit", (event) => {
  event.preventDefault();
  if (busy || loading) return;
  search = find("search").elements.search.value.trim();
  page = 1;
  load();
});
for (const [direction, offset] of [["previous", -1], ["next", 1]]) {
  find(direction).addEventListener("click", () => {
    if (busy || loading || find(direction).disabled) return;
    page += offset;
    load();
  });
}
const warning = document.querySelector("#smarto-page-script-warning");
if (warning) warning.hidden = true;
load();
