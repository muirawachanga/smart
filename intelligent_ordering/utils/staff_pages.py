import frappe


PAGE_ROLES = {
    "orders": {"System Manager", "Business Admin", "Store Manager", "Order Manager"},
    "admin": {"System Manager", "Business Admin"},
    "owner": {"System Manager", "Business Admin", "Store Manager"},
    "sales": {"System Manager", "Business Admin", "Store Manager", "Finance Manager"},
    "inventory": {"System Manager", "Business Admin", "Inventory Manager"},
    "delivery": {
        "System Manager", "Business Admin", "Store Manager", "Order Manager",
        "Delivery Manager", "Delivery Staff",
    },
    "support": {"System Manager", "Business Admin", "Store Manager", "Customer Support"},
}


def require_staff_page(context, page):
    user = frappe.session.user
    roles = set(frappe.get_roles(user))
    if user == "Guest" or (
        user != "Administrator" and not PAGE_ROLES[page].intersection(roles)
    ):
        frappe.throw("You are not authorized to access this workspace.", frappe.PermissionError)
    context.no_cache = 1
    context.can_manage_users = user == "Administrator" or "System Manager" in roles
