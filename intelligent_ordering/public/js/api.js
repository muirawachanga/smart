const API_ROOT = "/api/method/intelligent_ordering.api";

export class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

export async function get(endpoint, parameters = {}) {
  const query = new URLSearchParams(parameters);
  const suffix = query.size ? `?${query}` : "";
  return request(`${API_ROOT}.${endpoint}${suffix}`, endpoint, {
    method: "GET",
    headers: { Accept: "application/json" },
  });
}

export async function post(endpoint, parameters = {}) {
  const body = new URLSearchParams(parameters);
  return request(`${API_ROOT}.${endpoint}`, endpoint, {
    method: "POST",
    headers: {
      Accept: "application/json",
      "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
      "X-Frappe-CSRF-Token": window.frappe?.csrf_token || "",
    },
    body,
  });
}

async function request(url, operation, options) {
  let response;
  try {
    response = await fetch(url, {
      ...options,
      credentials: "same-origin",
    });
  } catch {
    throw new Error(`Could not connect to the server. Check your connection and try again. (Operation: ${operation})`);
  }
  const payload = await readResponse(response, operation);
  return payload.message;
}

export async function readResponse(response, operation, { login = false } = {}) {
  let payload;
  try {
    payload = await response.json();
  } catch {
    const status = Number.isInteger(response.status) ? `, HTTP ${response.status}` : "";
    throw new Error(`The server returned an invalid response. Try again or contact support. (Operation: ${operation}${status})`);
  }

  if (!response.ok) {
    const status = response.status;
    let message;
    if (login && status === 401) message = "Invalid credentials. Please try again.";
    else if (status === 401) message = "Your session may have expired. Sign in and try again.";
    else if (status === 403) message = "You do not have permission for this action, or your session has expired.";
    else if (status === 429) message = "Too many attempts. Please try again later.";
    else if (status === 501 && ["accounts.create_account", "accounts.send_invitation"].includes(operation)) {
      message = "Outgoing email is unavailable. Check the default outgoing Email Account in Frappe, then retry.";
    }
    else if (status >= 500) message = "The server encountered an error. Contact your administrator.";
    else message = serverErrorMessage(payload);
    const code = Number.isInteger(status) ? `, HTTP ${status}` : "";
    throw new ApiError(`${message} (Operation: ${operation}${code})`, status);
  }
  return payload;
}

export function serverErrorMessage(payload) {
  if (typeof payload?.message === "string" && payload.message) {
    return payload.message;
  }
  if (typeof payload?._server_messages === "string") {
    try {
      const messages = JSON.parse(payload._server_messages);
      if (Array.isArray(messages)) {
        const last = messages.at(-1);
        const message = typeof last === "string" ? JSON.parse(last) : last;
        if (typeof message?.message === "string") {
          return message.message;
        }
      }
    } catch {
      // Invalid server error metadata must not mask the failed request.
    }
  }
  return "The request could not be completed.";
}
