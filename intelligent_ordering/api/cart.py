from decimal import Decimal

import frappe

from intelligent_ordering.utils.cart import (
    MAX_CART_QUANTITY,
    merge_cart_items,
    parse_cart_items,
    round_money,
    validate_cart_quantity,
)
from intelligent_ordering.utils.inventory import available_stock


@frappe.whitelist(allow_guest=True, methods=["POST"])
def get_cart(guest_items="[]"):
    """Return the browser cart for guests or the signed-in customer's saved cart."""
    user = frappe.session.user
    if user == "Guest":
        return _serialize_items(_parse_items(guest_items), is_guest=True)

    _require_customer(user)
    cart = _get_user_cart(user)
    if not cart:
        return _serialize_items([], is_guest=False)
    removed = _refresh_cart(cart)
    return _serialize_document(cart, removed_products=removed)


@frappe.whitelist(allow_guest=True, methods=["POST"])
def add_item(product, quantity=1, guest_items="[]"):
    quantity = _parse_quantity(quantity)
    product = _validate_product_identifier(product)
    _get_enabled_product(product)
    user = frappe.session.user

    if user == "Guest":
        items = _merge_items(
            _parse_items(guest_items), [{"product": product, "quantity": quantity}]
        )
        _validate_stock_quantities(items, {product})
        return _serialize_items(items, is_guest=True)

    _require_customer(user)
    cart = _get_or_create_user_cart(user)
    removed = _remove_unavailable_rows(cart)
    items = _merge_items(_document_items(cart), [{"product": product, "quantity": quantity}])
    _validate_stock_quantities(items, {product})
    _replace_items(cart, items)
    cart.save()
    return _serialize_document(cart, removed_products=removed)


@frappe.whitelist(allow_guest=True, methods=["POST"])
def update_item(product, quantity, guest_items="[]"):
    product = _validate_product_identifier(product)
    quantity = _parse_quantity(quantity)
    _get_enabled_product(product)
    user = frappe.session.user

    if user == "Guest":
        items = _parse_items(guest_items)
        if not any(item["product"] == product for item in items):
            frappe.throw("This product is not in the cart.", frappe.ValidationError)
        updated = [
            {"product": item["product"], "quantity": quantity}
            if item["product"] == product
            else item
            for item in items
        ]
        _validate_stock_quantities(updated, {product})
        return _serialize_items(updated, is_guest=True)

    _require_customer(user)
    cart = _get_user_cart(user)
    if not cart:
        frappe.throw("This product is not in the cart.", frappe.ValidationError)

    removed = _remove_unavailable_rows(cart)
    items = _document_items(cart)
    if not any(item["product"] == product for item in items):
        frappe.throw("This product is not in the cart.", frappe.ValidationError)

    updated = [
        {"product": item["product"], "quantity": quantity}
        if item["product"] == product
        else item
        for item in items
    ]
    _validate_stock_quantities(updated, {product})
    _replace_items(cart, updated)
    cart.save()
    return _serialize_document(cart, removed_products=removed)


@frappe.whitelist(allow_guest=True, methods=["POST"])
def remove_item(product, guest_items="[]"):
    product = _validate_product_identifier(product)
    user = frappe.session.user

    if user == "Guest":
        items = [
            item
            for item in _parse_items(guest_items)
            if item["product"] != product
        ]
        return _serialize_items(items, is_guest=True)

    _require_customer(user)
    cart = _get_user_cart(user)
    if not cart:
        return _serialize_items([], is_guest=False)

    removed = _remove_unavailable_rows(cart)
    items = [
        item for item in _document_items(cart) if item["product"] != product
    ]
    _replace_items(cart, items)
    cart.save()
    return _serialize_document(cart, removed_products=removed)


@frappe.whitelist(allow_guest=True, methods=["POST"])
def clear_cart():
    user = frappe.session.user
    if user == "Guest":
        return _serialize_items([], is_guest=True)

    _require_customer(user)
    cart = _get_user_cart(user)
    if not cart:
        return _serialize_items([], is_guest=False)

    cart.set("items", [])
    cart.save()
    return _serialize_document(cart)


@frappe.whitelist(methods=["POST"])
def merge_guest_cart(guest_items):
    """Merge a browser's guest cart into the authenticated user's saved cart."""
    user = frappe.session.user
    _require_customer(user)
    incoming = _parse_items(guest_items)
    cart = _get_user_cart(user)
    if not cart and not incoming:
        return _serialize_items([], is_guest=False)

    removed = []
    available_incoming = []
    for item in incoming:
        product = _get_product(item["product"])
        if not _is_available(product):
            removed.append(item["product"])
            continue
        available_incoming.append(item)

    if not cart and not available_incoming:
        return _serialize_items([], is_guest=False, removed_products=removed)
    if not cart:
        cart = _get_or_create_user_cart(user)
    removed.extend(_remove_unavailable_rows(cart))

    items = _merge_items(_document_items(cart), available_incoming)
    _validate_stock_quantities(
        items, {item["product"] for item in available_incoming}
    )
    _replace_items(cart, items)
    cart.save()
    return _serialize_document(cart, removed_products=removed)


def _require_customer(user):
    if user == "Guest" or "Customer" not in frappe.get_roles(user):
        frappe.throw("Customer access is required.", frappe.PermissionError)


def _get_user_cart(user):
    cart_name = frappe.db.get_value("Shopping Cart", {"user": user}, "name")
    return frappe.get_doc("Shopping Cart", cart_name) if cart_name else None


def _get_or_create_user_cart(user):
    cart = _get_user_cart(user)
    if cart:
        return cart
    return frappe.get_doc(
        {"doctype": "Shopping Cart", "user": user, "items": []}
    ).insert()


def _get_product(product):
    return frappe.db.get_value(
        "Product",
        product,
        [
            "name",
            "sku",
            "product_name",
            "category",
            "image",
            "price",
            "currency",
            "enabled",
        ],
        as_dict=True,
    )


def _get_enabled_product(product):
    record = _get_product(product)
    if not _is_available(record):
        frappe.throw("The selected product is unavailable.", frappe.ValidationError)
    return record


def _is_available(product):
    if not product or not product.enabled:
        return False
    return not product.category or frappe.db.exists(
        "Product Category", {"name": product.category, "enabled": 1}
    )


def _validate_product_identifier(product):
    if not isinstance(product, str):
        frappe.throw("A product identifier is required.", frappe.ValidationError)
    product = product.strip()
    if not product or len(product) > 140:
        frappe.throw(
            "Product identifiers must contain 1 to 140 characters.",
            frappe.ValidationError,
        )
    return product


def _parse_quantity(value):
    try:
        return validate_cart_quantity(value)
    except ValueError as error:
        frappe.throw(str(error), frappe.ValidationError)


def _parse_items(value):
    try:
        return parse_cart_items(value)
    except ValueError as error:
        frappe.throw(str(error), frappe.ValidationError)


def _merge_items(*groups):
    try:
        return merge_cart_items(*groups)
    except ValueError as error:
        frappe.throw(str(error), frappe.ValidationError)


def _validate_stock_quantities(items, products=None):
    for item in items:
        if products is not None and item["product"] not in products:
            continue
        available_quantity = available_stock(item["product"])
        if item["quantity"] > available_quantity:
            frappe.throw(
                f"Only {available_quantity} units of "
                f"{item['product']} are available.",
                frappe.ValidationError,
            )


def _document_items(cart):
    return [
        {"product": item.product, "quantity": item.quantity}
        for item in cart.items
    ]


def _replace_items(cart, items):
    cart.set("items", [])
    for item in items:
        cart.append("items", item)


def _remove_unavailable_rows(cart):
    active_rows = []
    removed = []
    for item in cart.items:
        product = _get_product(item.product)
        if not _is_available(product):
            removed.append(item.product)
        else:
            active_rows.append(item)
    if len(active_rows) != len(cart.items):
        cart.set("items", active_rows)
    return removed


def _refresh_cart(cart):
    previous = _cart_snapshot(cart)
    removed = _remove_unavailable_rows(cart)
    cart.validate()
    if previous != _cart_snapshot(cart):
        cart.save()
    return removed


def _cart_snapshot(cart):
    return (
        cart.currency,
        str(cart.total),
        tuple(
            (
                item.product,
                str(item.quantity),
                str(item.currency),
                str(item.unit_price),
                str(item.subtotal),
            )
            for item in cart.items
        ),
    )


def _serialize_document(cart, removed_products=None):
    items = [
        {"product": item.product, "quantity": item.quantity}
        for item in cart.items
    ]
    response = _serialize_items(items, is_guest=False)
    response["removed_products"] = removed_products or []
    return response


def _serialize_items(items, is_guest, removed_products=None):
    response_items = []
    currencies = set()
    total = Decimal("0.00")
    item_count = 0

    for item in items:
        product = _get_product(item["product"])
        available = _is_available(product)
        available_quantity = (
            available_stock(item["product"]) if product else 0
        )
        quantity = item["quantity"]
        item_count += quantity

        if available:
            currency = (product.currency or "KES").upper()
            available = quantity <= available_quantity
            currencies.add(currency)
            unit_price = _money(product.price)
            subtotal = _money(unit_price * quantity)
            total += Decimal(str(subtotal))
            name = product.product_name
            image = product.image
            sku = product.sku
        else:
            currency = None
            unit_price = None
            subtotal = None
            name = "Unavailable product"
            image = None
            sku = None

        stock_status = (
            "Unavailable"
            if not _is_available(product)
            else "In Stock" if available_quantity else "Out of Stock"
        )
        response_items.append(
            {
                "product": item["product"],
                "sku": sku,
                "product_name": name,
                "image": image,
                "available": available,
                "available_quantity": available_quantity,
                "stock_status": stock_status,
                "currency": currency,
                "unit_price": unit_price,
                "quantity": quantity,
                "subtotal": subtotal,
            }
        )

    if len(currencies) > 1:
        frappe.throw(
            "Products in one cart must use the same currency.",
            frappe.ValidationError,
        )
    currency = next(iter(currencies), "KES")

    return {
        "items": response_items,
        "item_count": item_count,
        "currency": currency,
        "total": _money(total),
        "is_guest": is_guest,
        "max_quantity": MAX_CART_QUANTITY,
        "removed_products": removed_products or [],
    }


def _money(value):
    try:
        return round_money(value)
    except ValueError as error:
        frappe.throw(str(error), frappe.ValidationError)
