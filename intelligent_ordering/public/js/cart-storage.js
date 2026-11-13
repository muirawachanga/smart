const STORAGE_KEY = "intelligent-ordering.guest-cart.v1";

export function readGuestCart(storage = globalThis.localStorage) {
  const saved = storage.getItem(STORAGE_KEY);
  if (saved === null) {
    return [];
  }

  let items;
  try {
    items = JSON.parse(saved);
  } catch {
    throw new Error("The saved guest cart is invalid. Clear it to continue.");
  }

  if (
    !Array.isArray(items) ||
    items.some(
      (item) =>
        !item ||
        typeof item.product !== "string" ||
        !Number.isInteger(item.quantity) ||
        item.quantity < 1,
    )
  ) {
    throw new Error("The saved guest cart is invalid. Clear it to continue.");
  }

  return items.map(({ product, quantity }) => ({ product, quantity }));
}

export function writeGuestCart(items, storage = globalThis.localStorage) {
  const minimalItems = items.map(({ product, quantity }) => ({
    product,
    quantity,
  }));
  storage.setItem(STORAGE_KEY, JSON.stringify(minimalItems));
}

export function clearGuestCart(storage = globalThis.localStorage) {
  storage.removeItem(STORAGE_KEY);
}
