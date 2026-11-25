import frappe
from frappe.rate_limiter import rate_limit

from intelligent_ordering.api.customers import _profile
from intelligent_ordering.utils.contact_verification import confirm_verification, request_verification


def _customer():
    profile = _profile(lock=True)
    if not profile:
        frappe.throw("Save your customer profile before verifying contacts.", frappe.ValidationError)
    return profile


@frappe.whitelist(methods=["POST"])
@rate_limit(limit=5, seconds=3600)
def request(channel):
    return request_verification(_customer(), channel)


@frappe.whitelist(methods=["POST"])
@rate_limit(limit=20, seconds=600)
def confirm(channel, token):
    return confirm_verification(_customer(), channel, token)
