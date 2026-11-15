import { serverErrorMessage } from "./api.js";

const page = document.querySelector("[data-auth-page]");
const kind = page.dataset.authPage;
const form = document.querySelector("#auth-form");
const status = document.querySelector("#auth-status");
const error = document.querySelector("#auth-error");
let busy = false;
let challenge = "";

async function request(endpoint, values) {
  const response = await fetch(endpoint, {
    method: "POST",
    credentials: "same-origin",
    headers: {
      Accept: "application/json",
      "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
      "X-Frappe-CSRF-Token": page.dataset.authCsrf,
    },
    body: new URLSearchParams(values),
  });
  let payload;
  try {
    payload = await response.json();
  } catch {
    throw new Error("The server returned an invalid response. Please try again.");
  }
  if (!response.ok) {
    throw new Error(response.status === 401 ? "Invalid credentials. Please try again."
      : response.status === 429 ? "Too many attempts. Please try again later."
        : serverErrorMessage(payload));
  }
  return payload;
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
    document.querySelector("#auth-otp-prompt").textContent = payload.verification.setup
      ? `Enter the code from your ${payload.verification.method}.`
      : "Verification is not configured. Contact your administrator.";
    status.textContent = "Additional verification is required.";
    return;
  }
  if (!["Logged In", "No App"].includes(payload.message)) {
    throw new Error("Sign-in was not completed. Please try again.");
  }
  const redirect = new URLSearchParams(window.location.search).get("redirect-to") || "";
  const response = await fetch(`/api/method/intelligent_ordering.api.authentication.destination?${
    new URLSearchParams({ redirect_to: redirect })
  }`, { credentials: "same-origin", headers: { Accept: "application/json" } });
  const result = await response.json();
  if (!response.ok) throw new Error(serverErrorMessage(result));
  const target = result.message?.destination;
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
    error.textContent = "Passwords do not match.";
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
        if (!values.key) throw new Error("Open the reset link from your email to set a new password.");
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
    error.textContent = failure.message;
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
