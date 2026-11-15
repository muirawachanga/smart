function showUnexpectedError(code) {
  const alert = document.querySelector("#smarto-unexpected-error");
  if (!alert) return;
  alert.textContent = `An unexpected page error occurred (${code}). Reload the page; if it persists, contact support. Time: ${new Date().toISOString()}.`;
  alert.hidden = false;
}

window.addEventListener("error", () => showUnexpectedError("PAGE-ERROR"));
window.addEventListener("unhandledrejection", () => showUnexpectedError("PAGE-REQUEST"));
