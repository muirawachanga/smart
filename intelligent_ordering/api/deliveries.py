import base64
import binascii
import hashlib
import json
import math
import re
from contextlib import contextmanager
from datetime import datetime, timedelta

import frappe
from frappe.utils import getdate, now_datetime

from intelligent_ordering.utils.delivery import (
    DELIVERY_TRANSITIONS,
    PERSONNEL_TRANSITIONS,
    distance_km,
    nearest_delivery_route,
    validate_coordinates,
    validate_delivery_text,
    validate_delivery_transition,
)
from intelligent_ordering.utils.delivery_rates import get_area_quote
from intelligent_ordering.utils.fulfillment_notifications import prepare_notification
from intelligent_ordering.utils.validation import validate_pagination
from intelligent_ordering.utils.audit import record_admin_event


MANAGER_ROLES = {"System Manager", "Business Admin", "Store Manager", "Order Manager", "Delivery Manager"}
DELIVERY_FIELDS = [
    "name", "order", "customer_name", "customer_phone", "delivery_address",
    "delivery_area", "assigned_delivery_person", "currency", "delivery_fee",
    "scheduled_delivery_date", "dispatch_date", "completion_date", "completed_by",
    "cash_collected", "cash_collected_amount", "cash_collected_at", "cash_collected_by",
    "status", "delivery_notes", "location_set", "latitude", "longitude",
]
MANAGE_DELIVERY_AREA_ROLES = {"System Manager", "Business Admin", "Store Manager", "Order Manager"}
MAX_PROOF_BYTES = 5 * 1024 * 1024


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


def _delivery_locked(name, *, offer=False):
    name = _text(name, "Delivery", required=True)
    order_name = frappe.db.get_value("Delivery", name, "order")
    if not order_name:
        frappe.throw("Delivery not found.", frappe.DoesNotExistError)
    # All mutations lock the order before its delivery, including payment reconciliation.
    order = _order_locked(order_name)
    delivery = frappe.get_doc("Delivery", name, for_update=True)
    if not offer:
        _check_assigned(delivery)
    return delivery, order


def _check_assigned(delivery):
    if not is_manager() and delivery.assigned_delivery_person != frappe.session.user:
        frappe.throw("You can only access your assigned deliveries.", frappe.PermissionError)


def _serialize(delivery, detail=False, *, personnel=False):
    data = {field: delivery.get(field) for field in DELIVERY_FIELDS}
    if detail:
        order = frappe.db.get_value(
            "Sales Order", delivery.order, ["payment_status", "payment_method"], as_dict=True
        )
        data["payment_status"] = order.payment_status if order else None
        data["payment_method"] = order.payment_method if order else None
        data["items"] = frappe.get_all(
            "Sales Order Item",
            filters={"parent": delivery.order, "parenttype": "Sales Order"},
            fields=["product_name_snapshot", "product_sku_snapshot", "quantity"],
            order_by="idx asc",
            limit_page_length=100,
        )
        data["assignment_date"] = next(
            (
                row.activity_datetime for row in reversed(delivery.activities)
                if row.assigned_person == delivery.assigned_delivery_person
                and (row.to_status == "Assigned"
                     or (row.from_status == "Awaiting Assignment" and row.to_status == "Accepted"))
            ),
            None,
        )
        data["proof_files"] = frappe.get_all(
            "File",
            filters={
                "attached_to_doctype": "Delivery",
                "attached_to_name": delivery.name,
                "is_private": 1,
            },
            fields=["file_name", "file_url", "creation"],
            order_by="creation desc",
            limit_page_length=20,
        )
        transitions = PERSONNEL_TRANSITIONS if personnel or not is_manager() else DELIVERY_TRANSITIONS
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
            if ((not personnel and is_manager()) or row.get("activity_type") != "Offer Rejected"
                or row.get("responsible_user") == frappe.session.user)
        ]
    return data


def _save(delivery, order, previous_status="", previous_person="", notes="", activity_type=""):
    delivery.append("activities", {
        "activity_datetime": now_datetime(),
        "responsible_user": frappe.session.user,
        "activity_type": activity_type,
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
            "Picked Up": "Order Dispatched",
            "Dispatched": "Order Dispatched",
            "Delivered": "Delivery Completed",
            "Failed": "Delivery Failed",
        }.get(delivery.status)
    if event:
        event_key = (
            f"{delivery.name}:{event}" if event == "Order Dispatched"
            else f"{delivery.name}:{len(delivery.activities)}:{event}"
        )
        prepare_notification(event, order, delivery, event_key)
    if delivery.broadcast_started_at and (
        delivery.status == "Awaiting Assignment" or previous_status == "Awaiting Assignment"
    ):
        _notify_offer_change()


def _notify_offer_change():
    riders = frappe.db.sql(
        """SELECT l.rider FROM `tabDelivery Rider Location` l
           INNER JOIN `tabUser` u ON u.name = l.rider
           WHERE l.offers_online = 1 AND l.offers_seen_at >= %s AND u.enabled = 1
             AND EXISTS (SELECT 1 FROM `tabHas Role` r
                         WHERE r.parent = u.name AND r.parenttype = 'User'
                           AND r.role = 'Delivery Staff')""",
        now_datetime() - timedelta(seconds=90), as_dict=True,
    )
    for row in riders:
        frappe.publish_realtime("delivery_offers_changed", {}, user=row.rider, after_commit=True)


@frappe.whitelist()
def list_deliveries(status="", area="", search="", page=1, page_size=20, delayed="0"):
    _require_access()
    return _list_deliveries(status, area, search, page, page_size, delayed)


@frappe.whitelist()
def my_deliveries(status="", area="", search="", page=1, page_size=20, delayed="0"):
    _require_rider()
    return _list_deliveries(status, area, search, page, page_size, delayed, assigned_only=True)


def _list_deliveries(status, area, search, page, page_size, delayed, *, assigned_only=False):
    page, page_size = _pagination(page, page_size)
    search = _text(search, "Search", 100)
    area = _text(area, "Delivery area")
    if not isinstance(status, str) or (status and status not in DELIVERY_TRANSITIONS):
        frappe.throw("Select a valid delivery status.", frappe.ValidationError)
    if str(delayed) not in {"0", "1"}:
        frappe.throw("Select a valid delayed-delivery filter.", frappe.ValidationError)
    filters = {}
    if status:
        filters["status"] = status
    if area:
        filters["delivery_area"] = area
    if assigned_only or not is_manager():
        filters["assigned_delivery_person"] = frappe.session.user
    if str(delayed) == "1":
        filters["scheduled_delivery_date"] = ["<", now_datetime().date()]
        if status in {"Delivered", "Failed", "Cancelled"}:
            frappe.throw("Delayed deliveries must still be active.", frappe.ValidationError)
        if not status:
            filters["status"] = ["not in", ["Delivered", "Failed", "Cancelled"]]
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
    result = _serialize(delivery, detail=True)
    if is_manager():
        result["assignment_personnel"] = _delivery_personnel()
    return result


@frappe.whitelist()
def get_my_delivery(delivery_name):
    rider = _require_rider()
    delivery = frappe.get_doc("Delivery", _text(delivery_name, "Delivery", required=True))
    if delivery.assigned_delivery_person != rider:
        frappe.throw("You can only access your assigned deliveries.", frappe.PermissionError)
    delivery.check_permission("read")
    return _serialize(delivery, detail=True, personnel=True)


@frappe.whitelist()
def my_delivery_dashboard():
    return _rider_dashboard(_require_rider())


def _rider_dashboard(assigned):
    summary = frappe.db.sql(
        """
        SELECT COUNT(*) AS total,
          SUM(status = 'Assigned') AS pending,
          SUM(status = 'Accepted') AS accepted,
          SUM(status = 'Picked Up') AS picked_up,
          SUM(status IN ('Preparing','Ready for Dispatch','Dispatched','In Transit')) AS in_progress,
          SUM(status = 'Delivered') AS delivered,
          SUM(status = 'Failed') AS failed
        FROM `tabDelivery` WHERE assigned_delivery_person = %s
        """, assigned, as_dict=True,
    )[0]
    return {
        "manager": False,
        "rider": True,
        "summary": _delivery_summary(summary),
        "delayed_deliveries": _delayed_count(assigned),
        "personnel": [],
    }


@frappe.whitelist()
def delivery_dashboard(page=1, page_size=20):
    _require_access()
    if not is_manager():
        return _rider_dashboard(frappe.session.user)
    page, page_size = _pagination(page, page_size)
    personnel = _delivery_personnel()
    summary = frappe.db.sql(
        """
        SELECT COUNT(*) AS total,
          SUM(status IN ('Awaiting Assignment','Failed')
              AND COALESCE(assigned_delivery_person, '') = '') AS unassigned,
          SUM(status IN ('Assigned','Accepted')) AS assigned,
          SUM(status IN ('Preparing','Ready for Dispatch','Picked Up','Dispatched','In Transit')) AS in_progress,
          SUM(status = 'Delivered') AS completed,
          SUM(status = 'Failed') AS failed
        FROM `tabDelivery`
        """, as_dict=True,
    )[0]
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
    performance = frappe.db.sql(
        """
        SELECT d.assigned_delivery_person AS rider,
          SUM(d.status = 'Delivered') AS completed,
          SUM(d.status = 'Failed') AS failed,
          COUNT(*) AS total
        FROM `tabDelivery` d
        WHERE d.assigned_delivery_person IS NOT NULL
        GROUP BY d.assigned_delivery_person
        ORDER BY total DESC, rider
        LIMIT 100
        """, as_dict=True,
    )
    areas = frappe.get_list(
        "Delivery Area", fields=["name", "currency", "delivery_fee", "enabled", "modified"],
        order_by="area_name", limit_page_length=0,
    )
    return {
        "manager": True, "rider": "Delivery Staff" in frappe.get_roles(frappe.session.user),
        "summary": _delivery_summary(summary),
        "completion_rate": (
            round(100 * int(summary.completed or 0) / int(summary.total), 1)
            if summary.total else 0
        ),
        "delayed_deliveries": _delayed_count(),
        "available_riders": sum(1 for person in personnel if not int(person.workload or 0)),
        "personnel_performance": performance,
        "can_manage_areas": frappe.has_permission("Delivery Area", "write"),
        "can_delete_areas": frappe.has_permission("Delivery Area", "delete"),
        "escalated_broadcasts": frappe.get_all(
            "Delivery", filters={"status": "Awaiting Assignment", "broadcast_escalated_at": ["is", "set"]},
            fields=["name", "order", "broadcast_escalated_at"], order_by="broadcast_escalated_at desc",
            limit_page_length=100,
        ),
        "ready_orders": ready[:page_size],
        "has_more": len(ready) > page_size, "personnel": personnel, "areas": areas,
    }


def _delivery_personnel():
    return frappe.db.sql(
        """
        SELECT u.name, u.full_name,
            (SELECT COUNT(*) FROM `tabDelivery` d
             WHERE d.assigned_delivery_person = u.name
               AND d.status NOT IN ('Delivered', 'Failed', 'Cancelled')) AS workload
        FROM `tabUser` u
        WHERE u.enabled = 1 AND u.name NOT IN ('Guest', 'Administrator')
          AND EXISTS (SELECT 1 FROM `tabHas Role` r
                      WHERE r.parent = u.name AND r.parenttype = 'User'
                        AND r.role = 'Delivery Staff')
        ORDER BY u.full_name, u.name
        """, as_dict=True,
    )


def _delivery_summary(row):
    return {key: int(row.get(key) or 0) for key in row}


def _delayed_count(assigned_person=None):
    filters = ""
    values = []
    if assigned_person:
        filters = "AND assigned_delivery_person = %s"
        values.append(assigned_person)
    row = frappe.db.sql(
        f"""
        SELECT COUNT(*) AS delayed_count
        FROM `tabDelivery`
        WHERE scheduled_delivery_date < CURDATE()
          AND status NOT IN ('Delivered','Failed','Cancelled')
          {filters}
        """, values, as_dict=True,
    )[0]
    return int(row.delayed_count or 0)


@frappe.whitelist(methods=["POST"])
def create_delivery(order_name, delivery_area=""):
    _require_manager()
    order = _order_locked(order_name)
    existing = frappe.db.get_value("Delivery", {"order": order.name}, "name", for_update=True)
    if existing:
        return get_delivery(existing)
    if order.status != "Ready for Delivery":
        frappe.throw("Only orders Ready for Delivery can enter fulfillment.", frappe.ValidationError)
    delivery = _create_delivery(order, delivery_area)
    return _serialize(delivery, detail=True)


def _create_delivery(order, delivery_area="", *, automatic=False):
    area = order.get("delivery_area")
    if not area and not automatic:
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
    _start_broadcast(delivery)
    _save(delivery, order, notes="Delivery created from immutable order snapshots.")
    return delivery


def _broadcast_settings():
    config = frappe.conf.get("delivery_broadcast", {})
    if not isinstance(config, dict):
        frappe.throw("Delivery broadcast configuration must be an object.", frappe.ValidationError)
    rounds = config.get("attempts", 3)
    minutes = config.get("round_minutes", 5)
    if (type(rounds) is not int or not 1 <= rounds <= 20
            or type(minutes) is not int or not 1 <= minutes <= 1440):
        frappe.throw("Delivery broadcast attempts and round minutes are invalid.", frappe.ValidationError)
    return rounds, minutes


def _start_broadcast(delivery):
    rounds, minutes = _broadcast_settings()
    delivery.broadcast_started_at = now_datetime()
    delivery.broadcast_attempts = rounds
    delivery.broadcast_round_minutes = minutes
    delivery.broadcast_expires_at = delivery.broadcast_started_at + timedelta(minutes=rounds * minutes)
    delivery.broadcast_escalated_at = None


def broadcast_ready_order(order, method=None):
    original = order.get_doc_before_save()
    if not original or original.status == order.status or order.status != "Ready for Delivery":
        return
    if not frappe.db.get_value("Delivery", {"order": order.name}, "name", for_update=True):
        _create_delivery(order, automatic=True)


def escalate_expired_broadcasts():
    names = frappe.get_all(
        "Delivery",
        filters={
            "status": "Awaiting Assignment", "broadcast_expires_at": ["<=", now_datetime()],
            "broadcast_escalated_at": ["is", "not set"],
        },
        pluck="name", order_by="broadcast_expires_at asc", limit_page_length=100,
    )
    for name in names:
        delivery, order = _delivery_locked(name, offer=True)
        if (delivery.status != "Awaiting Assignment" or delivery.assigned_delivery_person
                or not delivery.broadcast_expires_at or delivery.broadcast_escalated_at
                or delivery.broadcast_expires_at > now_datetime()):
            continue
        managers = frappe.db.sql(
            """SELECT DISTINCT u.name FROM `tabUser` u
               INNER JOIN `tabHas Role` r ON r.parent = u.name AND r.parenttype = 'User'
               WHERE u.enabled = 1 AND r.role = 'Delivery Manager'""",
            as_dict=True,
        )
        for manager in managers:
            frappe.get_doc({
                "doctype": "Notification Log", "for_user": manager.name,
                "from_user": frappe.session.user, "type": "Alert",
                "document_type": "Delivery", "document_name": delivery.name,
                "subject": f"{delivery.name} needs manual rider assignment.",
            }).insert(ignore_permissions=True)
        if not managers:
            frappe.log_error(title="Delivery broadcast escalation",
                             message=f"No enabled Delivery Manager for {delivery.name}.")
        delivery.broadcast_escalated_at = now_datetime()
        _save(delivery, order, delivery.status, delivery.assigned_delivery_person,
              "Broadcast expired; manual assignment required.")


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
    person = _text(assigned_person, "Delivery person", required=True)
    frappe.db.sql("SELECT name FROM `tabUser` WHERE name = %s FOR UPDATE", person)
    person = _validate_person(person)
    scheduled = _schedule(scheduled_delivery_date)
    notes = _text(notes, "Assignment notes", 1000)
    delivery, order = _delivery_locked(delivery_name)
    if order.status != "Ready for Delivery" or delivery.status in {
        "Picked Up", "Dispatched", "In Transit", "Delivered", "Cancelled",
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
    if delivery.status in {"Awaiting Assignment", "Failed"} or previous_person != person:
        delivery.status = "Assigned"
    delivery.assigned_delivery_person = person
    delivery.scheduled_delivery_date = scheduled
    _save(delivery, order, previous_status, previous_person, notes)
    return _serialize(delivery, detail=True)


def _coordinates(latitude, longitude):
    try:
        return validate_coordinates(latitude, longitude)
    except ValueError as error:
        frappe.throw(str(error), frappe.ValidationError)


def _require_rider():
    user = frappe.session.user
    if user in {"Guest", "Administrator"} or "Delivery Staff" not in frappe.get_roles(user):
        frappe.throw("Only delivery personnel can access rider functions.", frappe.PermissionError)
    if not frappe.db.get_value("User", user, "enabled"):
        frappe.throw("This delivery account is disabled.", frappe.PermissionError)
    return user


def _lock_rider(rider):
    users = frappe.db.sql(
        "SELECT enabled FROM `tabUser` WHERE name = %s FOR UPDATE", rider,
    )
    roles = frappe.db.sql(
        """SELECT name FROM `tabHas Role` WHERE parent = %s AND parenttype = 'User'
           AND role = 'Delivery Staff' FOR UPDATE""", rider,
    )
    if not users or not users[0][0] or not roles:
        frappe.throw("Select an enabled user with the Delivery Staff role.", frappe.PermissionError)


def _rider_busy(rider):
    return bool(frappe.db.sql(
        """SELECT name FROM `tabDelivery` WHERE assigned_delivery_person = %s
           AND status NOT IN ('Delivered', 'Failed', 'Cancelled') LIMIT 1 FOR UPDATE""", rider,
    ))


def _presence(rider, *, for_update=False):
    return frappe.db.get_value(
        "Delivery Rider Location", rider, ["offers_online", "offers_seen_at"],
        as_dict=True, for_update=for_update,
    )


def _is_online(presence):
    if not presence or not presence.offers_online or not presence.offers_seen_at:
        return False
    seen = presence.offers_seen_at
    if isinstance(seen, str):
        seen = datetime.fromisoformat(seen)
    return now_datetime() - timedelta(seconds=90) <= seen <= now_datetime()


@frappe.whitelist(methods=["POST"])
def set_offer_presence(online):
    rider = _require_rider()
    if str(online) not in {"0", "1", "heartbeat"}:
        frappe.throw("Choose a valid availability state.", frappe.ValidationError)
    _lock_rider(rider)
    if frappe.db.exists("Delivery Rider Location", rider):
        location = frappe.get_doc("Delivery Rider Location", rider, for_update=True)
    else:
        location = frappe.get_doc({"doctype": "Delivery Rider Location", "rider": rider})
    if online == "heartbeat" and not _is_online(location):
        frappe.throw("Go online again to receive delivery offers.", frappe.ValidationError)
    location.offers_online = 0 if str(online) == "0" else 1
    location.offers_seen_at = now_datetime() if location.offers_online else None
    previous = getattr(frappe.flags, "sharing_delivery_location", False)
    frappe.flags.sharing_delivery_location = True
    try:
        location.save(ignore_permissions=True)
    finally:
        frappe.flags.sharing_delivery_location = previous
    return {"online": bool(location.offers_online)}


@frappe.whitelist()
def delivery_offers():
    rider = _require_rider()
    online = _is_online(_presence(rider))
    busy = bool(frappe.db.exists(
        "Delivery", {"assigned_delivery_person": rider, "status": ["not in", ["Delivered", "Failed", "Cancelled"]]},
    ))
    offers = []
    if online and not busy:
        now = now_datetime()
        offers = frappe.db.sql(
            """SELECT d.name, d.`order`, d.delivery_area, d.broadcast_started_at,
                      d.broadcast_round_minutes, d.broadcast_attempts
               FROM `tabDelivery` d
               INNER JOIN `tabSales Order` o ON o.name = d.`order`
               WHERE d.status = 'Awaiting Assignment'
                 AND COALESCE(d.assigned_delivery_person, '') = ''
                 AND d.broadcast_started_at IS NOT NULL AND d.broadcast_expires_at > %s
                 AND o.status = 'Ready for Delivery'
                 AND NOT EXISTS (
                    SELECT 1 FROM `tabDelivery Activity` a
                    WHERE a.parent = d.name AND a.parenttype = 'Delivery'
                      AND a.activity_type = 'Offer Rejected' AND a.responsible_user = %s
                 )
               ORDER BY d.broadcast_started_at, d.name LIMIT 100""",
            (now, rider), as_dict=True,
        )
        for offer in offers:
            round_number, expires_at = _offer_round(offer, now)
            offer["round_number"] = round_number
            offer["expires_at"] = expires_at
            for field in ("broadcast_started_at", "broadcast_round_minutes", "broadcast_attempts"):
                offer.pop(field, None)
    return {"online": online, "busy": busy, "offers": offers}


def _offer_round(delivery, now):
    started = delivery.broadcast_started_at
    if isinstance(started, str):
        started = datetime.fromisoformat(started)
    minutes = int(delivery.broadcast_round_minutes or 0)
    attempts = int(delivery.broadcast_attempts or 0)
    if not started or minutes <= 0 or attempts <= 0 or now < started:
        frappe.throw("This delivery broadcast is invalid.", frappe.ValidationError)
    number = int((now - started).total_seconds() // (minutes * 60)) + 1
    if number > attempts:
        frappe.throw("This delivery offer is no longer available.", frappe.ValidationError)
    return number, started + timedelta(minutes=number * minutes)


def _locked_offer(name, rider, round_number):
    _lock_rider(rider)
    if not _is_online(_presence(rider, for_update=True)) or _rider_busy(rider):
        frappe.throw("You must be online and have no active deliveries.", frappe.ValidationError)
    delivery, order = _delivery_locked(name, offer=True)
    if (order.status != "Ready for Delivery" or delivery.status != "Awaiting Assignment"
            or delivery.assigned_delivery_person or not delivery.broadcast_started_at
            or not delivery.broadcast_expires_at or delivery.broadcast_expires_at <= now_datetime()):
        frappe.throw("This delivery offer is no longer available.", frappe.ValidationError)
    current_round, _ = _offer_round(delivery, now_datetime())
    if str(round_number) != str(current_round):
        frappe.throw("This delivery offer has expired. Refresh the offers.", frappe.ValidationError)
    if any(row.activity_type == "Offer Rejected" and row.responsible_user == rider
           for row in delivery.activities):
        frappe.throw("You have already rejected this delivery offer.", frappe.ValidationError)
    return delivery, order


@frappe.whitelist(methods=["POST"])
def accept_delivery_offer(delivery_name, round_number):
    rider = _require_rider()
    delivery, order = _locked_offer(delivery_name, rider, round_number)
    delivery.assigned_delivery_person = rider
    delivery.scheduled_delivery_date = now_datetime().date()
    delivery.status = "Assigned"
    _save(delivery, order, "Awaiting Assignment", "", "Delivery offer accepted.")
    delivery.status = "Accepted"
    _save(delivery, order, "Assigned", rider, "Delivery offer accepted.")
    return _serialize(delivery, detail=True)


@frappe.whitelist(methods=["POST"])
def reject_delivery_offer(delivery_name, round_number):
    rider = _require_rider()
    delivery, order = _locked_offer(delivery_name, rider, round_number)
    _save(delivery, order, delivery.status, "", "Delivery offer rejected.", "Offer Rejected")
    return {"rejected": True}


def _rider_location(rider, *, for_update=False):
    location = frappe.db.get_value(
        "Delivery Rider Location", rider,
        ["location_set", "latitude", "longitude", "accuracy_meters", "location_updated_at"],
        as_dict=True, for_update=for_update,
    )
    if not location or not location.location_set or not location.location_updated_at:
        return None
    updated = location.location_updated_at
    if isinstance(updated, str):
        updated = datetime.fromisoformat(updated)
    now = now_datetime()
    if updated > now or updated < now - timedelta(minutes=30):
        return None
    return location


@frappe.whitelist(methods=["POST"])
def share_rider_location(latitude, longitude, accuracy_meters):
    rider = _require_rider()
    latitude, longitude = _coordinates(latitude, longitude)
    try:
        accuracy = float(accuracy_meters)
        if not math.isfinite(accuracy) or accuracy < 0 or accuracy > 10000000:
            raise ValueError
    except (ValueError, TypeError, OverflowError):
        frappe.throw("A valid GPS accuracy in meters is required.", frappe.ValidationError)
    frappe.db.sql("SELECT name FROM `tabUser` WHERE name = %s FOR UPDATE", rider)
    if frappe.db.exists("Delivery Rider Location", rider):
        location = frappe.get_doc("Delivery Rider Location", rider, for_update=True)
    else:
        location = frappe.get_doc({"doctype": "Delivery Rider Location", "rider": rider})
    location.location_set = 1
    location.latitude, location.longitude = latitude, longitude
    location.accuracy_meters = accuracy
    location.location_updated_at = now_datetime()
    previous = getattr(frappe.flags, "sharing_delivery_location", False)
    frappe.flags.sharing_delivery_location = True
    try:
        location.save(ignore_permissions=True)
    finally:
        frappe.flags.sharing_delivery_location = previous
    return {"shared_at": location.location_updated_at, "accuracy_meters": accuracy}


@frappe.whitelist(methods=["POST"])
def clear_rider_location():
    rider = _require_rider()
    frappe.db.sql("SELECT name FROM `tabUser` WHERE name = %s FOR UPDATE", rider)
    if frappe.db.exists("Delivery Rider Location", rider):
        location = frappe.get_doc("Delivery Rider Location", rider, for_update=True)
        location.location_set = 0
        location.latitude = location.longitude = location.accuracy_meters = 0
        location.location_updated_at = None
        previous = getattr(frappe.flags, "sharing_delivery_location", False)
        frappe.flags.sharing_delivery_location = True
        try:
            location.save(ignore_permissions=True)
        finally:
            frappe.flags.sharing_delivery_location = previous
    return {"shared": False}


@frappe.whitelist(methods=["POST"])
def set_delivery_coordinates(delivery_name, latitude, longitude):
    _require_manager()
    latitude, longitude = _coordinates(latitude, longitude)
    delivery, order = _delivery_locked(delivery_name)
    if delivery.status in {"Delivered", "Cancelled"}:
        frappe.throw("Coordinates cannot be changed for a completed or cancelled delivery.", frappe.ValidationError)
    delivery.latitude, delivery.longitude, delivery.location_set = latitude, longitude, 1
    _save(delivery, order, delivery.status, delivery.assigned_delivery_person, "Delivery coordinates updated.")
    return _serialize(delivery, detail=True)


@frappe.whitelist(methods=["POST"])
def clear_delivery_coordinates(delivery_name):
    _require_manager()
    delivery, order = _delivery_locked(delivery_name)
    if delivery.status in {"Delivered", "Cancelled"}:
        frappe.throw("Coordinates cannot be changed for a completed or cancelled delivery.", frappe.ValidationError)
    if delivery.location_set:
        delivery.latitude = delivery.longitude = 0
        delivery.location_set = 0
        _save(delivery, order, delivery.status, delivery.assigned_delivery_person, "Delivery coordinates cleared.")
    return _serialize(delivery, detail=True)


def _plan_signature(rider, location, deliveries):
    snapshot = [
        rider, str(location.location_updated_at), float(location.latitude), float(location.longitude),
        sorted((row.name, row.delivery_area, float(row.latitude), float(row.longitude)) for row in deliveries),
    ]
    return hashlib.sha256(json.dumps(snapshot, separators=(",", ":")).encode()).hexdigest()


@frappe.whitelist()
def suggest_delivery_group(delivery_name, radius_km=5, max_stops=5):
    _require_manager()
    try:
        radius = float(radius_km)
        count = int(str(max_stops))
        if not math.isfinite(radius) or not 0.1 <= radius <= 50 or not 1 <= count <= 10:
            raise ValueError
    except (ValueError, TypeError, OverflowError):
        frappe.throw("Select a radius from 0.1 to 50 km and 1 to 10 stops.", frappe.ValidationError)
    name = _text(delivery_name, "Delivery", required=True)
    seed = frappe.get_doc("Delivery", name)
    if seed.status != "Awaiting Assignment" or seed.assigned_delivery_person or not seed.location_set or not seed.delivery_area:
        frappe.throw("Choose an unassigned delivery with an area and coordinates.", frappe.ValidationError)
    origin = _coordinates(seed.latitude, seed.longitude)
    now = now_datetime()
    riders = frappe.db.sql(
        """
        SELECT u.name, u.full_name, l.latitude, l.longitude, l.accuracy_meters, l.location_updated_at
        FROM `tabUser` u
        INNER JOIN `tabDelivery Rider Location` l ON l.rider = u.name
        WHERE u.enabled = 1 AND u.name NOT IN ('Guest', 'Administrator')
          AND l.location_set = 1 AND l.location_updated_at BETWEEN %s AND %s
          AND EXISTS (SELECT 1 FROM `tabHas Role` r
              WHERE r.parent = u.name AND r.parenttype = 'User' AND r.role = 'Delivery Staff')
          AND NOT EXISTS (SELECT 1 FROM `tabDelivery` d
              WHERE d.assigned_delivery_person = u.name
                AND d.status NOT IN ('Delivered', 'Failed', 'Cancelled'))
        """, (now - timedelta(minutes=30), now), as_dict=True,
    )
    if not riders:
        frappe.throw("No idle riders have shared a recent location.", frappe.ValidationError)
    rider = min(riders, key=lambda row: (distance_km((row.latitude, row.longitude), origin), row.name))
    candidates = frappe.db.sql(
        """
        SELECT d.name, d.`order`, d.delivery_address, d.delivery_area, d.status, d.latitude, d.longitude
        FROM `tabDelivery` d
        INNER JOIN `tabSales Order` o ON o.name = d.`order`
        WHERE d.delivery_area = %s AND d.status = 'Awaiting Assignment'
          AND COALESCE(d.assigned_delivery_person, '') = '' AND d.location_set = 1
          AND o.status = 'Ready for Delivery'
        ORDER BY d.name LIMIT 1001
        """, seed.delivery_area, as_dict=True,
    )
    if len(candidates) > 1000:
        frappe.throw("Too many deliveries in this area to plan safely; narrow the backlog first.", frappe.ValidationError)
    if not any(row.name == name for row in candidates):
        frappe.throw("The delivery is no longer ready for assignment.", frappe.ValidationError)
    nearby = sorted(
        (row for row in candidates if row.name != name
         and distance_km(origin, (row.latitude, row.longitude)) <= radius),
        key=lambda row: (distance_km(origin, (row.latitude, row.longitude)), row.name),
    )
    selected = [next(row for row in candidates if row.name == name)] + nearby[:count - 1]
    route = nearest_delivery_route((rider.latitude, rider.longitude), selected)
    return {
        "rider": rider.name, "rider_name": rider.full_name,
        "location_updated_at": rider.location_updated_at,
        "accuracy_meters": rider.accuracy_meters,
        "plan_token": _plan_signature(rider.name, rider, selected),
        "route": route, "total_distance_km": round(sum(row["distance_km"] for row in route), 2),
    }


@frappe.whitelist(methods=["POST"])
def assign_delivery_group(rider, delivery_names, scheduled_delivery_date, plan_token):
    _require_manager()
    try:
        names = json.loads(delivery_names) if isinstance(delivery_names, str) else delivery_names
    except (ValueError, TypeError):
        frappe.throw("Select valid deliveries for the group.", frappe.ValidationError)
    if (
        not isinstance(names, list) or not 1 <= len(names) <= 10
        or any(not isinstance(name, str) or not name.strip() or len(name) > 140 for name in names)
    ):
        frappe.throw("Select 1 to 10 valid deliveries for the group.", frappe.ValidationError)
    names = [name.strip() for name in names]
    if len(set(names)) != len(names):
        frappe.throw("A delivery cannot appear twice in a group.", frappe.ValidationError)
    if not isinstance(plan_token, str) or not re.fullmatch(r"[a-f0-9]{64}", plan_token):
        frappe.throw("A current delivery plan is required.", frappe.ValidationError)
    rider = _text(rider, "Delivery person", required=True)
    _schedule(scheduled_delivery_date)
    frappe.db.sql("SELECT name FROM `tabUser` WHERE name = %s FOR UPDATE", rider)
    _validate_person(rider)
    location = _rider_location(rider, for_update=True)
    if not location:
        frappe.throw("The rider must share a recent location again.", frappe.ValidationError)
    active = frappe.db.sql(
        """SELECT name FROM `tabDelivery` WHERE assigned_delivery_person = %s
           AND status NOT IN ('Delivered', 'Failed', 'Cancelled') LIMIT 1 FOR UPDATE""", rider,
    )
    if active:
        frappe.throw("The rider is no longer idle. Plan the group again.", frappe.ValidationError)
    deliveries = [_delivery_locked(name) for name in sorted(names)]
    areas = set()
    for delivery, order in deliveries:
        if (delivery.status != "Awaiting Assignment" or delivery.assigned_delivery_person
                or not delivery.location_set or not delivery.delivery_area or order.status != "Ready for Delivery"):
            frappe.throw("A delivery is no longer ready for grouping. Plan again.", frappe.ValidationError)
        _coordinates(delivery.latitude, delivery.longitude)
        areas.add(delivery.delivery_area)
    if len(areas) != 1:
        frappe.throw("Grouped deliveries must belong to the same delivery area.", frappe.ValidationError)
    if _plan_signature(rider, location, [delivery for delivery, _ in deliveries]) != plan_token:
        frappe.throw("The rider location or delivery coordinates changed. Plan the group again.", frappe.ValidationError)
    for name in names:
        assign_delivery(name, rider, scheduled_delivery_date, "Assigned as a planned delivery group.")
    return {"rider": rider, "deliveries": names}


@frappe.whitelist()
def my_delivery_route():
    rider = _require_rider()
    location = _rider_location(rider)
    if not location:
        frappe.throw("Share your current location to plan a route.", frappe.ValidationError)
    deliveries = frappe.get_all(
        "Delivery", filters={
            "assigned_delivery_person": rider, "status": ["not in", ["Delivered", "Failed", "Cancelled"]],
        },
        fields=["name", "order", "status", "delivery_address", "delivery_area",
                "latitude", "longitude", "location_set"],
        order_by="name", limit_page_length=0,
    )
    located = [row for row in deliveries if row.location_set]
    route = nearest_delivery_route((location.latitude, location.longitude), located)
    return {
        "route": route, "missing_coordinates": len(deliveries) - len(located),
        "location_updated_at": location.location_updated_at,
        "total_distance_km": round(sum(row["distance_km"] for row in route), 2),
    }


@frappe.whitelist(methods=["POST"])
def update_delivery(delivery_name, status, notes="", confirmation=0, cash_collected=0):
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
    is_cod = (
        order.get("payment_method") == "Cash on Delivery"
        and frappe.db.exists(
            "Payment Transaction",
            {"order": order.name, "payment_method": "Cash on Delivery", "status": "Pending"},
        )
    )
    if (
        status in {"Picked Up", "Dispatched", "In Transit", "Delivered"}
        and order.payment_status != "Paid"
        and not is_cod
    ):
        frappe.throw("Verified payment is required before dispatch or delivery.", frappe.ValidationError)
    if status == "Delivered":
        if str(confirmation) != "1":
            frappe.throw("Explicit delivery confirmation is required.", frappe.ValidationError)
        if frappe.session.user != delivery.assigned_delivery_person:
            frappe.throw("Only the assigned delivery person can confirm receipt.", frappe.PermissionError)
        if not _proof_files(delivery.name):
            frappe.throw("Upload a private proof-of-delivery photo before completing delivery.",
                         frappe.ValidationError)
        if is_cod:
            if str(cash_collected) != "1":
                frappe.throw("Confirm cash was collected from the customer before completing this COD delivery.",
                             frappe.ValidationError)
            delivery.cash_collected = 1
            delivery.cash_collected_amount = order.total
            delivery.cash_collected_at = now_datetime()
            delivery.cash_collected_by = frappe.session.user
            notes = " ".join(
                part for part in (
                    notes,
                    f"Rider recorded cash collection of {order.currency} {order.total}; finance confirmation is pending.",
                ) if part
            )
        elif str(cash_collected) == "1":
            frappe.throw("Cash collection confirmation is only valid for Cash on Delivery orders.",
                         frappe.ValidationError)
    previous_status, previous_person = delivery.status, delivery.assigned_delivery_person
    delivery.status = status
    if notes:
        delivery.delivery_notes = notes
    if status in {"Picked Up", "Dispatched"} and previous_status != status:
        delivery.dispatch_date = now_datetime()
    if status == "Delivered":
        delivery.completion_date = now_datetime()
        delivery.completed_by = frappe.session.user
    _save(delivery, order, previous_status, previous_person, notes)
    if status == "Delivered" and order.payment_status == "Paid":
        with _workflow():
            order.status = "Completed"
            order.save(ignore_permissions=True)
    return _serialize(delivery, detail=True)


@frappe.whitelist(methods=["POST"])
def reject_delivery(delivery_name, reason):
    if "Delivery Staff" not in frappe.get_roles(frappe.session.user):
        frappe.throw("Only assigned delivery personnel can reject an assignment.", frappe.PermissionError)
    reason = _text(reason, "Rejection reason", 1000, required=True)
    delivery, order = _delivery_locked(delivery_name)
    if delivery.assigned_delivery_person != frappe.session.user:
        frappe.throw("You can only reject your assigned delivery.", frappe.PermissionError)
    if delivery.status != "Assigned":
        frappe.throw("Only an unaccepted assignment can be rejected.", frappe.ValidationError)
    previous_person = delivery.assigned_delivery_person
    delivery.status = "Awaiting Assignment"
    delivery.assigned_delivery_person = None
    delivery.scheduled_delivery_date = None
    delivery.delivery_notes = reason
    _save(delivery, order, "Assigned", previous_person, f"Assignment rejected: {reason}")
    return _serialize(delivery, detail=True)


def _proof_files(delivery_name):
    return frappe.get_all(
        "File",
        filters={
            "attached_to_doctype": "Delivery",
            "attached_to_name": delivery_name,
            "is_private": 1,
        },
        fields=["name", "file_name", "file_url", "creation"],
        order_by="creation desc",
        limit_page_length=20,
    )


@frappe.whitelist(methods=["POST"])
def upload_delivery_proof(delivery_name, file_data):
    if "Delivery Staff" not in frappe.get_roles(frappe.session.user):
        frappe.throw("Only delivery personnel can upload proof of delivery.", frappe.PermissionError)
    delivery, order = _delivery_locked(delivery_name)
    if delivery.assigned_delivery_person != frappe.session.user:
        frappe.throw("You can only upload proof for your assigned delivery.", frappe.PermissionError)
    if delivery.status not in {"Picked Up", "Dispatched", "In Transit"}:
        frappe.throw("Proof can only be uploaded for an active delivery.", frappe.ValidationError)
    if not isinstance(file_data, str) or not file_data or len(file_data) > ((MAX_PROOF_BYTES + 2) // 3) * 4:
        frappe.throw("Proof photo must be no larger than 5 MB.", frappe.ValidationError)
    try:
        content = base64.b64decode(file_data, validate=True)
    except (ValueError, binascii.Error):
        frappe.throw("The proof photo is not valid base64 image data.", frappe.ValidationError)
    if not content or len(content) > MAX_PROOF_BYTES:
        frappe.throw("Proof photo must be no larger than 5 MB.", frappe.ValidationError)
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        extension = "png"
    elif content.startswith(b"\xff\xd8\xff"):
        extension = "jpg"
    elif len(content) >= 12 and content[:4] == b"RIFF" and content[8:12] == b"WEBP":
        extension = "webp"
    else:
        frappe.throw("Upload a PNG, JPEG, or WebP proof photo.", frappe.ValidationError)
    from frappe.utils.file_manager import save_file

    saved = save_file(
        f"delivery-proof-{delivery.name}.{extension}",
        content,
        "Delivery",
        delivery.name,
        is_private=1,
    )
    return {
        "file_name": saved.file_name,
        "file_url": saved.file_url,
        "creation": saved.creation,
    }


@frappe.whitelist(methods=["POST"])
def save_delivery_area(area_name, delivery_fee, currency="KES", enabled=1, modified=""):
    _require_manager()
    if (
        frappe.session.user != "Administrator"
        and not MANAGE_DELIVERY_AREA_ROLES.intersection(frappe.get_roles())
    ):
        frappe.throw("Delivery area settings are not available to this role.", frappe.PermissionError)
    area_name = _text(area_name, "Area name", required=True)
    if str(enabled) not in {"0", "1"}:
        frappe.throw("Enabled must be 0 or 1.", frappe.ValidationError)
    if frappe.db.exists("Delivery Area", area_name):
        area = frappe.get_doc("Delivery Area", area_name, for_update=True)
        area.check_permission("write")
        if not modified or str(area.modified) != modified:
            frappe.throw("This area changed. Select Edit area again before saving.", frappe.ValidationError)
        event = "Delivery area updated"
    else:
        if modified:
            frappe.throw("This area no longer exists. Refresh before continuing.", frappe.ValidationError)
        area = frappe.new_doc("Delivery Area")
        area.area_name = area_name
        event = "Delivery area created"
    area.delivery_fee, area.currency, area.enabled = delivery_fee, currency, int(enabled)
    area.save()
    record_admin_event(event, "Delivery Area", area.name, "Area rate or availability saved")
    return {"name": area.name, "delivery_fee": area.delivery_fee, "currency": area.currency, "enabled": area.enabled}


@frappe.whitelist()
def list_delivery_areas():
    _require_manager()
    return {
        "areas": frappe.get_list(
            "Delivery Area", fields=["name", "currency", "delivery_fee", "enabled", "modified"],
            order_by="area_name", limit_page_length=0,
        ),
        "can_create": bool(frappe.has_permission("Delivery Area", "create")),
        "can_write": bool(frappe.has_permission("Delivery Area", "write")),
        "can_delete": bool(frappe.has_permission("Delivery Area", "delete")),
    }


@frappe.whitelist(methods=["POST"])
def delete_delivery_area(area_name, modified):
    _require_manager()
    area = frappe.get_doc("Delivery Area", _text(area_name, "Area name", required=True), for_update=True)
    area.check_permission("delete")
    if not modified or str(area.modified) != modified:
        frappe.throw("This area changed. Refresh before deleting it.", frappe.ValidationError)
    if any(frappe.db.exists(doctype, {"delivery_area": area.name}) for doctype in ("Sales Order", "Delivery")):
        frappe.throw("This area has order or delivery history. Disable it instead of deleting it.", frappe.ValidationError)
    # Native link checks also protect references from custom apps and fields.
    frappe.delete_doc("Delivery Area", area.name)
    record_admin_event("Delivery area deleted", "Delivery Area", area.name, "Unused delivery area deleted")
    return {"message": "Unused delivery area deleted. Existing orders have not changed."}
