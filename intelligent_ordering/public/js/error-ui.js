import { ERROR_MESSAGES, isCustomerPage } from "./error-messages.js";

let fieldSequence = 0;

function fieldMessage(field) {
  const validity = field.validity;
  if (validity.valueMissing) return ERROR_MESSAGES.required;
  if (validity.customError && field.type === "tel") return ERROR_MESSAGES.phone;
  if (validity.typeMismatch && field.type === "email") return ERROR_MESSAGES.email;
  if (validity.tooShort) return `Please enter at least ${field.minLength} characters.`;
  if (validity.tooLong) return `Please enter no more than ${field.maxLength} characters.`;
  if (validity.rangeUnderflow) return `Please enter a value of at least ${field.min}.`;
  if (validity.rangeOverflow) return `Please enter a value no greater than ${field.max}.`;
  return "Please check this field and try again.";
}

function clearField(field) {
  const id = field.dataset.smartoErrorId;
  if (!id) return;
  document.getElementById(id)?.remove();
  const descriptions = (field.getAttribute("aria-describedby") || "").split(/\s+/).filter((value) => value && value !== id);
  if (descriptions.length) field.setAttribute("aria-describedby", descriptions.join(" "));
  else field.removeAttribute("aria-describedby");
  field.removeAttribute("aria-invalid");
  delete field.dataset.smartoErrorId;
}

function showFieldError(field, message) {
  if (!field.willValidate) return;
  let id = field.dataset.smartoErrorId;
  let error = id && document.getElementById(id);
  if (!error) {
    id = `smarto-field-error-${++fieldSequence}`;
    error = document.createElement("span");
    error.id = id;
    error.className = "smarto-field-error";
    error.setAttribute("aria-live", "polite");
    const icon = document.createElement("span");
    icon.setAttribute("aria-hidden", "true");
    icon.textContent = "!";
    const text = document.createElement("span");
    error.append(icon, text);
    field.insertAdjacentElement("afterend", error);
    field.dataset.smartoErrorId = id;
    field.setAttribute("aria-describedby", [field.getAttribute("aria-describedby"), id].filter(Boolean).join(" "));
  }
  error.lastElementChild.textContent = message;
  field.setAttribute("aria-invalid", "true");
}

export function showValidationError(field, message) {
  if (field) showFieldError(field, message);
}

export function createFormAlert() {
  const wrapper = document.createElement("div");
  wrapper.className = "smarto-error-banner";
  wrapper.hidden = true;
  const message = document.createElement("p");
  message.setAttribute("role", "alert");
  const close = document.createElement("button");
  close.type = "button";
  close.textContent = "Dismiss";
  close.setAttribute("aria-label", "Dismiss message");
  const clear = () => { message.textContent = ""; wrapper.hidden = true; };
  close.addEventListener("click", clear);
  wrapper.append(message, close);
  return {
    element: wrapper,
    clear,
    show(value) { message.textContent = value; wrapper.hidden = false; },
  };
}

export function setupPhoneValidation(field) {
  const validate = () => {
    const value = field.value.trim();
    const digits = value.replace(/\D/g, "").length;
    const valid = !value || (/^\+?[0-9][0-9\s().-]{6,19}$/.test(value) && digits >= 7 && digits <= 15);
    field.setCustomValidity(valid ? "" : ERROR_MESSAGES.phone);
  };
  field.addEventListener("input", validate);
  field.addEventListener("change", validate);
  validate();
}

function setupBanner(message) {
  if (!message?.parentNode) return;
  const wrapper = document.createElement("div");
  wrapper.className = "smarto-error-banner";
  wrapper.hidden = message.hidden || !message.textContent.trim();
  message.parentNode.insertBefore(wrapper, message);
  wrapper.append(message);
  const close = document.createElement("button");
  close.type = "button";
  close.textContent = "Dismiss";
  close.setAttribute("aria-label", "Dismiss message");
  close.addEventListener("click", () => { message.textContent = ""; wrapper.hidden = true; });
  wrapper.append(close);
  new MutationObserver(() => { wrapper.hidden = message.hidden || !message.textContent.trim(); }).observe(message, {
    childList: true, characterData: true, subtree: true, attributes: true, attributeFilter: ["hidden"],
  });
}

export function initErrorUI() {
  if (!isCustomerPage()) return;
  for (const selector of ["#auth-error", "#checkout-feedback", "#customer-feedback", "#cart-feedback", "#app-feedback"]) {
    setupBanner(document.querySelector(selector));
  }
  for (const field of document.querySelectorAll('input[type="tel"][name="phone"]')) {
    setupPhoneValidation(field);
  }
  document.addEventListener("invalid", (event) => {
    const field = event.target;
    if (!field.validity || !field.willValidate) return;
    showFieldError(field, fieldMessage(field));
  }, true);
  for (const event of ["input", "change"]) {
    document.addEventListener(event, ({ target }) => {
      if (target.dataset?.smartoErrorId && target.validity?.valid) clearField(target);
    });
  }
  const toast = document.querySelector("#smarto-network-toast");
  if (toast) {
    let timer;
    const show = (message) => {
      toast.textContent = message;
      toast.hidden = false;
      clearTimeout(timer);
      timer = setTimeout(() => { toast.hidden = true; }, 8000);
    };
    window.addEventListener("offline", () => show(ERROR_MESSAGES.offline));
    window.addEventListener("online", () => show(ERROR_MESSAGES.online));
    window.addEventListener("smarto:connection-error", () => show(ERROR_MESSAGES.connection));
  }
}

