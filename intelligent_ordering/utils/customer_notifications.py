import frappe


def on_update(doc, method=None):
    original = doc.get_doc_before_save()
    if not original and doc.doctype != "Sales Order":
        return
    changes = []
    fields = ("status", "cancellation_request_status") if doc.doctype == "Sales Order" else ("status",)
    for field in fields:
        if (original.get(field) if original else None) != doc.get(field):
            changes.append(f"{field.replace('_', ' ')}: {doc.get(field)}")
    if not changes:
        return
    order_name = doc.name if doc.doctype == "Sales Order" else doc.order
    customer = frappe.db.get_value("Sales Order", order_name, "customer")
    user = frappe.db.get_value("Customer Profile", customer, "user") if customer else None
    if not user:
        return
    frappe.get_doc({
        "doctype": "Notification Log", "for_user": user, "from_user": frappe.session.user,
        "type": "Alert", "document_type": "Sales Order", "document_name": order_name,
        "subject": f"{order_name} - {doc.doctype}: {'; '.join(changes)}",
    }).insert(ignore_permissions=True)
