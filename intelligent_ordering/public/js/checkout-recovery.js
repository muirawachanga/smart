export const TOKEN_KEY = "smarto.checkout.pending-token.v1";
export const ORDER_KEY = "smarto.checkout.pending-order.v1";
export const FINGERPRINT_KEY = "smarto.checkout.pending-fingerprint.v1";

export function createCheckoutToken() {
  if (typeof crypto.randomUUID === "function") return crypto.randomUUID();
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join("");
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

export async function checkoutFingerprint(submission, previous) {
  const value = JSON.stringify(submission);
  if (previous?.startsWith("json:") || (!previous && !crypto.subtle)) {
    // This is an equality check for retries, not a server authorization token.
    return `json:${value}`;
  }
  if (!crypto.subtle) {
    throw new Error("Use HTTPS or localhost to retry this checkout's original recovery state.");
  }
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(value));
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0")).join("");
}
