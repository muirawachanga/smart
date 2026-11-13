import frappe

from intelligent_ordering.utils.delivery import delivery_quote_token, validate_delivery_fee


def get_area_quote(area, currency, *, for_update=False):
    if not isinstance(area, str) or not area.strip() or len(area) > 140:
        frappe.throw("Select a configured delivery area.", frappe.ValidationError)
    rate = frappe.get_doc("Delivery Area", area.strip(), for_update=for_update)
    if not rate.enabled or rate.currency != currency:
        frappe.throw("The delivery area is unavailable for this currency.", frappe.ValidationError)
    try:
        fee = validate_delivery_fee(rate.delivery_fee)
    except ValueError as error:
        frappe.throw(str(error), frappe.ValidationError)
    return {
        "delivery_area": rate.name,
        "delivery_fee": fee,
        "currency": currency,
        "delivery_quote": delivery_quote_token(rate.name, fee, currency),
    }


def list_checkout_areas(currency):
    return frappe.get_all(
        "Delivery Area", filters={"enabled": 1, "currency": currency},
        fields=["name", "delivery_fee", "currency"], order_by="area_name",
        limit_page_length=0,
    )
