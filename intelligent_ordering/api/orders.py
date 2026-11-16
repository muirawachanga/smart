import frappe

from intelligent_ordering.api.checkout import _serialize_order
from intelligent_ordering.utils.checkout import ORDER_STATUSES
from intelligent_ordering.utils.validation import validate_pagination


ORDER_STAFF_ROLES = {"System Manager", "Business Admin", "Store Manager", "Order Manager"}
ORDER_READ_ROLES = ORDER_STAFF_ROLES | {"Customer Support"}


@frappe.whitelist(allow_guest=True)
def get_my_orders(page=1, page_size=20, status=""):
    user = frappe.session.user
    if user == "Guest":
        return {"requires_login": True, "orders": []}
    _require_customer(user)

    try:
        page, page_size = validate_pagination(page, page_size)
    except ValueError as error:
        frappe.throw(str(error), frappe.ValidationError)

    status = _validate_status_filter(status)
    profile = frappe.db.get_value(
        "Customer Profile",
        {"user": user, "enabled": 1},
        "name",
    )
    if not profile:
        return {
            "requires_login": False,
            "orders": [],
            "page": page,
            "page_size": page_size,
            "has_more": False,
        }

    filters = {"customer": profile}
    if status:
        filters["status"] = status
    rows = frappe.get_list(
        "Sales Order",
        filters=filters,
        fields=[
            "name",
            "order_datetime",
            "status",
            "currency",
            "total",
        ],
        order_by="order_datetime desc, creation desc",
        limit_start=(page - 1) * page_size,
        limit_page_length=page_size + 1,
    )
    has_more = len(rows) > page_size
    return {
        "requires_login": False,
        "orders": rows[:page_size],
        "page": page,
        "page_size": page_size,
        "has_more": has_more,
    }


@frappe.whitelist(allow_guest=True)
def get_order(order_name):
    if frappe.session.user == "Guest":
        return {"requires_login": True}
    order = frappe.get_doc("Sales Order", _validate_order_name(order_name))
    order.check_permission("read")
    result = _serialize_order(order)
    if ORDER_READ_ROLES.intersection(frappe.get_roles(frappe.session.user)) or frappe.session.user == "Administrator":
        result["history"] = frappe.get_all(
            "Admin Audit Log",
            filters={"reference_doctype": "Sales Order", "reference_name": order.name},
            fields=["event_datetime", "responsible_user", "event_type", "details"],
            order_by="event_datetime asc", limit_page_length=100,
        )
        result["deliveries"] = frappe.get_all(
            "Delivery", filters={"order": order.name},
            fields=["name", "status", "assigned_delivery_person", "scheduled_delivery_date"],
            order_by="creation desc", limit_page_length=20,
        )
    return result


@frappe.whitelist(allow_guest=True)
def get_my_order(order_name):
    """Return order details only to the customer who owns them."""
    user = frappe.session.user
    if user == "Guest":
        return {"requires_login": True}
    _require_customer(user)
    order_name = _validate_order_name(order_name)
    order_reference = frappe.db.get_value(
        "Sales Order", order_name, ["name", "customer"], as_dict=True
    )
    if not order_reference:
        frappe.throw("This order is unavailable.", frappe.PermissionError)
    owner = frappe.db.get_value("Customer Profile", order_reference.customer, "user")
    if owner != user:
        frappe.throw("This order is unavailable.", frappe.PermissionError)
    order = frappe.get_doc("Sales Order", order_reference.name)
    return _serialize_order(order)


@frappe.whitelist()
def list_orders(search="", status="", payment_status="", page=1, page_size=20):
    _require_order_staff(read_only=True)
    if not isinstance(search, str):
        frappe.throw("Search must be text.", frappe.ValidationError)
    search = search.strip()
    if len(search) > 100:
        frappe.throw("Search must not exceed 100 characters.", frappe.ValidationError)
    try:
        page, page_size = validate_pagination(page, page_size)
    except ValueError as error:
        frappe.throw(str(error), frappe.ValidationError)

    status = _validate_status_filter(status)
    if payment_status is None:
        payment_status = ""
    if not isinstance(payment_status, str) or (
        payment_status and payment_status not in {
            "Unpaid", "Pending", "Paid", "Failed", "Refunded"
        }
    ):
        frappe.throw("Select a valid payment status.", frappe.ValidationError)
    filters = {"status": status} if status else {}
    if payment_status:
        filters["payment_status"] = payment_status
    or_filters = []
    if search:
        search_pattern = f"%{search}%"
        or_filters = [
            ["Sales Order", "name", "like", search_pattern],
            ["Sales Order", "customer_name_snapshot", "like", search_pattern],
            ["Sales Order", "customer_phone_snapshot", "like", search_pattern],
        ]

    rows = frappe.get_list(
        "Sales Order",
        filters=filters,
        or_filters=or_filters,
        fields=[
            "name",
            "order_datetime",
            "customer_name_snapshot",
            "customer_phone_snapshot",
            "status",
            "currency",
            "total",
        ],
        order_by="order_datetime desc, creation desc",
        limit_start=(page - 1) * page_size,
        limit_page_length=page_size + 1,
    )
    has_more = len(rows) > page_size
    return {
        "orders": rows[:page_size],
        "page": page,
        "page_size": page_size,
        "has_more": has_more,
    }


@frappe.whitelist(methods=["POST"])
def update_order_status(order_name, status):
    _require_order_staff()
    order = frappe.get_doc("Sales Order", _validate_order_name(order_name), for_update=True)
    order.check_permission("write")
    order.status = status
    order.save()
    return _serialize_order(order)


@frappe.whitelist()
def order_overview():
    _require_order_staff()
    rows = frappe.get_list(
        "Sales Order", fields=["status", "count(name) as count"],
        group_by="status", limit_page_length=0,
    )
    return {"statuses": rows}


def _require_customer(user):
    if "Customer" not in frappe.get_roles(user):
        frappe.throw("Customer access is required.", frappe.PermissionError)


def _require_order_staff(read_only=False):
    allowed_roles = ORDER_READ_ROLES if read_only else ORDER_STAFF_ROLES
    if frappe.session.user != "Administrator" and not allowed_roles.intersection(frappe.get_roles(frappe.session.user)):
        frappe.throw("Order management access is required.", frappe.PermissionError)


def _validate_status_filter(status):
    if status is None:
        return ""
    if not isinstance(status, str):
        frappe.throw("Status must be text.", frappe.ValidationError)
    status = status.strip()
    if status and status not in ORDER_STATUSES:
        frappe.throw("Select a valid order status.", frappe.ValidationError)
    return status


def _validate_order_name(order_name):
    if not isinstance(order_name, str) or not order_name.strip():
        frappe.throw("An order number is required.", frappe.ValidationError)
    if len(order_name) > 140:
        frappe.throw("Order number is too long.", frappe.ValidationError)
    return order_name.strip()
