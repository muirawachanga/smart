import hashlib
import json
from decimal import Decimal, InvalidOperation


DELIVERY_TRANSITIONS = {
    "Awaiting Assignment": {"Assigned", "Cancelled"},
    "Assigned": {"Accepted", "Cancelled"},
    "Accepted": {"Preparing", "Cancelled"},
    "Preparing": {"Ready for Dispatch", "Cancelled"},
    "Ready for Dispatch": {"Picked Up", "Dispatched", "Cancelled"},
    "Picked Up": {"In Transit", "Failed"},
    "Dispatched": {"In Transit", "Failed"},
    "In Transit": {"Delivered", "Failed"},
    "Failed": {"Assigned", "Cancelled"},
    "Delivered": set(),
    "Cancelled": set(),
}
PERSONNEL_TRANSITIONS = {
    "Assigned": {"Accepted"},
    "Accepted": {"Preparing"},
    "Preparing": {"Ready for Dispatch"},
    "Ready for Dispatch": {"Picked Up", "Dispatched"},
    "Picked Up": {"In Transit", "Failed"},
    "Dispatched": {"In Transit", "Failed"},
    "In Transit": {"Delivered", "Failed"},
}


def validate_delivery_transition(current, target, *, personnel=False):
    if (
        not isinstance(current, str) or not isinstance(target, str)
        or current not in DELIVERY_TRANSITIONS or target not in DELIVERY_TRANSITIONS
    ):
        raise ValueError("Select a valid delivery status.")
    if current == target:
        return target
    transitions = PERSONNEL_TRANSITIONS if personnel else DELIVERY_TRANSITIONS
    if target not in transitions.get(current, set()):
        raise ValueError(f"Delivery cannot move from {current} to {target}.")
    return target


def validate_delivery_fee(value):
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValueError("Delivery fee must be a non-negative monetary amount.") from None
    if not amount.is_finite() or amount < 0 or amount > Decimal("250000"):
        raise ValueError("Delivery fee must be between 0 and 250000.")
    if amount != amount.quantize(Decimal("0.01")):
        raise ValueError("Delivery fee must have at most two decimal places.")
    return float(amount)


def delivery_quote_token(area, fee, currency):
    payload = json.dumps([area, validate_delivery_fee(fee), currency], separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()


def validate_delivery_text(value, label, maximum=1000, required=False):
    if not isinstance(value, str):
        raise ValueError(f"{label} must be text.")
    value = value.strip()
    if len(value) > maximum or (required and not value):
        raise ValueError(f"{label} is required and must not exceed {maximum} characters."
                         if required else f"{label} must not exceed {maximum} characters.")
    return value
