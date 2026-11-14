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
  return request(`${API_ROOT}.${endpoint}${suffix}`, {
    method: "GET",
    headers: { Accept: "application/json" },
  });
}

export async function post(endpoint, parameters = {}) {
  const body = new URLSearchParams(parameters);
  return request(`${API_ROOT}.${endpoint}`, {
    method: "POST",
    headers: {
      Accept: "application/json",
      "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
      "X-Frappe-CSRF-Token": window.frappe?.csrf_token || "",
    },
    body,
  });
}

async function request(url, options) {
  const response = await fetch(url, {
    ...options,
    credentials: "same-origin",
  });
  let payload;
  try {
    payload = await response.json();
  } catch {
    throw new Error("The server returned an invalid response.");
  }

  if (!response.ok) {
    throw new ApiError(serverErrorMessage(payload), response.status);
  }

  return payload.message;
}

function serverErrorMessage(payload) {
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
