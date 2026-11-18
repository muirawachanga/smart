from datetime import datetime, timedelta
from contextlib import contextmanager

import frappe
from frappe.utils import now_datetime


def preparation_minutes():
    settings = frappe.conf.get("order_fulfillment", {})
    if not isinstance(settings, dict):
        frappe.throw("Order fulfillment configuration must be an object.", frappe.ValidationError)
    minutes = settings.get("preparation_minutes", 20)
    if type(minutes) is not int or not 1 <= minutes <= 1440:
        frappe.throw("Preparation minutes must be an integer from 1 to 1440.", frappe.ValidationError)
    return minutes


def advance_confirmed_orders():
    names = frappe.get_all(
        "Sales Order",
        filters={"status": ["in", ["Confirmed", "Processing"]]},
        fields=["name"], order_by="modified asc", limit_page_length=100,
    )
    now = now_datetime()
    transitioned = 0
    for row in names:
        order = frappe.get_doc("Sales Order", row.name, for_update=True)
        if order.status not in {"Confirmed", "Processing"}:
            continue
        if not order.confirmed_at or not order.preparation_minutes:
            order.confirmed_at = order.confirmed_at or now
            order.preparation_minutes = order.preparation_minutes or preparation_minutes()
            if order.status == "Confirmed":
                order.status = "Processing"
            _save(order)
            transitioned += 1
            continue
        if order.status == "Confirmed":
            order.status = "Processing"
        elif _datetime(order.confirmed_at) + timedelta(minutes=order.preparation_minutes) <= now:
            is_cod = (
                order.payment_method == "Cash on Delivery"
                and frappe.db.exists(
                    "Payment Transaction",
                    {"order": order.name, "payment_method": "Cash on Delivery", "status": "Pending"},
                )
            )
            if order.payment_status != "Paid" and not is_cod:
                continue
            order.status = "Ready for Delivery"
        else:
            continue
        _save(order)
        transitioned += 1
    return transitioned


@contextmanager
def _fulfillment_workflow():
    previous = getattr(frappe.flags, "processing_order_fulfillment", False)
    frappe.flags.processing_order_fulfillment = True
    try:
        yield
    finally:
        frappe.flags.processing_order_fulfillment = previous


def _save(order):
    with _fulfillment_workflow():
        order.save(ignore_permissions=True)


def _datetime(value):
    return datetime.fromisoformat(value) if isinstance(value, str) else value
