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
    now = now_datetime()
    transitioned = 0
    last_name = ""
    while transitioned < 100:
        rows = frappe.get_all(
            "Sales Order",
            filters={"status": ["in", ["Pending", "Confirmed", "Processing", "Ready for Delivery"]], "name": [">", last_name]},
            or_filters=[
                ["Sales Order", "status", "in", ["Confirmed", "Processing", "Ready for Delivery"]],
                ["Sales Order", "payment_status", "=", "Paid"],
            ],
            fields=["name"], order_by="name asc", limit_page_length=100,
        )
        if not rows:
            break
        for row in rows:
            last_name = row.name
            order = frappe.get_doc("Sales Order", row.name, for_update=True)
            if order.status in {"Confirmed", "Processing", "Ready for Delivery"}:
                frappe.db.savepoint("fulfillment_broadcast")
                try:
                    _ensure_broadcast(order)
                except (frappe.ValidationError, frappe.PermissionError):
                    frappe.db.rollback(save_point="fulfillment_broadcast")
                    frappe.log_error(
                        title="Delivery broadcast blocked",
                        message=f"Order {row.name}\n{frappe.get_traceback()}",
                    )
                    continue
            if order.status == "Pending":
                if (
                    order.payment_method != "M-Pesa" or order.payment_status != "Paid"
                    or not frappe.db.exists("Payment Transaction", {
                        "order": order.name, "payment_method": "M-Pesa", "status": "Successful",
                    })
                ):
                    continue
                order.status = "Confirmed"
            elif order.status not in {"Confirmed", "Processing"}:
                continue
            elif not order.confirmed_at or not order.preparation_minutes:
                order.confirmed_at = order.confirmed_at or now
                order.preparation_minutes = order.preparation_minutes or preparation_minutes()
                if order.status == "Confirmed":
                    order.status = "Processing"
            elif order.status == "Confirmed":
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
            frappe.db.savepoint("fulfillment_order")
            try:
                _save(order)
            except (frappe.ValidationError, frappe.PermissionError):
                frappe.db.rollback(save_point="fulfillment_order")
                frappe.log_error(
                    title="Order fulfillment blocked",
                    message=f"Order {row.name}\n{frappe.get_traceback()}",
                )
                continue
            transitioned += 1
            if transitioned >= 100:
                break
        if len(rows) < 100:
            break
    return transitioned


def _ensure_broadcast(order):
    from intelligent_ordering.api.deliveries import ensure_order_broadcast

    ensure_order_broadcast(order)


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


def complete_order_after_customer_receipt(order, delivery):
    if (
        order.status != "Ready for Delivery"
        or order.payment_status != "Paid" or delivery.order != order.name
        or delivery.status != "Delivered" or not delivery.customer_receipt_confirmed
    ):
        return False
    previous = getattr(frappe.flags, "processing_delivery", False)
    frappe.flags.processing_delivery = True
    try:
        order.status = "Completed"
        order.save(ignore_permissions=True)
    finally:
        frappe.flags.processing_delivery = previous
    return True


def _datetime(value):
    return datetime.fromisoformat(value) if isinstance(value, str) else value
