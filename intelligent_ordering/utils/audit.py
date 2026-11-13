import frappe
from frappe.utils import now_datetime


def record_admin_event(event_type, reference_doctype, reference_name, details=""):
    previous = getattr(frappe.flags, "creating_admin_audit_log", False)
    frappe.flags.creating_admin_audit_log = True
    try:
        frappe.get_doc({
            "doctype": "Admin Audit Log",
            "event_type": str(event_type)[:140],
            "reference_doctype": str(reference_doctype)[:140],
            "reference_name": str(reference_name)[:140],
            "responsible_user": frappe.session.user,
            "event_datetime": now_datetime(),
            "details": str(details)[:1000],
        }).insert(ignore_permissions=True)
    finally:
        frappe.flags.creating_admin_audit_log = previous


def audit_product(doc, method=None):
    original = None if method == "after_insert" or doc.is_new() else doc.get_doc_before_save()
    changed = ["created"] if original is None else [
        field for field in ("sku", "product_name", "category", "description", "image",
                            "price", "currency", "enabled")
        if original.get(field) != doc.get(field)
    ]
    if changed:
        record_admin_event(
            "Product created" if original is None else "Product updated",
            "Product", doc.name, ", ".join(changed),
        )


def audit_category(doc, method=None):
    original = None if method == "after_insert" or doc.is_new() else doc.get_doc_before_save()
    changed = ["created"] if original is None else [
        field for field in ("category_name", "description", "enabled")
        if original.get(field) != doc.get(field)
    ]
    if changed:
        record_admin_event(
            "Category created" if original is None else "Category updated",
            "Product Category", doc.name, ", ".join(changed),
        )


def audit_order_status(doc, method=None):
    original = doc.get_doc_before_save()
    if original and original.status != doc.status:
        record_admin_event(
            "Order status changed", "Sales Order", doc.name,
            f"{original.status} -> {doc.status}",
        )


def audit_payment_status(doc, method=None):
    original = doc.get_doc_before_save()
    if original and original.status != doc.status:
        record_admin_event(
            "Payment status changed", "Payment Transaction", doc.name,
            f"{original.status} -> {doc.status}; order {doc.order}",
        )


def audit_stock_movement(doc, method=None):
    if doc.transaction_type in {"Opening", "Receipt", "Issue", "Adjustment", "Return"}:
        record_admin_event(
            "Stock movement recorded", "Stock Ledger Entry", doc.name,
            f"{doc.transaction_type}; product {doc.product}; warehouse {doc.warehouse}; "
            f"quantity change {doc.quantity_change}; reserved change {doc.reserved_change}",
        )


def audit_delivery(doc, method=None):
    original = doc.get_doc_before_save()
    if not original:
        record_admin_event("Delivery created", "Delivery", doc.name, f"Order {doc.order}")
        return
    changed = []
    for field in ("status", "assigned_delivery_person", "scheduled_delivery_date"):
        if original.get(field) != doc.get(field):
            changed.append(f"{field}: {original.get(field) or ''} -> {doc.get(field) or ''}")
    if changed:
        record_admin_event("Delivery updated", "Delivery", doc.name, "; ".join(changed))


def audit_user_roles(doc, method=None):
    original = doc.get_doc_before_save()
    before_roles = sorted(row.role for row in original.get("roles", [])) if original else []
    after = sorted(row.role for row in doc.get("roles", []))
    changes = []
    if before_roles != after:
        changes.append(
            f"roles added: {', '.join(sorted(set(after) - set(before_roles))) or 'none'}; "
            f"roles removed: {', '.join(sorted(set(before_roles) - set(after))) or 'none'}"
        )
    if original:
        changed_fields = [
            field for field in ("first_name", "last_name", "email", "enabled", "user_type")
            if original.get(field) != doc.get(field)
        ]
        if changed_fields:
            changes.append(f"user fields changed: {', '.join(changed_fields)}")
    elif method == "after_insert":
        changes.append("user created")
    if changes:
        record_admin_event(
            "User access changed", "User", doc.name, "; ".join(changes),
        )
