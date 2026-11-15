from functools import wraps
from urllib.parse import urlencode

import frappe
from frappe.sessions import get_csrf_token


def prepare_auth_page(context):
    context.no_cache = 1
    context.auth_csrf_token = get_csrf_token()


def guard_website(function):
    @wraps(function)
    def guarded(context):
        if frappe.session.user == "Guest":
            requested = frappe.request.path
            frappe.local.flags.redirect_location = "/login?" + urlencode({"redirect-to": requested})
            raise frappe.Redirect
        try:
            return function(context)
        except frappe.PermissionError:
            frappe.local.flags.redirect_location = "/access-denied"
            raise frappe.Redirect

    return guarded
