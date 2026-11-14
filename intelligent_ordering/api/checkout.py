import re
from hmac import compare_digest

import frappe

from intelligent_ordering.api.cart import get_cart
from intelligent_ordering.utils.delivery_rates import get_area_quote, list_checkout_areas
from intelligent_ordering.utils.cart import round_money
from intelligent_ordering.utils.inventory import validate_checkout_stock
from intelligent_ordering.utils.checkout import (
    checkout_cart_revision,
    validate_address,
    validate_customer_name,
    validate_phone,
    validate_request_token,
)


@frappe.whitelist(allow_guest=True)
def get_checkout(delivery_area=""):
    if frappe.session.user == "Guest":
        return {"requires_login": True}

    user = _require_customer()
    cart = get_cart()
    profile = frappe.db.get_value(
        "Customer Profile",
        {"user": user},
        ["name", "full_name", "phone", "enabled"],
        as_dict=True,
    )
    if profile and not profile.enabled:
        frappe.throw("The customer profile is disabled.", frappe.PermissionError)

    result = {
        "requires_login": False,
        "customer_name": profile.full_name if profile else "",
        "phone": profile.phone if profile else "",
        "cart": cart,
        "cart_revision": checkout_cart_revision(cart["items"]),
        "delivery_areas": list_checkout_areas(cart["currency"]),
        "saved_addresses": frappe.get_all(
            "Customer Address", filters={"customer": profile.name},
            fields=["name", "address_label", "address_line_1", "address_line_2", "city", "region", "postal_code", "is_default"],
            order_by="is_default desc, creation desc", limit_page_length=100,
        ) if profile else [],
    }
    if delivery_area:
        quote = get_area_quote(delivery_area, cart["currency"])
        result.update(quote)
        result["total"] = round_money(cart["total"] + quote["delivery_fee"])
    return result


@frappe.whitelist(allow_guest=True, methods=["POST"])
def get_checkout_attempt(request_token):
    """Recover a submitted order after an interrupted checkout response."""
    if frappe.session.user == "Guest":
        return {"requires_login": True}
    user = _require_customer()
    try:
        request_token = validate_request_token(request_token)
    except ValueError as error:
        frappe.throw(str(error), frappe.ValidationError)
    previous_order = frappe.db.get_value(
        "Sales Order",
        {"checkout_token": request_token},
        ["name", "customer"],
        as_dict=True,
    )
    if not previous_order:
        return {"order_name": None}
    owner = frappe.db.get_value(
        "Customer Profile", previous_order.customer, "user"
    )
    if owner != user:
        frappe.throw("This checkout request is unavailable.", frappe.PermissionError)
    return {"order_name": previous_order.name}


@frappe.whitelist(methods=["POST"])
def create_order(
    customer_name,
    phone,
    address_line_1,
    city,
    request_token,
    cart_revision,
    address_line_2="",
    region="",
    postal_code="",
    delivery_area="",
    delivery_quote="",
):
    user = _require_customer()
    try:
        request_token = validate_request_token(request_token)
    except ValueError as error:
        frappe.throw(str(error), frappe.ValidationError)

    previous_order = frappe.db.get_value(
        "Sales Order",
        {"checkout_token": request_token},
        ["name", "customer"],
        as_dict=True,
    )
    if previous_order:
        owner = frappe.db.get_value(
            "Customer Profile", previous_order.customer, "user"
        )
        if owner != user:
            frappe.throw(
                "This checkout request belongs to another customer.",
                frappe.PermissionError,
            )
        return {
            "duplicate": True,
            "order": _order_summary(previous_order.name),
            "cart": get_cart(),
        }

    try:
        customer_name = validate_customer_name(customer_name)
        phone = validate_phone(phone)
        address = validate_address(
            address_line_1,
            city,
            address_line_2,
            region,
            postal_code,
        )
    except ValueError as error:
        frappe.throw(str(error), frappe.ValidationError)

    if not isinstance(cart_revision, str) or not re.fullmatch(
        r"[0-9a-f]{64}", cart_revision
    ):
        frappe.throw("Refresh and review your cart before submitting.", frappe.ValidationError)

    cart = get_cart()
    if not cart["items"]:
        frappe.throw("Your cart is empty.", frappe.ValidationError)
    validate_checkout_stock(cart["items"])
    locked_items = []
    for item in cart["items"]:
        rows = frappe.db.sql(
            """SELECT price, currency, category, enabled
               FROM `tabProduct` WHERE name = %s FOR UPDATE""",
            item["product"],
            as_dict=True,
        )
        product = rows[0] if rows else None
        if not product or not product.enabled:
            frappe.throw("The order contains an unavailable product.", frappe.ValidationError)
        if product.category:
            categories = frappe.db.sql(
                "SELECT enabled FROM `tabProduct Category` WHERE name = %s FOR UPDATE",
                product.category,
                as_dict=True,
            )
            if not categories or not categories[0].enabled:
                frappe.throw("The order contains an unavailable product.", frappe.ValidationError)
        try:
            unit_price = round_money(product.price)
        except ValueError as error:
            frappe.throw(str(error), frappe.ValidationError)
        locked_items.append({
            "product": item["product"],
            "quantity": item["quantity"],
            "unit_price": unit_price,
            "currency": (product.currency or "KES").upper(),
        })
    current_revision = checkout_cart_revision(locked_items)
    if not compare_digest(cart_revision, current_revision):
        frappe.throw(
            "Your cart or product prices changed. Review the cart and submit again.",
            frappe.ValidationError,
        )
    quote = get_area_quote(delivery_area, cart["currency"], for_update=True)
    if not isinstance(delivery_quote, str) or not compare_digest(
        delivery_quote, quote["delivery_quote"]
    ):
        frappe.throw("Delivery charges changed. Refresh checkout and review the total.", frappe.ValidationError)

    profile = _save_customer_profile(user, customer_name, phone)
    address_doc = _get_or_create_address(profile.name, address)
    address_snapshot = ", ".join(
        part
        for part in (
            address["address_line_1"],
            address["address_line_2"],
            address["city"],
            address["region"],
            address["postal_code"],
        )
        if part
    )

    order = frappe.get_doc(
        {
            "doctype": "Sales Order",
            "customer": profile.name,
            "customer_name_snapshot": customer_name,
            "customer_phone_snapshot": phone,
            "delivery_address": address_doc.name,
            "delivery_address_snapshot": address_snapshot,
            "delivery_area": quote["delivery_area"],
            "status": "Pending",
            "payment_status": "Unpaid",
            "items": [
                {
                    "product": item["product"],
                    "quantity": item["quantity"],
                }
                for item in cart["items"]
            ],
            "checkout_token": request_token,
        }
    )
    was_creating_checkout_order = getattr(
        frappe.flags, "creating_checkout_order", False
    )
    frappe.flags.creating_checkout_order = True
    try:
        order.insert(ignore_permissions=True)
    finally:
        frappe.flags.creating_checkout_order = was_creating_checkout_order

    shopping_cart_name = frappe.db.get_value(
        "Shopping Cart", {"user": user}, "name"
    )
    if shopping_cart_name:
        shopping_cart = frappe.get_doc("Shopping Cart", shopping_cart_name)
        shopping_cart.set("items", [])
        shopping_cart.save()

    return {
        "duplicate": False,
        "order": _serialize_order(order),
        "cart": get_cart(),
    }


def _require_customer():
    user = frappe.session.user
    if user == "Guest" or "Customer" not in frappe.get_roles(user):
        frappe.throw("Sign in with a customer account to continue.", frappe.PermissionError)
    return user


def _save_customer_profile(user, customer_name, phone):
    frappe.db.sql("SELECT name FROM `tabUser` WHERE name = %s FOR UPDATE", user)
    profile_name = frappe.db.get_value(
        "Customer Profile", {"user": user}, "name"
    )
    if profile_name:
        profile = frappe.get_doc("Customer Profile", profile_name)
        if not profile.enabled:
            frappe.throw("The customer profile is disabled.", frappe.PermissionError)
        if profile.full_name != customer_name or profile.phone != phone:
            profile.full_name = customer_name
            profile.phone = phone
            profile.save(ignore_permissions=True)
        return profile

    return frappe.get_doc(
        {
            "doctype": "Customer Profile",
            "user": user,
            "full_name": customer_name,
            "phone": phone,
            "enabled": 1,
        }
    ).insert(ignore_permissions=True)


def _get_or_create_address(customer, address):
    filters = {"customer": customer, **address}
    address_name = frappe.db.get_value("Customer Address", filters, "name")
    if address_name:
        return frappe.get_doc("Customer Address", address_name)

    has_default = frappe.db.exists(
        "Customer Address", {"customer": customer, "is_default": 1}
    )
    return frappe.get_doc(
        {
            "doctype": "Customer Address",
            **filters,
            "is_default": 0 if has_default else 1,
        }
    ).insert(ignore_permissions=True)


def _order_summary(order_name):
    order = frappe.get_doc("Sales Order", order_name)
    return _serialize_order(order)


def _serialize_order(order):
    return {
        "cancellation_request_status": order.get("cancellation_request_status"),
        "cancellation_reason": order.get("cancellation_reason"),
        "cancellation_response": order.get("cancellation_response"),
        "name": order.name,
        "order_datetime": order.order_datetime,
        "status": order.status,
        "payment_status": order.payment_status,
        "customer_name": order.customer_name_snapshot,
        "customer_phone": order.customer_phone_snapshot,
        "delivery_address": order.delivery_address_snapshot,
        "delivery_area": order.get("delivery_area"),
        "delivery_fee": order.get("delivery_fee") or 0,
        "currency": order.currency,
        "subtotal": order.subtotal,
        "total": order.total,
        "items": [
            {
                "product": item.product,
                "product_name": item.product_name_snapshot,
                "sku": item.product_sku_snapshot,
                "category": item.get("product_category_snapshot") or "",
                "quantity": item.quantity,
                "unit_price": item.unit_price,
                "line_total": item.line_total,
            }
            for item in order.items
        ],
    }
