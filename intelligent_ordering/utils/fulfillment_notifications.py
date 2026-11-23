import json
import re

import frappe
import requests
from frappe.utils import now_datetime


SMS_ENDPOINTS = {
    "sandbox": "https://api.sandbox.africastalking.com/version1/messaging",
    "production": "https://api.africastalking.com/version1/messaging",
}
SMS_MESSAGES = {
    "Order Confirmed": "Your order {order} has been confirmed.",
    "Payment Pending": "A payment request was started for order {order}. Check your order for its current status.",
    "Payment Successful": "Payment for order {order} has been confirmed.",
    "Payment Failed": "Payment for order {order} failed. Please try again or contact support.",
    "Payment Cancelled": "Payment for order {order} was cancelled.",
    "Payment Reversed": "Payment for order {order} was reversed. Please contact support.",
    "Delivery Assigned": "A rider has been assigned to your order {order}.",
    "Order Dispatched": "Your order {order} is on its way.",
    "Delivery Completed": "Your order {order} has been delivered.",
    "Delivery Failed": "Delivery of order {order} could not be completed. Please contact support.",
}


def prepare_notification(event_type, order, delivery=None, event_key=None):
    key = event_key or f"{order.name}:{event_type}"
    if frappe.db.exists("Fulfillment Notification", {"event_key": key}):
        return
    config = frappe.conf.get("fulfillment_notifications") or {}
    if not isinstance(config, dict):
        config = {}
    provider = config.get("provider", "unconfigured")
    if not isinstance(provider, str) or len(provider) > 140:
        provider = "unconfigured"
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
            "sms_environment": (
                config.get("environment") if provider == "africas_talking"
                and config.get("environment") in ("sandbox", "production") else None
            ),
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


def handle_payment_status_change(doc, method=None):
    original = doc.get_doc_before_save()
    if not original or original.status == doc.status:
        return
    event = f"Payment {doc.status}"
    if event not in SMS_MESSAGES:
        return
    order = frappe.get_doc("Sales Order", doc.order)
    prepare_notification(event, order, event_key=f"payment:{doc.name}:{doc.status}")


def _phone_number(value):
    if not isinstance(value, str):
        raise ValueError("Customer phone number is missing or invalid.")
    phone = re.sub(r"[\s()-]", "", value.strip())
    if re.fullmatch(r"0[17][0-9]{8}", phone):
        phone = "+254" + phone[1:]
    elif re.fullmatch(r"254[17][0-9]{8}", phone):
        phone = "+" + phone
    if not re.fullmatch(r"\+[1-9][0-9]{7,14}", phone):
        raise ValueError("Customer phone number must be international or a Kenyan mobile number.")
    return phone


def _configuration():
    config = frappe.conf.get("fulfillment_notifications") or {}
    if not isinstance(config, dict):
        raise ValueError("Africa's Talking SMS configuration is invalid.")
    if config.get("provider") != "africas_talking" or config.get("enabled") is not True:
        return None
    environment = config.get("environment")
    username = config.get("username")
    api_key = config.get("api_key")
    sender_id = config.get("sender_id")
    if (
        not isinstance(environment, str) or environment not in SMS_ENDPOINTS
        or not isinstance(username, str) or not username.strip()
        or not isinstance(api_key, str) or not api_key.strip()
        or (environment == "sandbox" and username != "sandbox")
        or (environment == "production" and username == "sandbox")
        or (sender_id is not None and (not isinstance(sender_id, str) or not sender_id.strip()))
    ):
        raise ValueError("Africa's Talking SMS configuration is invalid.")
    return config


def _save_notification(notification):
    previous = getattr(frappe.flags, "preparing_fulfillment_notification", False)
    frappe.flags.preparing_fulfillment_notification = True
    try:
        notification.save(ignore_permissions=True)
    finally:
        frappe.flags.preparing_fulfillment_notification = previous


def _submit(config, phone, message):
    data = {"username": config["username"], "to": phone, "message": message}
    if config.get("sender_id"):
        data["from"] = config["sender_id"]
    try:
        response = requests.post(
            SMS_ENDPOINTS[config["environment"]], data=data,
            headers={"apiKey": config["api_key"], "Accept": "application/json"},
            timeout=(3.05, 10), allow_redirects=False,
        )
        if not 200 <= response.status_code < 300:
            return "Unknown", "", f"Provider returned HTTP {response.status_code}; investigate before retrying."
        recipients = response.json()["SMSMessageData"]["Recipients"]
        if not isinstance(recipients, list) or len(recipients) != 1:
            raise ValueError("Unexpected recipient response")
        recipient = recipients[0]
        if recipient.get("number") != phone:
            raise ValueError("Recipient does not match")
        raw_code = recipient.get("statusCode")
        code = str(raw_code) if isinstance(raw_code, (int, str)) else ""
        if not re.fullmatch(r"[0-9]{3}", code):
            code = ""
        message_id = recipient.get("messageId")
        if code in {"100", "101", "102"} and isinstance(message_id, str) and message_id and message_id != "None":
            return "Submitted", message_id[:140], ""
        if code in {"402", "403", "404", "405", "406"}:
            return "Failed", "", f"Provider rejected the message (status {code})."
        return "Unknown", "", f"Provider outcome is uncertain (status {code or 'invalid'}); investigate before retrying."
    except (requests.RequestException, ValueError, KeyError, TypeError, AttributeError):
        return "Unknown", "", "Provider outcome is uncertain; investigate before retrying."


def send_pending_sms():
    try:
        config = _configuration()
    except ValueError as error:
        frappe.log_error(title="SMS configuration error", message=str(error))
        return
    if not config:
        return
    names = frappe.get_all(
        "Fulfillment Notification",
        filters={"provider": "africas_talking", "sms_environment": config["environment"], "status": "Prepared"},
        pluck="name", order_by="creation asc", limit_page_length=20,
    )
    for name in names:
        notification = frappe.get_doc("Fulfillment Notification", name, for_update=True)
        if (
            notification.status != "Prepared" or notification.provider != "africas_talking"
            or notification.sms_environment != config["environment"]
        ):
            frappe.db.commit()
            continue
        try:
            phone = _phone_number(notification.recipient_phone)
            template = SMS_MESSAGES[notification.event_type]
            message = template.format(order=notification.order)
        except (ValueError, KeyError) as error:
            notification.status = "Failed"
            notification.last_error = str(error) if isinstance(error, ValueError) else "Unsupported notification event."
            _save_notification(notification)
            frappe.db.commit()
            continue
        # Persist the attempt before the external call; an unknown outcome is not safe to retry.
        notification.status = "Sending"
        notification.attempts = (notification.attempts or 0) + 1
        notification.attempted_at = now_datetime()
        notification.last_error = ""
        _save_notification(notification)
        frappe.db.commit()
        status, message_id, detail = _submit(config, phone, message)
        notification = frappe.get_doc("Fulfillment Notification", name, for_update=True)
        if notification.status == "Sending":
            notification.status = status
            notification.provider_message_id = message_id
            notification.last_error = detail
            _save_notification(notification)
        frappe.db.commit()


@frappe.whitelist(methods=["POST"])
def retry_failed_sms(name):
    if frappe.session.user != "Administrator" and not {"System Manager", "Business Admin"}.intersection(frappe.get_roles()):
        frappe.throw("SMS administration access is required.", frappe.PermissionError)
    if not isinstance(name, str) or not name.strip():
        frappe.throw("A notification name is required.", frappe.ValidationError)
    notification = frappe.get_doc("Fulfillment Notification", name.strip(), for_update=True)
    if notification.status != "Failed" or notification.provider != "africas_talking":
        frappe.throw("Only rejected SMS notifications can be retried.", frappe.ValidationError)
    notification.status = "Prepared"
    notification.last_error = ""
    _save_notification(notification)
    from intelligent_ordering.utils.audit import record_admin_event

    record_admin_event("SMS retry requested", "Fulfillment Notification", notification.name)
    return {"name": notification.name, "status": notification.status}
