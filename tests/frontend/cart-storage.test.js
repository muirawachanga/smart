import assert from "node:assert/strict";
import test from "node:test";

import {
  clearGuestCart,
  readGuestCart,
  writeGuestCart,
} from "../../intelligent_ordering/public/js/cart-storage.js";

function createStorage() {
  const entries = new Map();
  return {
    getItem: (key) => entries.get(key) ?? null,
    setItem: (key, value) => entries.set(key, value),
    removeItem: (key) => entries.delete(key),
  };
}

test("guest cart persists across reloads using browser storage", () => {
  const storage = createStorage();
  writeGuestCart(
    [{ product: "SKU-1", quantity: 2, unit_price: 900 }],
    storage,
  );

  assert.deepEqual(readGuestCart(storage), [
    { product: "SKU-1", quantity: 2 },
  ]);
});

test("guest cart storage can be cleared", () => {
  const storage = createStorage();
  writeGuestCart([{ product: "SKU-1", quantity: 1 }], storage);
  clearGuestCart(storage);

  assert.deepEqual(readGuestCart(storage), []);
});

test("invalid saved guest data is reported instead of silently discarded", () => {
  const storage = createStorage();
  storage.setItem("intelligent-ordering.guest-cart.v1", "{invalid");

  assert.throws(() => readGuestCart(storage), /saved guest cart is invalid/i);
});
