import { get, post } from "./api.js";

const form = document.querySelector("#setup-business-form");
const fields = document.querySelector("#setup-business-fields");
const status = document.querySelector("#setup-status");
const error = document.querySelector("#setup-error");
const refresh = document.querySelector("#setup-refresh");
const canSave = Boolean(form?.querySelector('button[type="submit"]'));
let businessLoaded = false;

function text(tag, value) {
  const node = document.createElement(tag);
  node.textContent = value;
  return node;
}

function render(data) {
  document.querySelector("#setup-checks").replaceChildren(...data.checks.map((check) => {
    const card = document.createElement("article");
    card.append(text("h3", `${check.title}: ${check.status}`), text("p", check.detail));
    const link = text("a", "Open setup");
    link.href = check.link;
    card.append(link);
    return card;
  }));
  document.querySelector("#setup-optional").replaceChildren(...data.optional.map((item) =>
    text("p", `${item.title}: ${item.status}`)));
  document.querySelector("#setup-manual").replaceChildren(...data.manual_checks.map((item) => {
    const card = document.createElement("article");
    card.append(text("h3", `${item.title}: not verified`), text("p", item.detail));
    return card;
  }));
  status.textContent = `${data.blocking_count} configuration blockers. ${data.notice}`;
}

async function load() {
  error.textContent = "";
  refresh.disabled = true;
  fields.disabled = true;
  try {
    const data = await get("onboarding.readiness");
    render(data);
    if (!businessLoaded) {
      for (const key of ["name", "email", "phone", "address"]) {
        form.elements.namedItem(key).value = data.business[key];
      }
      businessLoaded = true;
    }
    fields.disabled = !canSave;
    return true;
  } catch (failure) {
    fields.disabled = true;
    document.querySelector("#setup-checks").replaceChildren();
    document.querySelector("#setup-optional").replaceChildren();
    document.querySelector("#setup-manual").replaceChildren();
    status.textContent = "Readiness is unknown because checks could not be loaded.";
    error.textContent = failure.message;
    return false;
  } finally {
    refresh.disabled = false;
  }
}

form?.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!canSave || fields.disabled || !form.reportValidity()) return;
  const values = Object.fromEntries(["name", "email", "phone", "address"].map((key) =>
    [key, form.elements.namedItem(key).value]));
  fields.disabled = true;
  refresh.disabled = true;
  error.textContent = "";
  try {
    await post("onboarding.save_business", values);
    businessLoaded = false;
    await load();
    status.textContent = `Business details saved. ${status.textContent}`;
  } catch (failure) {
    error.textContent = failure.message;
    status.textContent = "Business details were not confirmed saved. Refresh before retrying.";
    fields.disabled = !canSave;
  } finally {
    refresh.disabled = false;
  }
});
refresh?.addEventListener("click", () => load());
if (form) {
  const warning = document.querySelector("#smarto-page-script-warning");
  if (warning) warning.hidden = true;
  load();
}
