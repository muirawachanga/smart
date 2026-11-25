import { get, post } from "./api.js";
import { displayError } from "./error-messages.js";

const section = document.querySelector("#contact-verification");
const status = document.querySelector("#contact-verification-status");
const feedback = document.querySelector("#contact-verification-feedback");
const emailForm = document.querySelector("#contact-email-confirm");
const phoneForm = document.querySelector("#contact-phone-confirm");
const emailSend = document.querySelector("#contact-email-send");
const phoneSend = document.querySelector("#contact-phone-send");
let emailToken = "";
let busy = false;
let loaded = false;
let verification = {};
let revision = 0;

function controls() {
  emailSend.disabled = busy || !loaded || verification.email_verified;
  phoneSend.disabled = busy || !loaded || verification.phone_verified;
  emailForm.querySelector('button[type="submit"]').disabled = busy || !loaded || !emailToken;
  phoneForm.querySelector('button[type="submit"]').disabled = busy || !loaded || verification.phone_verified;
}

async function load() {
  const request = ++revision;
  loaded = false;
  controls();
  try {
    const profile = await get("customers.get_profile");
    if (request !== revision) return;
    verification = profile.verification;
    status.textContent = `Email: ${verification.email_verified ? "verified" : "not verified"}. `
      + `Phone: ${verification.phone_verified ? "verified" : "not verified"}. `
      + (verification.required_for_ordering ? "Both are required before ordering." : "Existing account: ordering remains available.");
    loaded = true;
  } catch (error) {
    if (request !== revision) return;
    status.textContent = "Contact verification status could not be loaded.";
    feedback.textContent = displayError(error);
  } finally {
    if (request === revision) controls();
  }
}

async function action(endpoint, values) {
  if (busy || !loaded) return;
  busy = true;
  controls();
  feedback.textContent = "";
  try {
    const result = await post(endpoint, values);
    feedback.textContent = result.message;
    if (endpoint === "contact_verification.confirm") {
      if (values.channel === "email") {
        emailToken = "";
        emailForm.hidden = true;
      } else {
        phoneForm.reset();
      }
      await load();
    }
  } catch (error) {
    feedback.textContent = displayError(error);
  } finally {
    busy = false;
    controls();
  }
}

if (section) {
  const fragment = new URLSearchParams(window.location.hash.slice(1));
  if (fragment.has("verify-email")) {
    emailToken = fragment.get("verify-email") || "";
    window.history.replaceState(null, "", window.location.pathname + window.location.search);
    emailForm.hidden = !emailToken;
  }
  emailSend.addEventListener("click", () => action("contact_verification.request", { channel: "email" }));
  phoneSend.addEventListener("click", () => action("contact_verification.request", { channel: "phone" }));
  emailForm.addEventListener("submit", (event) => {
    event.preventDefault();
    if (emailToken) return action("contact_verification.confirm", { channel: "email", token: emailToken });
  });
  phoneForm.addEventListener("submit", (event) => {
    event.preventDefault();
    if (phoneForm.reportValidity()) {
      return action("contact_verification.confirm", { channel: "phone", token: phoneForm.elements.token.value });
    }
  });
  document.addEventListener("smarto:profile-saved", () => {
    load();
  });
  load();
}
