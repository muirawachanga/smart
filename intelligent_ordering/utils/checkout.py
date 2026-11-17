import hashlib
import json
import re
import uuid


ORDER_STATUSES = (
    "Pending",
    "Confirmed",
    "Processing",
    "Ready for Delivery",
    "Completed",
    "Cancelled",
)

STATUS_TRANSITIONS = {
    "Pending": {"Confirmed", "Cancelled"},
    "Confirmed": {"Processing", "Cancelled"},
    "Processing": {"Ready for Delivery", "Cancelled"},
    "Ready for Delivery": {"Completed", "Cancelled"},
    "Completed": set(),
    "Cancelled": set(),
}

PHONE_PATTERN = re.compile(r"^\+?[0-9][0-9\s().-]{6,19}$")
PAYMENT_METHODS = {"M-Pesa", "Cash on Delivery"}


def validate_customer_name(value):
    return _required_text(value, "Customer name", 140)


def validate_phone(value):
    phone = _required_text(value, "Phone number", 20)
    if not PHONE_PATTERN.fullmatch(phone):
        raise ValueError("Enter a valid phone number.")
    digits = re.sub(r"\D", "", phone)
    if not 7 <= len(digits) <= 15:
        raise ValueError("Phone number must contain 7 to 15 digits.")
    return ("+" if phone.startswith("+") else "") + digits


def validate_address(line_1, city, line_2="", region="", postal_code=""):
    return {
        "address_line_1": _required_text(line_1, "Address line 1", 140),
        "address_line_2": _optional_text(line_2, "Address line 2", 140),
        "city": _required_text(city, "City", 140),
        "region": _optional_text(region, "Region", 140),
        "postal_code": _optional_text(postal_code, "Postal code", 40),
    }


def validate_request_token(value):
    if not isinstance(value, str):
        raise ValueError("A valid checkout request token is required.")
    try:
        return str(uuid.UUID(value))
    except (ValueError, AttributeError):
        raise ValueError("A valid checkout request token is required.") from None


def validate_payment_method(value):
    if not isinstance(value, str) or value not in PAYMENT_METHODS:
        raise ValueError("Select a supported payment method.")
    return value


def validate_order_status_transition(current, requested):
    if not isinstance(requested, str) or requested not in ORDER_STATUSES:
        raise ValueError("Select a valid order status.")
    if requested == current:
        return requested
    if requested not in STATUS_TRANSITIONS.get(current, set()):
        raise ValueError(
            f"Order status cannot move from {current} to {requested}."
        )
    return requested


def checkout_cart_revision(items):
    normalized = [
        [
            item["product"],
            int(item["quantity"]),
            f"{float(item['unit_price']):.2f}",
            item["currency"],
        ]
        for item in items
    ]
    payload = json.dumps(normalized, ensure_ascii=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _required_text(value, label, max_length):
    if not isinstance(value, str):
        raise ValueError(f"{label} is required.")
    value = value.strip()
    if not value:
        raise ValueError(f"{label} is required.")
    if len(value) > max_length:
        raise ValueError(f"{label} must not exceed {max_length} characters.")
    return value


def _optional_text(value, label, max_length):
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ValueError(f"{label} must be text.")
    value = value.strip()
    if len(value) > max_length:
        raise ValueError(f"{label} must not exceed {max_length} characters.")
    return value
