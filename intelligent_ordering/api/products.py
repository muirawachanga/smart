import re
from decimal import Decimal, InvalidOperation

import frappe

from intelligent_ordering.utils.staff_pages import PAGE_ROLES
from intelligent_ordering.utils.validation import validate_pagination


FIELDS = ["name", "sku", "product_name", "category", "description", "image",
          "price", "currency", "enabled", "modified"]


def _require():
    if frappe.session.user == "Guest" or (
        frappe.session.user != "Administrator"
        and not PAGE_ROLES["products"].intersection(frappe.get_roles(frappe.session.user))
    ):
        frappe.throw("Product management access is required.", frappe.PermissionError)


def _text(value, label, maximum=140, required=False):
    if not isinstance(value, str) or len(value.strip()) > maximum or (required and not value.strip()):
        frappe.throw(f"Enter {label} of at most {maximum} characters.", frappe.ValidationError)
    return value.strip()


def _enabled(value):
    if value not in (0, 1, "0", "1"):
        frappe.throw("Choose a valid product availability.", frappe.ValidationError)
    return int(value)


@frappe.whitelist()
def list_products(search="", page=1, page_size=20):
    _require()
    search = _text(search, "product search", 100)
    try:
        page, page_size = validate_pagination(page, page_size)
    except ValueError as error:
        frappe.throw(str(error), frappe.ValidationError)
    pattern = f"%{search}%"
    products = frappe.get_list(
        "Product", fields=FIELDS,
        or_filters=[[field, "like", pattern] for field in ("sku", "product_name")] if search else [],
        order_by="product_name asc, name asc", limit_start=(page - 1) * page_size,
        limit_page_length=page_size + 1,
    )
    categories = frappe.get_list(
        "Product Category", filters={"enabled": 1}, fields=["name", "category_name"],
        order_by="category_name asc", limit_page_length=0,
    )
    return {
        "products": products[:page_size], "has_more": len(products) > page_size, "page": page,
        "categories": categories,
        "upload_image_types": ["image/png", "image/jpeg", "image/gif"] + (
            ["image/webp"] if frappe.session.user == "Administrator"
            or frappe.get_cached_value("User", frappe.session.user, "user_type") == "System User" else []
        ),
        "can_create_category": bool(frappe.has_permission("Product Category", "create")),
        "can_receive_stock": frappe.session.user == "Administrator" or bool(
            PAGE_ROLES["inventory"].intersection(
                frappe.get_roles(frappe.session.user))),
    }


@frappe.whitelist(methods=["POST"])
def save_product(sku, product_name, category, price, currency="KES", description="",
                 image="", enabled=1, product="", modified=""):
    _require()
    product = _text(product, "product identifier")
    values = {
        "sku": _text(sku, "SKU", required=True),
        "product_name": _text(product_name, "product name", required=True),
        "category": _text(category, "enabled category", required=True),
        "description": _text(description, "description", 1000),
        "currency": _text(currency, "currency", 3, True).upper(),
        "image": _text(image, "image path", 500),
        "enabled": _enabled(enabled),
    }
    if not re.fullmatch(r"[A-Z]{3}", values["currency"]):
        frappe.throw("Currency must be a three-letter code.", frappe.ValidationError)
    try:
        amount = Decimal(str(price))
    except (InvalidOperation, ValueError):
        frappe.throw("Enter a non-negative finite price.", frappe.ValidationError)
    if not amount.is_finite() or amount < 0 or amount > Decimal("999999999.99"):
        frappe.throw("Enter a price between 0 and 999999999.99.", frappe.ValidationError)
    values["price"] = amount
    if values["image"] and (
        not product or not values["image"].startswith("/files/")
        or not re.search(r"\.(png|jpe?g|webp|gif)$", values["image"], re.IGNORECASE)
        or not frappe.db.exists("File", {
            "file_url": values["image"], "is_private": 0,
            "attached_to_doctype": "Product", "attached_to_name": product,
        })
    ):
        frappe.throw("Upload a public image attached to this saved product.", frappe.ValidationError)
    if product:
        doc = frappe.get_doc("Product", product)
        doc.check_permission("write")
        if values["sku"] != doc.sku:
            frappe.throw("An existing product's SKU cannot be changed here.", frappe.ValidationError)
        if not modified or str(doc.modified) != modified:
            frappe.throw("This product changed. Reopen it before saving.", frappe.ValidationError)
        doc.update(values)
        doc.save()
    else:
        doc = frappe.get_doc({"doctype": "Product", **values})
        doc.insert()
    return {"product": {field: doc.get(field) for field in FIELDS}}


@frappe.whitelist(methods=["POST"])
def create_category(category_name, description=""):
    _require()
    doc = frappe.get_doc({
        "doctype": "Product Category",
        "category_name": _text(category_name, "category name", required=True),
        "description": _text(description, "category description", 1000), "enabled": 1,
    })
    doc.insert()
    return {"name": doc.name, "category_name": doc.category_name}
