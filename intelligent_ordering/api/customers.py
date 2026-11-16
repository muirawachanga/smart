import re

import frappe
from frappe.rate_limiter import rate_limit
from frappe.utils import escape_html, now_datetime, validate_email_address

from intelligent_ordering.api.checkout import _require_customer, _save_customer_profile, _serialize_order
from intelligent_ordering.api.orders import _require_order_staff, _validate_order_name
from intelligent_ordering.utils.audit import record_admin_event
from intelligent_ordering.utils.checkout import (
    validate_address, validate_customer_name, validate_phone,
)
from intelligent_ordering.utils.validation import validate_pagination
from intelligent_ordering.utils.mpesa import normalize_phone


ADDRESS_FIELDS = [
    "name", "address_label", "address_line_1", "address_line_2",
    "city", "region", "postal_code", "is_default",
]
CANCELLATION_FIELDS = (
    "cancellation_request_status", "cancellation_reason", "cancellation_requested_at",
    "cancellation_resolved_at", "cancellation_resolved_by", "cancellation_response",
)


@frappe.whitelist(allow_guest=True, methods=["POST"])
@rate_limit(limit=5, seconds=3600)
def register(email, full_name, phone="", password="", confirm_password="",
             terms_version="", privacy_version="", accept_terms=0, acknowledge_privacy=0,
             marketing_consent=0):
    """Create a Customer-only Frappe account and an immutable consent record."""
    from frappe.core.doctype.user.user import is_signup_disabled
    from intelligent_ordering.api.policies import require_acceptance
    from intelligent_ordering.utils.authentication import validate_new_password

    if frappe.session.user != "Guest":
        frappe.throw("Sign out before registering a customer account.", frappe.PermissionError)
    if is_signup_disabled():
        frappe.throw("Customer registration is disabled. Contact the store.", frappe.ValidationError)
    try:
        full_name = validate_customer_name(full_name)
        phone = validate_phone(phone)
    except ValueError as error:
        frappe.throw(str(error), frappe.ValidationError)
    if not isinstance(email, str) or len(email) > 140:
        frappe.throw("Enter a valid email address.", frappe.ValidationError)
    email = validate_email_address(email.strip().lower(), throw=True)
    require_acceptance(terms_version, privacy_version, accept_terms, acknowledge_privacy)
    if marketing_consent not in (0, 1, "0", "1"):
        frappe.throw("Invalid marketing consent.", frappe.ValidationError)
    validate_new_password(password, confirm_password, (full_name, email, phone))
    if frappe.db.exists("User", email):
        frappe.throw("An account already uses this email. Sign in or reset your password.", frappe.ValidationError)
    user = frappe.get_doc({
        "doctype": "User", "email": email, "first_name": escape_html(full_name),
        "enabled": 1, "user_type": "Website User", "send_welcome_email": 0,
        "new_password": password, "mobile_no": phone,
        "roles": [{"role": "Customer"}],
    })
    user.insert(ignore_permissions=True)
    profile = _save_customer_profile(email, full_name, phone)
    frappe.get_doc({
        "doctype": "SmartO Policy Acceptance", "user": email, "customer": profile.name,
        "terms_version": terms_version, "privacy_version": privacy_version,
        "marketing_consent": int(marketing_consent),
    }).insert(ignore_permissions=True)
    return {"message": "Account created. Sign in to start shopping."}


@frappe.whitelist(allow_guest=True, methods=["POST"])
def sign_up(email, full_name, redirect_to=""):
    """Do not allow alternate signup to bypass policy consent."""
    frappe.throw("Create your SmartO customer account at /register.", frappe.ValidationError)


def _profile(lock=False):
    user = _require_customer()
    if lock:
        frappe.db.sql("SELECT name FROM `tabUser` WHERE name = %s FOR UPDATE", user)
    name = frappe.db.get_value("Customer Profile", {"user": user}, "name")
    if not name:
        return None
    profile = frappe.get_doc("Customer Profile", name)
    if not profile.enabled:
        frappe.throw("Your customer profile is disabled. Contact the store.", frappe.PermissionError)
    return profile


def _text(value, label, maximum, required=False):
    if not isinstance(value, str) or len(value.strip()) > maximum or (required and not value.strip()):
        frappe.throw(f"Enter valid {label} (up to {maximum} characters).", frappe.ValidationError)
    return value.strip()


def _page(page, page_size):
    try:
        return validate_pagination(page, page_size)
    except ValueError as error:
        frappe.throw(str(error), frappe.ValidationError)


@frappe.whitelist()
def get_profile():
    profile = _profile()
    return {
        "email": frappe.session.user,
        "full_name": profile.full_name if profile else frappe.db.get_value("User", frappe.session.user, "full_name"),
        "phone": profile.phone if profile else "",
    }


@frappe.whitelist(methods=["POST"])
def save_profile(full_name, phone):
    _profile(lock=True)
    try:
        full_name = validate_customer_name(full_name)
        phone = validate_phone(phone)
    except ValueError as error:
        frappe.throw(str(error), frappe.ValidationError)
    _save_customer_profile(frappe.session.user, full_name, phone)
    return get_profile()


@frappe.whitelist()
def list_addresses():
    profile = _profile()
    return frappe.get_all(
        "Customer Address", filters={"customer": profile.name}, fields=ADDRESS_FIELDS,
        order_by="is_default desc, creation desc", limit_page_length=100,
    ) if profile else []


@frappe.whitelist(methods=["POST"])
def save_address(address_line_1, city, address_name="", address_label="", address_line_2="",
                 region="", postal_code="", is_default=0):
    profile = _profile(lock=True)
    if not profile:
        frappe.throw("Save your customer profile before adding an address.", frappe.ValidationError)
    try:
        values = validate_address(address_line_1, city, address_line_2, region, postal_code)
    except ValueError as error:
        frappe.throw(str(error), frappe.ValidationError)
    values["address_label"] = _text(address_label, "address label", 140)
    if is_default not in (0, 1, "0", "1"):
        frappe.throw("Select a valid default address option.", frappe.ValidationError)
    if address_name:
        address_name = _text(address_name, "address reference", 140, True)
        if not frappe.db.exists("Customer Address", {"name": address_name, "customer": profile.name}):
            frappe.throw("This address is unavailable.", frappe.PermissionError)
        address = frappe.get_doc("Customer Address", address_name)
    else:
        if frappe.db.count("Customer Address", {"customer": profile.name}) >= 100:
            frappe.throw("You can save up to 100 addresses.", frappe.ValidationError)
        address = frappe.get_doc({"doctype": "Customer Address", "customer": profile.name})
    default_name = frappe.db.get_value(
        "Customer Address", {"customer": profile.name, "is_default": 1}, "name"
    )
    make_default = is_default in (1, "1") or not default_name or default_name == address.name
    if make_default:
        frappe.db.sql("UPDATE `tabCustomer Address` SET is_default = 0 WHERE customer = %s", profile.name)
    address.update({**values, "is_default": int(make_default)})
    address.save(ignore_permissions=True)
    return list_addresses()


@frappe.whitelist(methods=["POST"])
def delete_address(address_name):
    profile = _profile(lock=True)
    address_name = _text(address_name, "address reference", 140, True)
    if not profile or not frappe.db.exists(
        "Customer Address", {"name": address_name, "customer": profile.name}
    ):
        frappe.throw("This address is unavailable.", frappe.PermissionError)
    if frappe.db.exists("Sales Order", {"delivery_address": address_name}):
        frappe.throw("This address is referenced by an order and cannot be deleted.", frappe.ValidationError)
    frappe.delete_doc("Customer Address", address_name, ignore_permissions=True)
    remaining = list_addresses()
    if remaining and not any(row.is_default for row in remaining):
        frappe.db.set_value("Customer Address", remaining[0].name, "is_default", 1)
    return list_addresses()


@frappe.whitelist()
def payment_history(page=1, page_size=20, search="", search_by="phone"):
    profile = _profile()
    page, page_size = _page(page, page_size)
    if search_by not in ("phone", "receipt"):
        frappe.throw("Choose phone number or M-Pesa receipt search.", frappe.ValidationError)
    search = _text(search, "payment search", 40)
    predicate = ""
    params = [profile.name if profile else None]
    if search:
        if search_by == "phone":
           try:
               search = normalize_phone(search)
           except ValueError as error:
               frappe.throw(str(error), frappe.ValidationError)
           predicate = " AND p.phone_number = %s"
        else:
           search = search.upper()
           if not re.fullmatch(r"[A-Z0-9]{10,20}", search):
               frappe.throw("Enter a valid M-Pesa receipt reference (10-20 letters or digits).",
                            frappe.ValidationError)
           predicate = " AND p.mpesa_receipt_number = %s"
        params.append(search)
    params.extend([page_size + 1, (page - 1) * page_size])
    rows = frappe.db.sql(
        """SELECT p.name, p.`order`, p.amount, p.payment_method, p.status,
                  p.phone_number, p.mpesa_receipt_number, p.transaction_date, p.creation, o.currency
           FROM `tabPayment Transaction` p
           INNER JOIN `tabSales Order` o ON o.name = p.`order`
           WHERE o.customer = %s""" + predicate + """
           ORDER BY p.creation DESC, p.name DESC LIMIT %s OFFSET %s""",
        tuple(params), as_dict=True,
    ) if profile else []
    return {"transactions": rows[:page_size], "has_more": len(rows) > page_size, "page": page}


def _owned_order(order_name, lock=False):
    profile = _profile()
    order_name = _validate_order_name(order_name)
    if not profile or not frappe.db.exists("Sales Order", {"name": order_name, "customer": profile.name}):
        frappe.throw("This order is unavailable.", frappe.PermissionError)
    return frappe.get_doc("Sales Order", order_name, for_update=lock)


@frappe.whitelist()
def track_order(order_name):
    order = _owned_order(order_name)
    deliveries = frappe.get_all(
        "Delivery", filters={"order": order.name},
        fields=["name", "status", "scheduled_delivery_date", "modified"],
        order_by="creation desc", limit_page_length=1,
    )
    delivery = deliveries[0] if deliveries else None
    timeline = frappe.get_all(
        "Delivery Activity", filters={"parent": delivery.name, "parenttype": "Delivery", "parentfield": "activities"},
        fields=["activity_datetime", "from_status", "to_status"],
        order_by="idx asc", limit_page_length=100,
    ) if delivery else []
    return {
        "order_status": order.status, "payment_status": order.payment_status,
        "updated_at": order.modified, "delivery": delivery, "timeline": timeline,
        **{field: order.get(field) for field in CANCELLATION_FIELDS if field != "cancellation_resolved_by"},
    }


@frappe.whitelist(methods=["POST"])
def request_cancellation(order_name, reason):
    order = _owned_order(order_name, lock=True)
    reason = _text(reason, "cancellation reason", 1000, True)
    if order.status in {"Completed", "Cancelled"}:
        frappe.throw("This order cannot receive a cancellation request.", frappe.ValidationError)
    if order.cancellation_request_status not in (None, "", "Rejected"):
        frappe.throw("A cancellation request already exists for this order. Contact the store.", frappe.ValidationError)
    order.cancellation_request_status = "Requested"
    order.cancellation_reason = reason
    order.cancellation_requested_at = now_datetime()
    order.cancellation_response = None
    order.cancellation_resolved_at = None
    order.cancellation_resolved_by = None
    _save_cancellation(order)
    return track_order(order.name)


@frappe.whitelist(methods=["POST"])
def resolve_cancellation(order_name, decision, response):
    _require_order_staff()
    if not isinstance(decision, str) or decision not in {"Approved", "Rejected"}:
        frappe.throw("Select Approved or Rejected.", frappe.ValidationError)
    response = _text(response, "cancellation response", 1000, True)
    order = frappe.get_doc("Sales Order", _validate_order_name(order_name), for_update=True)
    order.check_permission("write")
    if order.cancellation_request_status != "Requested":
        frappe.throw("There is no pending cancellation request.", frappe.ValidationError)
    if order.status in {"Completed", "Cancelled"}:
        frappe.throw("This order is already closed.", frappe.ValidationError)
    order.cancellation_request_status = decision
    order.cancellation_response = response
    order.cancellation_resolved_at = now_datetime()
    order.cancellation_resolved_by = frappe.session.user
    if decision == "Approved":
        order.status = "Cancelled"
    _save_cancellation(order)
    return _serialize_order(order)


def _save_cancellation(order):
    previous = getattr(frappe.flags, "processing_customer_cancellation", False)
    frappe.flags.processing_customer_cancellation = True
    try:
        order.save(ignore_permissions=True)
    finally:
        frappe.flags.processing_customer_cancellation = previous
    record_admin_event(
        "Cancellation request " + order.cancellation_request_status,
        "Sales Order", order.name, order.cancellation_response or order.cancellation_reason,
    )


@frappe.whitelist()
def notifications(page=1, page_size=20):
    _profile()
    page, page_size = _page(page, page_size)
    rows = frappe.get_all(
        "Notification Log", filters={"for_user": frappe.session.user, "document_type": "Sales Order"},
        fields=["name", "subject", "document_name", "read", "creation"],
        order_by="creation desc, name desc", limit_start=(page - 1) * page_size,
        limit_page_length=page_size + 1,
    )
    return {"notifications": rows[:page_size], "has_more": len(rows) > page_size, "page": page}


@frappe.whitelist(methods=["POST"])
def read_notification(name):
    _profile()
    name = _text(name, "notification reference", 140, True)
    if not frappe.db.exists("Notification Log", {
        "name": name, "for_user": frappe.session.user, "document_type": "Sales Order",
    }):
        frappe.throw("This notification is unavailable.", frappe.PermissionError)
    frappe.db.set_value("Notification Log", name, "read", 1)
    return {"name": name, "read": 1}
