import hashlib
import json
import math
from decimal import Decimal, InvalidOperation


def validate_coordinates(latitude, longitude):
    try:
        if isinstance(latitude, bool) or isinstance(longitude, bool):
            raise ValueError
        lat, lon = float(latitude), float(longitude)
    except (ValueError, TypeError, OverflowError):
        raise ValueError("Enter valid latitude and longitude.") from None
    if not math.isfinite(lat) or not math.isfinite(lon) or not -90 <= lat <= 90 or not -180 <= lon <= 180:
        raise ValueError("Latitude must be between -90 and 90 and longitude between -180 and 180.")
    return lat, lon


def distance_km(origin, destination):
    lat1, lon1 = validate_coordinates(*origin)
    lat2, lon2 = validate_coordinates(*destination)
    delta_lat = math.radians(lat2 - lat1)
    delta_lon = math.radians(lon2 - lon1)
    a = (math.sin(delta_lat / 2) ** 2
         + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2))
         * math.sin(delta_lon / 2) ** 2)
    return 6371.0088 * 2 * math.asin(math.sqrt(min(1, a)))


def nearest_delivery_route(origin, deliveries):
    # Greedy nearest-neighbor routing is deterministic but not a globally optimal route.
    remaining = list(deliveries)
    route = []
    current = origin
    while remaining:
        stop = min(remaining, key=lambda row: (
            distance_km(current, (row["latitude"], row["longitude"])), row["name"],
        ))
        distance = distance_km(current, (stop["latitude"], stop["longitude"]))
        route.append({**stop, "distance_km": round(distance, 2)})
        current = (stop["latitude"], stop["longitude"])
        remaining.remove(stop)
    return route


DELIVERY_TRANSITIONS = {
    "Awaiting Assignment": {"Assigned", "Cancelled"},
    "Assigned": {"Accepted", "Cancelled"},
    "Accepted": {"Preparing", "Ready for Dispatch", "Cancelled"},
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
    "Accepted": {"Preparing", "Ready for Dispatch"},
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
