import { ApiError, fetchWithTimeout, get } from "./api.js";
import { ERROR_MESSAGES, displayError } from "./error-messages.js";
import { showValidationError } from "./error-ui.js";

const page = document.querySelector("[data-auth-page]");
const kind = page.dataset.authPage;
const form = document.querySelector("#auth-form");
const status = document.querySelector("#auth-status");
const error = document.querySelector("#auth-error");
let busy = false;
let challenge = "";

async function request(endpoint, values) {
  const operation = kind === "login" ? "authentication.login"
    : kind === "register" ? "customers.register"
      : kind === "forgot" ? "authentication.forgot_password" : "authentication.reset_password";
  try {
    return await fetchWithTimeout(endpoint, {
      method: "POST",
      credentials: "same-origin",
      headers: {
        Accept: "application/json",
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "X-Frappe-CSRF-Token": page.dataset.authCsrf,
      },
      body: new URLSearchParams(values),
    }, operation, { login: kind === "login", customer: true });
  } catch (error) {
    if (error instanceof ApiError) throw error;
    throw new ApiError(ERROR_MESSAGES.connection);
  }
}

async function finishLogin(payload) {
  if (payload.message === "Password Reset") {
    const destination = new URL(payload.redirect_to, window.location.origin);
    if (destination.origin !== window.location.origin || destination.pathname !== "/update-password") {
      throw new Error("The password reset destination is invalid.");
    }
    window.location.assign(`/reset-password${destination.search}`);
    return;
  }
  if (payload.verification) {
    if (!payload.tmp_id) throw new Error("The verification challenge could not be started.");
    challenge = payload.tmp_id;
    form.elements.password.value = "";
    form.hidden = true;
    document.querySelector("#auth-otp-form").hidden = false;
    const verification = payload.verification;
    document.querySelector("#auth-otp-prompt").textContent = verification.setup
      ? (verification.prompt || `Enter the code from your ${verification.method}.`)
      : "Verification could not be delivered or is not configured. Contact your administrator.";
    document.querySelector("#auth-otp-form").querySelector('button[type="submit"]').disabled = !verification.setup;
    status.textContent = "Additional verification is required.";
    return;
  }
  if (!["Logged In", "No App"].includes(payload.message)) {
    throw new Error("Sign-in was not completed. Please try again.");
  }
  const redirect = new URLSearchParams(window.location.search).get("redirect-to") || "";
  const result = await get("authentication.destination", { redirect_to: redirect });
  const target = result?.destination;
  if (typeof target !== "string" || !target.startsWith("/") || target.startsWith("//")) {
    throw new Error("The sign-in destination is invalid.");
  }
  window.location.assign(target);
}

async function submit(event, activeForm) {
  event.preventDefault();
  if (busy || !activeForm.reportValidity()) return;
  const values = Object.fromEntries(new FormData(activeForm));
  if (values.confirm_password !== undefined && values.password !== values.confirm_password) {
    error.textContent = ERROR_MESSAGES.passwordMatch;
    showValidationError(activeForm.elements.confirm_password, ERROR_MESSAGES.passwordMatch);
    return;
  }
  busy = true;
  const button = activeForm.querySelector('button[type="submit"]');
  button.disabled = true;
  activeForm.setAttribute("aria-busy", "true");
  status.textContent = "Please wait...";
  error.textContent = "";
  try {
    if (kind === "login") {
      const credentials = challenge
        ? { cmd: "login", otp: values.otp, tmp_id: challenge }
        : { cmd: "login", usr: values.email, pwd: values.password };
      await finishLogin(await request("/", credentials));
    } else {
      if (kind === "register") {
        values.marketing_consent = activeForm.elements.marketing_consent.checked ? "1" : "0";
      }
      if (kind === "reset") {
        values.key = new URLSearchParams(window.location.search).get("key") || "";
        if (!values.key) throw new ApiError(ERROR_MESSAGES.reset);
      }
      const endpoint = kind === "register" ? "customers.register"
        : kind === "forgot" ? "authentication.forgot_password" : "authentication.reset_password";
      const result = await request(`/api/method/intelligent_ordering.api.${endpoint}`, values);
      status.textContent = result.message.message;
      if (kind !== "forgot") {
        activeForm.reset();
        activeForm.hidden = true;
      }
    }
  } catch (failure) {
    status.textContent = "Could not complete this request.";
    error.textContent = displayError(failure);
  } finally {
    busy = false;
    button.disabled = false;
    activeForm.setAttribute("aria-busy", "false");
  }
}

if (form) form.addEventListener("submit", (event) => submit(event, form));
const otpForm = document.querySelector("#auth-otp-form");
if (otpForm) otpForm.addEventListener("submit", (event) => submit(event, otpForm));
for (const toggle of document.querySelectorAll("[data-toggle-password]")) {
  toggle.addEventListener("click", () => {
    const input = document.getElementById(toggle.dataset.togglePassword);
    const visible = input.type === "password";
    input.type = visible ? "text" : "password";
    toggle.textContent = visible ? "Hide password" : "Show password";
    toggle.setAttribute("aria-pressed", String(visible));
  });
}
const warning = document.querySelector("#smarto-page-script-warning");
if (warning) warning.hidden = true;
