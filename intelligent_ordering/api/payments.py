import hashlib
import json
import secrets
from contextlib import contextmanager
from datetime import timedelta

import frappe
from frappe.utils import get_datetime, now_datetime

from intelligent_ordering.utils.mpesa import (
    DarajaClient, DarajaError, DarajaRejected,
    normalize_phone, parse_callback, payment_amount,
)
from intelligent_ordering.utils.audit import record_admin_event
from intelligent_ordering.utils.validation import validate_pagination


PAYMENT_STAFF = {"System Manager", "Business Admin", "Store Manager", "Order Manager", "Finance Manager"}
RECONCILIATION_ROLES = {"System Manager", "Business Admin", "Finance Manager"}
FINAL_FAILURE_CODES = {1, 17, 26, 1032, 1037, 2001}
PUBLIC_FIELDS = [
    "name", "order", "phone_number", "amount", "payment_method", "status",
    "mpesa_receipt_number", "transaction_date", "failure_description", "creation",
]


def _client(environment=None):
    config = frappe.conf.get("mpesa")
    if not isinstance(config, dict):
        frappe.throw("M-Pesa is not configured.", frappe.ValidationError)
    if environment and environment != config.get("environment", "Sandbox"):
        frappe.throw(
            "Restore the transaction's M-Pesa environment before reconciliation.",
            frappe.ValidationError,
        )
    try:
        return DarajaClient(config)
    except ValueError as error:
        frappe.throw(str(error), frappe.ValidationError)


def _staff():
    if frappe.session.user != "Administrator" and not PAYMENT_STAFF.intersection(
        frappe.get_roles(frappe.session.user)
    ):
        frappe.throw("Payment management access is required.", frappe.PermissionError)


def _owned_order(name):
    _identifier(name)
    order = frappe.get_doc("Sales Order", name)
    owner = frappe.db.get_value("Customer Profile", order.customer, "user")
    if frappe.session.user == "Guest" or owner != frappe.session.user:
        frappe.throw("You can only pay for your own orders.", frappe.PermissionError)
    order.check_permission("read")
    return order


@contextmanager
def _processing():
    previous = getattr(frappe.flags, "processing_payment", False)
    frappe.flags.processing_payment = True
    try:
        yield
    finally:
        frappe.flags.processing_payment = previous


def _save(doc):
    with _processing():
        if doc.is_new():
            doc.insert(ignore_permissions=True)
        else:
            doc.save(ignore_permissions=True)


def create_cod_transaction(order):
    """Create the outstanding COD payment record during trusted checkout."""
    payment = frappe.get_doc({
        "doctype": "Payment Transaction",
        "order": order.name,
        "customer": order.customer,
        "phone_number": order.customer_phone_snapshot,
        "amount": order.total,
        "payment_method": "Cash on Delivery",
        "environment": "Not Applicable",
        "status": "Pending",
    })
    _save(payment)
    return payment


def _lock_order(name):
    frappe.db.sql("SELECT name FROM `tabSales Order` WHERE name = %s FOR UPDATE", name)


def _locked_payment(name):
    _identifier(name)
    order_name = frappe.db.get_value("Payment Transaction", name, "order")
    if not order_name:
        frappe.throw("Payment transaction not found.", frappe.DoesNotExistError)
    _lock_order(order_name)
    frappe.db.sql(
        "SELECT name FROM `tabPayment Transaction` WHERE name = %s FOR UPDATE", name
    )
    return frappe.get_doc("Payment Transaction", name, for_update=True)


def _identifier(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 140:
        frappe.throw("A valid document identifier is required.", frappe.ValidationError)


def _public(doc):
    return {field: doc.get(field) for field in PUBLIC_FIELDS}


def _active_payment(order_name):
    rows = frappe.db.sql(
        """
        SELECT name FROM `tabPayment Transaction`
        WHERE `order` = %s AND status IN ('Initiated', 'Pending', 'Successful')
        ORDER BY creation DESC LIMIT 1 FOR UPDATE
        """, order_name,
    )
    return rows[0][0] if rows else None


@frappe.whitelist(methods=["POST"])
def initiate_payment(order_name, phone):
    """Persist the attempt before calling Daraja; ambiguous requests are not retried."""
    order = _owned_order(order_name)
    client = _client()
    try:
        phone = normalize_phone(phone)
    except ValueError as error:
        frappe.throw(str(error), frappe.ValidationError)
    _lock_order(order.name)
    order = frappe.get_doc("Sales Order", order.name, for_update=True)
    try:
        amount = payment_amount(order.total)
    except ValueError as error:
        frappe.throw(str(error), frappe.ValidationError)
    if order.currency != "KES" or order.status in {"Cancelled", "Completed"}:
        frappe.throw("This order is not eligible for M-Pesa payment.", frappe.ValidationError)
    if order.get("payment_method") != "M-Pesa":
        frappe.throw("This order uses Cash on Delivery.", frappe.ValidationError)
    if order.payment_status == "Paid":
        frappe.throw("This order is already paid.", frappe.ValidationError)
    active = _active_payment(order.name)
    if active:
        return _public(frappe.get_doc("Payment Transaction", active))

    token = secrets.token_urlsafe(32)
    payment = frappe.get_doc({
        "doctype": "Payment Transaction", "order": order.name,
        "customer": order.customer, "phone_number": phone, "amount": amount,
        "payment_method": "M-Pesa",
        "environment": client.config.get("environment", "Sandbox"),
        "status": "Initiated",
        "callback_token_hash": hashlib.sha256(token.encode()).hexdigest(),
    })
    _save(payment)
    # External side effects cannot be rolled back. Retain the attempt across
    # timeouts/process failures so a second request cannot charge again.
    frappe.db.commit()
    try:
        response = client.initiate(order.name, phone, amount, token)
    except DarajaRejected:
        payment = _locked_payment(payment.name)
        if payment.status == "Initiated":
            payment.status = "Failed"
            payment.failure_description = (
                "Provider rejected initiation; no STK push was accepted. Check configuration and retry."
            )
            _save(payment)
        return _public(payment)
    except DarajaError:
        payment = _locked_payment(payment.name)
        if payment.status == "Initiated":
            payment.failure_description = (
                "Provider outcome unknown. Do not retry; reconcile with Safaricom."
            )
            _save(payment)
        return _public(payment)

    payment = _locked_payment(payment.name)
    if payment.status in {"Successful", "Failed", "Cancelled"}:
        return _public(payment)
    merchant = response.get("MerchantRequestID")
    checkout = response.get("CheckoutRequestID")
    if (
        str(response.get("ResponseCode")) == "0"
        and isinstance(merchant, str) and 1 <= len(merchant) <= 140
        and isinstance(checkout, str) and 1 <= len(checkout) <= 140
    ):
        if payment.checkout_request_id and (
            payment.checkout_request_id != checkout or payment.merchant_request_id != merchant
        ):
            frappe.throw("Provider payment identifiers conflict.", frappe.ValidationError)
        payment.merchant_request_id = merchant
        payment.checkout_request_id = checkout
        payment.status = "Pending"
        payment.failure_description = ""
    elif (
        str(response.get("ResponseCode")) in {"1", "2"}
        and not payment.checkout_request_id and not checkout
    ):
        payment.status = "Failed"
        payment.failure_description = "Provider rejected the STK push request."
    else:
        # An unrecognized response is not proof the charge was never initiated.
        payment.failure_description = "STK initiation was not confirmed. Staff reconciliation required."
    _save(payment)
    return _public(payment)


@frappe.whitelist(allow_guest=True, methods=["POST"])
def callback(token=None):
    """Token-authenticated callback plus an independent authenticated STK query."""
    if not isinstance(token, str) or not 40 <= len(token) <= 64:
        frappe.throw("Invalid payment callback.", frappe.PermissionError)
    payment_name = frappe.db.get_value(
        "Payment Transaction",
        {"callback_token_hash": hashlib.sha256(token.encode()).hexdigest()}, "name",
    )
    if not payment_name:
        frappe.throw("Invalid payment callback.", frappe.PermissionError)
    raw = frappe.request.get_data()
    if len(raw) > 16384:
        frappe.throw("Payment callback is too large.", frappe.ValidationError)
    try:
        payload = json.loads(raw)
        parsed = parse_callback(payload)
    except (ValueError, UnicodeDecodeError):
        frappe.throw("Invalid payment callback data.", frappe.ValidationError)
    payment = _locked_payment(payment_name)
    _validate_callback(payment, parsed)
    serialized = json.dumps(payload, separators=(",", ":"), sort_keys=True)
    if payment.callback_response and (
        parse_callback(json.loads(payment.callback_response)) != parsed
    ):
        frappe.throw("Conflicting payment callback.", frappe.ValidationError)
    if payment.status in {"Successful", "Failed", "Cancelled", "Reversed"}:
        if not payment.callback_response:
            frappe.throw("Conflicting payment callback.", frappe.ValidationError)
        return {"ResultCode": 0, "ResultDesc": "Already processed"}
    payment.merchant_request_id = parsed["merchant_request_id"]
    payment.checkout_request_id = parsed["checkout_request_id"]
    payment.callback_response = payment.callback_response or serialized
    payment.status = "Pending"
    _save(payment)
    _reconcile(payment)
    return {"ResultCode": 0, "ResultDesc": "Accepted"}


def _validate_callback(payment, parsed):
    if (
        payment.checkout_request_id
        and payment.checkout_request_id != parsed["checkout_request_id"]
    ) or (
        payment.merchant_request_id
        and payment.merchant_request_id != parsed["merchant_request_id"]
    ):
        frappe.throw("M-Pesa identifiers do not match.", frappe.ValidationError)
    if parsed["code"] == 0 and (
        parsed["amount"] != payment_amount(payment.amount)
        or parsed["phone"] != payment.phone_number
    ):
        frappe.throw("M-Pesa amount or phone does not match.", frappe.ValidationError)


def _reconcile(payment):
    if payment.payment_method != "M-Pesa":
        frappe.throw("Only M-Pesa transactions can be reconciled with Safaricom.", frappe.ValidationError)
    if payment.status in {"Successful", "Failed", "Cancelled", "Reversed"}:
        return
    if not payment.checkout_request_id:
        payment.failure_description = (
            "No checkout ID was received. Safaricom investigation is required before retrying."
        )
        _save(payment)
        return
    try:
        response = _client(payment.environment).query(payment.checkout_request_id)
    except DarajaError:
        payment.failure_description = "Status query unavailable; payment remains unresolved."
        _save(payment)
        return
    except frappe.ValidationError:
        payment.failure_description = (
            "M-Pesa configuration cannot reconcile this environment; restore configuration and retry."
        )
        _save(payment)
        return
    payment.query_response = json.dumps(response, separators=(",", ":"))
    if (
        response.get("CheckoutRequestID") != payment.checkout_request_id
        or response.get("MerchantRequestID") != payment.merchant_request_id
        or str(response.get("ResponseCode")) != "0"
    ):
        payment.failure_description = "Provider query did not verify the payment identifiers."
        _save(payment)
        return
    code = str(response.get("ResultCode"))
    if code == "0" and payment.callback_response:
        parsed = parse_callback(json.loads(payment.callback_response))
        _validate_callback(payment, parsed)
        if parsed["code"] != 0:
            payment.failure_description = "Provider query conflicts with callback; investigation required."
            _save(payment)
            return
        payment.status = "Successful"
        payment.mpesa_receipt_number = parsed["receipt"]
        payment.transaction_date = parsed["transaction_date"]
        payment.failure_description = ""
        order = frappe.get_doc("Sales Order", payment.order, for_update=True)
        if payment_amount(order.total) != payment_amount(payment.amount) or order.currency != "KES":
            frappe.throw("Order amount does not match the payment.", frappe.ValidationError)
        # This deliberately leaves status and inventory untouched, even if a
        # late payment arrives after staff cancellation.
        order.db_set("payment_status", "Paid", update_modified=True)
    elif code == "0":
        payment.failure_description = (
            "Provider reports success; awaiting authenticated callback amount and receipt."
        )
    elif code.isdigit() and int(code) in FINAL_FAILURE_CODES:
        parsed = (
            parse_callback(json.loads(payment.callback_response))
            if payment.callback_response else None
        )
        if parsed and str(parsed["code"]) != code:
            payment.failure_description = (
                "Provider query conflicts with callback; investigation required."
            )
        else:
            payment.status = "Cancelled" if code == "1032" else "Failed"
            payment.failure_description = str(response.get("ResultDesc", "Payment failed."))[:1000]
    else:
        payment.failure_description = "Payment is unresolved; reconcile again later."
    _save(payment)


@frappe.whitelist(methods=["POST"])
def reconcile_payment(payment_name):
    _staff()
    if not _can_reconcile():
        frappe.throw("Finance reconciliation access is required.", frappe.PermissionError)
    payment = _locked_payment(payment_name)
    _reconcile(payment)
    record_admin_event(
        "Payment reconciliation requested",
        "Payment Transaction",
        payment.name,
        f"Current status: {payment.status}; order {payment.order}",
    )
    return _public(payment)


@frappe.whitelist(methods=["POST"])
def confirm_cod_payment(payment_name):
    """Finance confirms rider-reported COD collection; riders cannot settle payments."""
    _staff()
    if not _can_reconcile():
        frappe.throw("Finance reconciliation access is required.", frappe.PermissionError)
    payment = _locked_payment(payment_name)
    if payment.payment_method != "Cash on Delivery":
        frappe.throw("This is not a Cash on Delivery transaction.", frappe.ValidationError)
    if payment.status != "Pending":
        frappe.throw("Only an outstanding COD transaction can be confirmed.", frappe.ValidationError)
    order = frappe.get_doc("Sales Order", payment.order, for_update=True)
    if order.status in {"Cancelled", "Completed"} or order.payment_status == "Paid":
        frappe.throw("This order is not eligible for COD payment confirmation.", frappe.ValidationError)

    delivery_name = frappe.db.get_value("Delivery", {"order": order.name}, "name")
    if not delivery_name:
        frappe.throw("The delivery has not been completed.", frappe.ValidationError)
    frappe.db.sql(
        "SELECT name FROM `tabDelivery` WHERE name = %s FOR UPDATE", delivery_name
    )
    delivery = frappe.get_doc("Delivery", delivery_name)
    if (
        delivery.status != "Delivered"
        or not delivery.cash_collected
        or delivery.cash_collected_amount != payment.amount
        or payment.amount != order.total
        or not delivery.cash_collected_at
        or not delivery.cash_collected_by
    ):
        frappe.throw("The rider has not recorded matching cash collection for this delivery.", frappe.ValidationError)

    payment.status = "Successful"
    payment.transaction_date = delivery.cash_collected_at
    payment.failure_description = ""
    _save(payment)
    order.db_set("payment_status", "Paid", update_modified=True)
    order.reload()
    was_processing_delivery = getattr(frappe.flags, "processing_delivery", False)
    frappe.flags.processing_delivery = True
    try:
        order.status = "Completed"
        order.save(ignore_permissions=True)
    finally:
        frappe.flags.processing_delivery = was_processing_delivery
    record_admin_event(
        "Cash on delivery payment confirmed",
        "Payment Transaction",
        payment.name,
        f"Order {order.name}; {payment.amount} {order.currency}; collected by {delivery.cash_collected_by}.",
    )
    return _public(payment)


def _can_reconcile():
    return frappe.session.user == "Administrator" or bool(
        RECONCILIATION_ROLES.intersection(frappe.get_roles(frappe.session.user))
    )


@frappe.whitelist()
def get_order_payments(order_name):
    _owned_order(order_name)
    return frappe.get_all(
        "Payment Transaction", filters={"order": order_name},
        fields=PUBLIC_FIELDS, order_by="creation desc", limit_page_length=100,
    )


@frappe.whitelist()
def list_transactions(search="", status="", page=1, page_size=20):
    _staff()
    if not isinstance(search, str) or len(search) > 140:
        frappe.throw("Invalid payment search.", frappe.ValidationError)
    if status not in ("", "Initiated", "Pending", "Successful", "Failed", "Cancelled", "Reversed"):
        frappe.throw("Invalid payment status filter.", frappe.ValidationError)
    try:
        page, page_size = validate_pagination(page, page_size)
    except ValueError as error:
        frappe.throw(str(error), frappe.ValidationError)
    rows = frappe.get_list(
        "Payment Transaction", fields=PUBLIC_FIELDS,
        filters={"status": status} if status else {},
        or_filters=[
            ["name", "like", f"%{search}%"],
            ["order", "like", f"%{search}%"],
            ["mpesa_receipt_number", "like", f"%{search}%"],
        ] if search else [],
        order_by="creation desc", limit_start=(page - 1) * page_size,
        limit_page_length=page_size + 1,
    )
    return {"transactions": rows[:page_size], "has_more": len(rows) > page_size, "page": page}


@frappe.whitelist()
def get_transaction(payment_name):
    _staff()
    _identifier(payment_name)
    payment = frappe.get_doc("Payment Transaction", payment_name)
    payment.check_permission("read")
    delivery = frappe.db.get_value(
        "Delivery", {"order": payment.order},
        ["status", "cash_collected", "cash_collected_amount", "cash_collected_at", "cash_collected_by"],
        as_dict=True,
    )
    return {
        **_public(payment), "checkout_request_id": payment.checkout_request_id,
        "merchant_request_id": payment.merchant_request_id,
        "callback_response": payment.callback_response, "query_response": payment.query_response,
        "can_reconcile": payment.payment_method == "M-Pesa" and _can_reconcile(),
        "cash_collection": delivery,
        "can_confirm_cod": bool(
            payment.payment_method == "Cash on Delivery"
            and payment.status == "Pending"
            and _can_reconcile()
            and delivery
            and delivery.status == "Delivered"
            and delivery.cash_collected
            and delivery.cash_collected_amount == payment.amount
            and delivery.cash_collected_at
            and delivery.cash_collected_by
        ),
        "order_summary": frappe.db.get_value(
            "Sales Order", payment.order,
            ["name", "status", "payment_status", "currency", "total", "order_datetime"],
            as_dict=True,
        ),
    }


@frappe.whitelist()
def finance_overview():
    _staff()
    if frappe.session.user != "Administrator" and not (
        {"System Manager", "Business Admin", "Store Manager", "Finance Manager"}
        & set(frappe.get_roles(frappe.session.user))
    ):
        frappe.throw("Finance overview access is required.", frappe.PermissionError)
    payments = frappe.db.sql(
        """
        SELECT o.currency,
          COALESCE(SUM(CASE WHEN p.status = 'Successful' THEN p.amount ELSE 0 END), 0) AS collected,
          COALESCE(SUM(CASE WHEN p.status IN ('Initiated','Pending') THEN p.amount ELSE 0 END), 0) AS pending,
          COALESCE(SUM(CASE WHEN p.status = 'Failed' THEN p.amount ELSE 0 END), 0) AS failed,
          COALESCE(SUM(CASE WHEN p.status = 'Reversed' THEN p.amount ELSE 0 END), 0) AS reversed,
          COALESCE(SUM(CASE WHEN p.status = 'Successful'
            AND DATE(p.transaction_date) = CURDATE() THEN p.amount ELSE 0 END), 0) AS daily_revenue,
          COALESCE(SUM(CASE WHEN p.status = 'Successful'
            AND YEARWEEK(p.transaction_date, 3) = YEARWEEK(CURDATE(), 3)
            THEN p.amount ELSE 0 END), 0) AS weekly_revenue,
          COALESCE(SUM(CASE WHEN p.status = 'Successful'
            AND DATE_FORMAT(p.transaction_date, '%Y-%m') = DATE_FORMAT(CURDATE(), '%Y-%m')
            THEN p.amount ELSE 0 END), 0) AS monthly_revenue
        FROM `tabPayment Transaction` p
        INNER JOIN `tabSales Order` o ON o.name = p.`order`
        GROUP BY o.currency ORDER BY o.currency
        """, as_dict=True,
    )
    outstanding = frappe.db.sql(
        """
        SELECT o.currency, SUM(GREATEST(o.total - COALESCE(p.collected, 0), 0)) AS outstanding
        FROM `tabSales Order` o
        LEFT JOIN (
          SELECT `order`, SUM(amount) AS collected
          FROM `tabPayment Transaction` WHERE status = 'Successful' GROUP BY `order`
        ) p ON p.`order` = o.name
        WHERE o.status != 'Cancelled'
        GROUP BY o.currency ORDER BY o.currency
        """, as_dict=True,
    )
    methods = frappe.db.sql(
        """
        SELECT p.payment_method, p.status, o.currency,
          COUNT(*) AS transactions, SUM(p.amount) AS amount
        FROM `tabPayment Transaction` p
        INNER JOIN `tabSales Order` o ON o.name = p.`order`
        GROUP BY p.payment_method, p.status, o.currency
        ORDER BY p.payment_method, o.currency, p.status
        """, as_dict=True,
    )
    return {"payments": payments, "outstanding": outstanding, "methods": methods}


@frappe.whitelist()
def payment_summary():
    _staff()
    return frappe.db.sql(
        """
        SELECT p.environment, p.status, o.currency,
          COUNT(*) AS transactions, SUM(p.amount) AS amount
        FROM `tabPayment Transaction` p
        INNER JOIN `tabSales Order` o ON o.name = p.`order`
        GROUP BY p.environment, p.status, o.currency
        ORDER BY p.environment, o.currency, p.status
        """, as_dict=True,
    )


@frappe.whitelist(methods=["POST"])
def expire_unpaid_order(order_name):
    """Explicit staff action, never a scheduled automatic cancellation."""
    _staff()
    _identifier(order_name)
    config = frappe.conf.get("mpesa") or {}
    minutes = config.get("payment_expiry_minutes", 0)
    if isinstance(minutes, bool) or not isinstance(minutes, int) or minutes <= 0:
        frappe.throw("Payment expiry is not configured.", frappe.ValidationError)
    _lock_order(order_name)
    order = frappe.get_doc("Sales Order", order_name, for_update=True)
    order.check_permission("write")
    if (
        order.payment_status == "Paid"
        or order.status not in {"Pending", "Confirmed", "Processing"}
        or get_datetime(order.creation) + timedelta(minutes=minutes) > now_datetime()
    ):
        frappe.throw("This order is not eligible for payment expiry.", frappe.ValidationError)
    order.status = "Cancelled"
    order.save()
    return {"order": order.name, "status": order.status}
