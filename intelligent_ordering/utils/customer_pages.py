import frappe


def require_customer_page(context):
    context.no_cache = 1
    if frappe.session.user != "Guest" and "Customer" not in frappe.get_roles(frappe.session.user):
        frappe.throw("A customer account is required.", frappe.PermissionError)
