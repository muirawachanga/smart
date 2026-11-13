import json
import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP


MAX_CART_LINES = 100
MAX_CART_QUANTITY = 9999
MAX_CART_PAYLOAD_LENGTH = 32_768


def validate_cart_quantity(value):
    if isinstance(value, bool):
        raise ValueError("Quantity must be a positive whole number.")

    if isinstance(value, int):
        quantity = value
    elif isinstance(value, str) and re.fullmatch(r"[0-9]+", value.strip()):
        quantity = int(value.strip())
    else:
        raise ValueError("Quantity must be a positive whole number.")

    if quantity < 1:
        raise ValueError("Quantity must be greater than zero.")
    if quantity > MAX_CART_QUANTITY:
        raise ValueError(f"Quantity must not exceed {MAX_CART_QUANTITY}.")
    return quantity


def parse_cart_items(value):
    if value is None or value == "":
        return []

    if isinstance(value, str):
        if len(value) > MAX_CART_PAYLOAD_LENGTH:
            raise ValueError("Cart data is too large.")
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            raise ValueError("Cart data must be valid JSON.") from None

    if not isinstance(value, list):
        raise ValueError("Cart items must be a list.")
    if len(value) > MAX_CART_LINES:
        raise ValueError(f"A cart cannot contain more than {MAX_CART_LINES} items.")

    items = []
    positions = {}
    for item in value:
        if not isinstance(item, dict):
            raise ValueError("Each cart item must be an object.")

        product = item.get("product")
        if not isinstance(product, str):
            raise ValueError("Each cart item must include a product identifier.")
        product = product.strip()
        if not product or len(product) > 140:
            raise ValueError("Product identifiers must contain 1 to 140 characters.")

        quantity = validate_cart_quantity(item.get("quantity"))
        position = positions.get(product)
        if position is None:
            if len(items) == MAX_CART_LINES:
                raise ValueError(f"A cart cannot contain more than {MAX_CART_LINES} items.")
            positions[product] = len(items)
            items.append({"product": product, "quantity": quantity})
        else:
            combined = items[position]["quantity"] + quantity
            items[position]["quantity"] = validate_cart_quantity(combined)

    return items


def merge_cart_items(*groups):
    merged = []
    positions = {}

    for group in groups:
        for item in group:
            position = positions.get(item["product"])
            if position is None:
                if len(merged) == MAX_CART_LINES:
                    raise ValueError(
                        f"A cart cannot contain more than {MAX_CART_LINES} items."
                    )
                positions[item["product"]] = len(merged)
                merged.append(
                    {
                        "product": item["product"],
                        "quantity": validate_cart_quantity(item["quantity"]),
                    }
                )
            else:
                combined = merged[position]["quantity"] + item["quantity"]
                merged[position]["quantity"] = validate_cart_quantity(combined)

    return merged


def round_money(value):
    try:
        amount = Decimal(str(value or 0))
    except (InvalidOperation, ValueError):
        raise ValueError("A product has an invalid price.") from None
    if not amount.is_finite():
        raise ValueError("A product has an invalid price.")
    return float(amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
