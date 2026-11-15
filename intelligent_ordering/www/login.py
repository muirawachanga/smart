import frappe

from intelligent_ordering.utils.auth_pages import prepare_auth_page
from intelligent_ordering.utils.authentication import login_destination

no_cache = 1


def get_context(context):
    prepare_auth_page(context)
    if frappe.session.user != "Guest":
        frappe.local.flags.redirect_location = login_destination(frappe.form_dict.get("redirect-to", ""))
        raise frappe.Redirect
