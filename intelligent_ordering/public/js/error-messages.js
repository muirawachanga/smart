export const ERROR_MESSAGES = Object.freeze({
  connection: "We couldn't connect. Check your connection and try again.",
  offline: "You're offline. Check your connection and try again.",
  online: "You're back online. Please try again.",
  unexpected: "Something went wrong. Please try again or contact the store.",
  pageUnexpected: "Something went wrong on this page. Reload it, or contact the store if the problem continues.",
  session: "Your session may have ended. Sign in and try again.",
  access: "You can't access this page or action. Sign in with the right account or contact the store.",
  missing: "We couldn't find what you're looking for. Check the link or return to the homepage.",
  busy: "The store is temporarily unavailable. Please try again later or contact the store.",
  rateLimit: "Too many attempts. Please wait a little while and try again.",
  login: "The email or password doesn't match our records. Try again or reset your password.",
  registration: "We couldn't create your account. Check your details or try signing in or resetting your password.",
  reset: "We couldn't use this reset link. Request a new one and try again.",
  invalid: "Please check your details and try again.",
  required: "Please fill in this field.",
  email: "Enter a valid email address, such as name@example.com.",
  phone: "Enter a valid phone number.",
  passwordMatch: "Passwords don't match. Please check and try again.",
  payment: "Payment couldn't be completed. Check your payment details or contact the store before trying again.",
  paymentUnknown: "We couldn't confirm the payment request. Check your payment status or contact the store before trying again.",
  stock: "This item is no longer available in the requested quantity. Update your cart and try again.",
  verifyContacts: "Verify your email and phone in My profile before ordering. Use your verified phone at checkout.",
});

export function isCustomerPage() {
  const path = globalThis.window?.location?.pathname || "";
  if (!path) return false;
  const hash = globalThis.window?.location?.hash || "";
  return !path.startsWith("/dashboard/") && !(path === "/store"
    && ["#admin-dashboard", "#payment-dashboard", "#delivery-dashboard", "#inventory-dashboard"].includes(hash));
}

export function customerError(status, operation = "", message = "") {
  if (status === 429) return ERROR_MESSAGES.rateLimit;
  if (operation === "payments.initiate_payment" && (status === 408 || status >= 500)) return ERROR_MESSAGES.paymentUnknown;
  if (status >= 500) return ERROR_MESSAGES.busy;
  if (operation === "authentication.login") return ERROR_MESSAGES.login;
  if (operation === "customers.register") return ERROR_MESSAGES.registration;
  if (operation === "authentication.reset_password") return ERROR_MESSAGES.reset;
  if (status === 401) return ERROR_MESSAGES.session;
  if (status === 403) return ERROR_MESSAGES.access;
  if (status === 404) return ERROR_MESSAGES.missing;
  if (operation === "checkout.create_order" && message === ERROR_MESSAGES.verifyContacts) return message;
  if (operation.startsWith("contact_verification.") && [
    "This verification link or code is invalid or expired. Request a new one.",
    "Contact verification is unavailable. Contact the store.",
    "Delivery could not be confirmed. If it arrives, use it; otherwise wait before resending.",
    "Wait at least 60 seconds before requesting another verification.",
    "Save a valid contact before requesting verification.",
    "Save your customer profile before verifying contacts.",
  ].includes(message)) return message;
  if (/stock|available quantity|out of stock/i.test(message)) return ERROR_MESSAGES.stock;
  if (/phone|mobile number/i.test(message)) return ERROR_MESSAGES.phone;
  if (operation.startsWith("payments.")) return ERROR_MESSAGES.payment;
  return ERROR_MESSAGES.invalid;
}

export function displayError(error) {
  if (!isCustomerPage()) return error?.message || ERROR_MESSAGES.unexpected;
  return error?.customerSafe === true ? error.message : ERROR_MESSAGES.unexpected;
}
