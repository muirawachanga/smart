import json

import frappe


def prepare_notification(event_type, order, delivery=None, event_key=None):
    key = event_key or f"{order.name}:{event_type}"
    if frappe.db.exists("Fulfillment Notification", {"event_key": key}):
        return
    provider = (frappe.conf.get("fulfillment_notifications") or {}).get("provider", "unconfigured")
    previous = getattr(frappe.flags, "preparing_fulfillment_notification", False)
    frappe.flags.preparing_fulfillment_notification = True
    try:
        frappe.get_doc({
            "doctype": "Fulfillment Notification",
            "event_key": key,
            "event_type": event_type,
            "order": order.name,
            "delivery": delivery.name if delivery else None,
            "recipient_phone": order.customer_phone_snapshot,
            "recipient_user": delivery.assigned_delivery_person if delivery else None,
            "provider": provider,
            "status": "Prepared",
            "payload": json.dumps({
                "event": event_type, "order": order.name,
                "delivery": delivery.name if delivery else None,
                "order_status": order.status,
                "delivery_status": delivery.status if delivery else None,
            }),
        }).insert(ignore_permissions=True)
    finally:
        frappe.flags.preparing_fulfillment_notification = previous


def handle_order_status_change(doc, method=None):
    original = doc.get_doc_before_save()
    if original and original.status != doc.status and doc.status == "Confirmed":
        prepare_notification("Order Confirmed", doc)
