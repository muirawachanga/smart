import { ERROR_MESSAGES } from "./error-messages.js";

function showUnexpectedError() {
  const alert = document.querySelector("#smarto-unexpected-error");
  if (!alert) return;
  alert.textContent = ERROR_MESSAGES.pageUnexpected;
  alert.hidden = false;
}

window.addEventListener("error", showUnexpectedError);
window.addEventListener("unhandledrejection", showUnexpectedError);
