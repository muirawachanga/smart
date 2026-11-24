import { customerError, ERROR_MESSAGES, isCustomerPage } from "./error-messages.js";

const API_ROOT = "/api/method/intelligent_ordering.api";

export async function fetchWithTimeout(url, options, operation, responseOptions = {}, timeoutMs = 30000) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(url, { ...options, signal: controller.signal });
    return await readResponse(response, operation, responseOptions);
  } finally {
    clearTimeout(timer);
  }
}

export class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.customerSafe = true;
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
  try {
    const requestOptions = {
      ...options,
      credentials: "same-origin",
    };
    const payload = isCustomerPage()
      ? await fetchWithTimeout(url, requestOptions, operation)
      : await readResponse(await fetch(url, requestOptions), operation);
    return payload.message;
  } catch (error) {
    if (error instanceof ApiError) throw error;
    if (isCustomerPage() && typeof CustomEvent === "function") {
      window.dispatchEvent?.(new CustomEvent("smarto:connection-error"));
    }
    const message = isCustomerPage()
      ? (operation === "payments.initiate_payment" ? ERROR_MESSAGES.paymentUnknown : ERROR_MESSAGES.connection)
      : `Could not connect to the server. Check your connection and try again. (Operation: ${operation})`;
    throw new ApiError(message);
  }
}

export async function readResponse(response, operation, { login = false, customer = isCustomerPage() } = {}) {
  let payload;
  try {
    payload = await response.json();
  } catch (error) {
    if (error?.name === "AbortError") throw error;
    if (customer) throw new ApiError(
      response.ok ? (operation === "payments.initiate_payment" ? ERROR_MESSAGES.paymentUnknown : ERROR_MESSAGES.unexpected)
        : customerError(response.status, operation), response.status,
    );
    const status = Number.isInteger(response.status) ? `, HTTP ${response.status}` : "";
    throw new ApiError(`The server returned an invalid response. Try again or contact support. (Operation: ${operation}${status})`);
  }

  if (!response.ok) {
    const status = response.status;
    if (customer) {
      throw new ApiError(customerError(status, operation, serverErrorMessage(payload)), status);
    }
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
