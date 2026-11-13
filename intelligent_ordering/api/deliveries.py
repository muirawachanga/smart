import re
from contextlib import contextmanager

import frappe
from frappe.utils import getdate, now_datetime

from intelligent_ordering.utils.delivery import (
    DELIVERY_TRANSITIONS,
    PERSONNEL_TRANSITIONS,
    validate_delivery_text,
    validate_delivery_transition,
)
from intelligent_ordering.utils.delivery_rates import get_area_quote
from intelligent_ordering.utils.fulfillment_notifications import prepare_notification
from intelligent_ordering.utils.validation import validate_pagination


MANAGER_ROLES = {"System Manager", "Business Admin", "Store Manager", "Order Manager", "Delivery Manager"}
DELIVERY_FIELDS = [
    "name", "order", "customer_name", "customer_phone", "delivery_address",
    "delivery_area", "assigned_delivery_person", "currency", "delivery_fee",
    "scheduled_delivery_date", "dispatch_date", "completion_date", "completed_by",
    "status", "delivery_notes",
]


def is_manager(user=None):
    user = user or frappe.session.user
    return user == "Administrator" or bool(MANAGER_ROLES.intersection(frappe.get_roles(user)))


def _require_manager():
    if not is_manager():
        frappe.throw("Delivery management access is required.", frappe.PermissionError)


def _require_access():
    if not is_manager() and "Delivery Staff" not in frappe.get_roles(frappe.session.user):
        frappe.throw("Delivery staff access is required.", frappe.PermissionError)


def _text(value, label, maximum=140, required=False):
    try:
        return validate_delivery_text(value, label, maximum, required)
    except ValueError as error:
        frappe.throw(str(error), frappe.ValidationError)


def _pagination(page, page_size):
    try:
        return validate_pagination(page, page_size)
    except ValueError as error:
        frappe.throw(str(error), frappe.ValidationError)


@contextmanager
def _workflow():
    previous = getattr(frappe.flags, "processing_delivery", False)
    frappe.flags.processing_delivery = True
    try:
        yield
    finally:
        frappe.flags.processing_delivery = previous


def _order_locked(name):
    return frappe.get_doc("Sales Order", _text(name, "Order", required=True), for_update=True)


def _delivery_locked(name):
    name = _text(name, "Delivery", required=True)
    order_name = frappe.db.get_value("Delivery", name, "order")
    if not order_name:
        frappe.throw("Delivery not found.", frappe.DoesNotExistError)
    # All mutations lock the order before its delivery, including payment reconciliation.
    order = _order_locked(order_name)
    delivery = frappe.get_doc("Delivery", name, for_update=True)
    _check_assigned(delivery)
    return delivery, order


def _check_assigned(delivery):
    if not is_manager() and delivery.assigned_delivery_person != frappe.session.user:
        frappe.throw("You can only access your assigned deliveries.", frappe.PermissionError)


def _serialize(delivery, detail=False):
    data = {field: delivery.get(field) for field in DELIVERY_FIELDS}
    if detail:
        transitions = DELIVERY_TRANSITIONS if is_manager() else PERSONNEL_TRANSITIONS
        data["allowed_statuses"] = sorted(transitions.get(delivery.status, set()))
        if delivery.assigned_delivery_person != frappe.session.user:
            data["allowed_statuses"] = [
                status for status in data["allowed_statuses"] if status != "Delivered"
            ]
        data["activities"] = [
            {field: row.get(field) for field in (
                "activity_datetime", "responsible_user", "from_status", "to_status",
                "previous_person", "assigned_person", "scheduled_delivery_date", "notes",
            )}
            for row in delivery.activities
        ]
    return data


def _save(delivery, order, previous_status="", previous_person="", notes=""):
    delivery.append("activities", {
        "activity_datetime": now_datetime(),
        "responsible_user": frappe.session.user,
        "from_status": previous_status,
        "to_status": delivery.status,
        "previous_person": previous_person,
        "assigned_person": delivery.assigned_delivery_person,
        "scheduled_delivery_date": delivery.scheduled_delivery_date,
        "notes": notes,
    })
    with _workflow():
        delivery.save(ignore_permissions=True)
    event = None
    if delivery.assigned_delivery_person and (
        previous_person != delivery.assigned_delivery_person
        or (previous_status != delivery.status and delivery.status == "Assigned")
    ):
        event = "Delivery Assigned"
    elif previous_status != delivery.status:
        event = {
            "Dispatched": "Order Dispatched",
            "Delivered": "Delivery Completed",
            "Failed": "Delivery Failed",
        }.get(delivery.status)
    if event:
        prepare_notification(event, order, delivery, f"{delivery.name}:{len(delivery.activities)}:{event}")


@frappe.whitelist()
def list_deliveries(status="", area="", search="", page=1, page_size=20):
    _require_access()
    page, page_size = _pagination(page, page_size)
    search = _text(search, "Search", 100)
    area = _text(area, "Delivery area")
    if not isinstance(status, str) or (status and status not in DELIVERY_TRANSITIONS):
        frappe.throw("Select a valid delivery status.", frappe.ValidationError)
    filters = {}
    if status:
        filters["status"] = status
    if area:
        filters["delivery_area"] = area
    if not is_manager():
        filters["assigned_delivery_person"] = frappe.session.user
    rows = frappe.get_list(
        "Delivery", filters=filters, fields=DELIVERY_FIELDS,
        or_filters=[["order", "like", f"%{search}%"], ["name", "like", f"%{search}%"]] if search else [],
        order_by="scheduled_delivery_date asc, creation desc",
        limit_start=(page - 1) * page_size, limit_page_length=page_size + 1,
    )
    return {"deliveries": rows[:page_size], "has_more": len(rows) > page_size, "page": page}


@frappe.whitelist()
def get_delivery(delivery_name):
    _require_access()
    delivery = frappe.get_doc("Delivery", _text(delivery_name, "Delivery", required=True))
    _check_assigned(delivery)
    delivery.check_permission("read")
    return _serialize(delivery, detail=True)


@frappe.whitelist()
def delivery_dashboard(page=1, page_size=20):
    _require_access()
    if not is_manager():
        return {"manager": False}
    page, page_size = _pagination(page, page_size)
    ready = frappe.db.sql(
        """
        SELECT o.name, o.customer_name_snapshot, o.delivery_address_snapshot,
               o.delivery_area, o.currency, o.delivery_fee
        FROM `tabSales Order` o
        WHERE o.status = 'Ready for Delivery'
          AND NOT EXISTS (SELECT 1 FROM `tabDelivery` d WHERE d.`order` = o.name)
        ORDER BY o.order_datetime
        LIMIT %s OFFSET %s
        """, (page_size + 1, (page - 1) * page_size), as_dict=True,
    )
    personnel = frappe.db.sql(
        """
        SELECT u.name, u.full_name,
            (SELECT COUNT(*) FROM `tabDelivery` d
             WHERE d.assigned_delivery_person = u.name
               AND d.status NOT IN ('Delivered', 'Cancelled')) AS workload
        FROM `tabUser` u
        WHERE u.enabled = 1 AND u.name NOT IN ('Guest', 'Administrator')
          AND EXISTS (SELECT 1 FROM `tabHas Role` r
                      WHERE r.parent = u.name AND r.parenttype = 'User'
                        AND r.role = 'Delivery Staff')
        ORDER BY u.full_name, u.name
        """, as_dict=True,
    )
    areas = frappe.get_list(
        "Delivery Area", fields=["name", "currency", "delivery_fee", "enabled"],
        order_by="area_name", limit_page_length=0,
    )
    return {
        "manager": True, "ready_orders": ready[:page_size],
        "has_more": len(ready) > page_size, "personnel": personnel, "areas": areas,
    }


@frappe.whitelist(methods=["POST"])
def create_delivery(order_name, delivery_area=""):
    _require_manager()
    order = _order_locked(order_name)
    order.check_permission("read")
    existing = frappe.db.get_value("Delivery", {"order": order.name}, "name", for_update=True)
    if existing:
        return get_delivery(existing)
    if order.status != "Ready for Delivery":
        frappe.throw("Only orders Ready for Delivery can enter fulfillment.", frappe.ValidationError)
    area = order.get("delivery_area")
    if not area:
        # Legacy orders retain their paid amount; the selected area is routing only.
        area = get_area_quote(delivery_area, order.currency)["delivery_area"]
    delivery = frappe.get_doc({
        "doctype": "Delivery", "order": order.name, "customer": order.customer,
        "customer_name": order.customer_name_snapshot,
        "customer_phone": order.customer_phone_snapshot,
        "delivery_address": order.delivery_address_snapshot,
        "delivery_area": area, "currency": order.currency,
        "delivery_fee": order.get("delivery_fee") or 0,
        "status": "Awaiting Assignment",
    })
    _save(delivery, order, notes="Delivery created from immutable order snapshots.")
    return _serialize(delivery, detail=True)


def _validate_person(person):
    person = _text(person, "Delivery person", required=True)
    if (
        not frappe.db.get_value("User", person, "enabled")
        or "Delivery Staff" not in frappe.get_roles(person)
        or person in {"Guest", "Administrator"}
    ):
        frappe.throw("Select an enabled user with the Delivery Staff role.", frappe.ValidationError)
    return person


def _schedule(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
        frappe.throw("A scheduled delivery date (YYYY-MM-DD) is required.", frappe.ValidationError)
    try:
        date = getdate(value)
    except (ValueError, TypeError):
        frappe.throw("Select a valid scheduled delivery date.", frappe.ValidationError)
    if date < now_datetime().date():
        frappe.throw("The scheduled delivery date cannot be in the past.", frappe.ValidationError)
    return date


@frappe.whitelist(methods=["POST"])
def assign_delivery(delivery_name, assigned_person, scheduled_delivery_date, notes=""):
    _require_manager()
    person = _validate_person(assigned_person)
    scheduled = _schedule(scheduled_delivery_date)
    notes = _text(notes, "Assignment notes", 1000)
    delivery, order = _delivery_locked(delivery_name)
    if order.status != "Ready for Delivery" or delivery.status in {
        "Dispatched", "In Transit", "Delivered", "Cancelled",
    }:
        frappe.throw("This delivery cannot be assigned or reassigned.", frappe.ValidationError)
    previous_status, previous_person = delivery.status, delivery.assigned_delivery_person
    if (
        previous_person == person and delivery.scheduled_delivery_date
        and getdate(delivery.scheduled_delivery_date) == scheduled and not notes
        and delivery.status not in {"Awaiting Assignment", "Failed"}
    ):
        return _serialize(delivery, detail=True)
    if previous_person and previous_person != person and not notes:
        frappe.throw("Provide a reason for delivery reassignment.", frappe.ValidationError)
    if delivery.status in {"Awaiting Assignment", "Failed"}:
        delivery.status = "Assigned"
    delivery.assigned_delivery_person = person
    delivery.scheduled_delivery_date = scheduled
    _save(delivery, order, previous_status, previous_person, notes)
    return _serialize(delivery, detail=True)


@frappe.whitelist(methods=["POST"])
def update_delivery(delivery_name, status, notes="", confirmation=0):
    _require_access()
    notes = _text(notes, "Delivery notes", 1000)
    delivery, order = _delivery_locked(delivery_name)
    try:
        validate_delivery_transition(delivery.status, status, personnel=not is_manager())
    except ValueError as error:
        frappe.throw(str(error), frappe.ValidationError)
    if delivery.status == status and not notes:
        return _serialize(delivery, detail=True)
    if delivery.status in {"Delivered", "Cancelled"}:
        frappe.throw("Terminal delivery history cannot be changed.", frappe.ValidationError)
    if status != "Cancelled" and order.status != "Ready for Delivery":
        frappe.throw("The associated order is not Ready for Delivery.", frappe.ValidationError)
    if status != "Cancelled" and not delivery.assigned_delivery_person:
        frappe.throw("Assign a delivery person first.", frappe.ValidationError)
    if status in {"Failed", "Cancelled"} and not notes:
        frappe.throw("A reason is required for failed or cancelled deliveries.", frappe.ValidationError)
    if status in {"Dispatched", "In Transit", "Delivered"} and order.payment_status != "Paid":
        frappe.throw("Verified payment is required before dispatch or delivery.", frappe.ValidationError)
    if status == "Delivered":
        if str(confirmation) != "1":
            frappe.throw("Explicit delivery confirmation is required.", frappe.ValidationError)
        if frappe.session.user != delivery.assigned_delivery_person:
            frappe.throw("Only the assigned delivery person can confirm receipt.", frappe.PermissionError)
    previous_status, previous_person = delivery.status, delivery.assigned_delivery_person
    delivery.status = status
    if notes:
        delivery.delivery_notes = notes
    if status == "Dispatched" and previous_status != status:
        delivery.dispatch_date = now_datetime()
    if status == "Delivered":
        delivery.completion_date = now_datetime()
        delivery.completed_by = frappe.session.user
    _save(delivery, order, previous_status, previous_person, notes)
    if status == "Delivered":
        with _workflow():
            order.status = "Completed"
            order.save(ignore_permissions=True)
    return _serialize(delivery, detail=True)


@frappe.whitelist(methods=["POST"])
def save_delivery_area(area_name, delivery_fee, currency="KES", enabled=1):
    _require_manager()
    area_name = _text(area_name, "Area name", required=True)
    if str(enabled) not in {"0", "1"}:
        frappe.throw("Enabled must be 0 or 1.", frappe.ValidationError)
    if frappe.db.exists("Delivery Area", area_name):
        area = frappe.get_doc("Delivery Area", area_name, for_update=True)
        area.check_permission("write")
    else:
        area = frappe.new_doc("Delivery Area")
        area.area_name = area_name
    area.delivery_fee, area.currency, area.enabled = delivery_fee, currency, int(enabled)
    area.save()
    return {"name": area.name, "delivery_fee": area.delivery_fee, "currency": area.currency, "enabled": area.enabled}
