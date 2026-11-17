import frappe


PAGE_ROLES = {
    "delivery_areas": {"System Manager", "Business Admin", "Store Manager", "Order Manager", "Delivery Manager"},
    "accounts": {"System Manager"},
    "products": {"System Manager", "Business Admin", "Store Manager", "Order Manager", "Inventory Manager"},
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
    context.workspace_reports = {
        "delivery_areas": [],
        "accounts": [],
        "products": [],
        "admin": [("sales", "Verified sales"), ("orders", "Orders"), ("customers", "Customers"),
                  ("payments", "Payments"), ("inventory", "Inventory"), ("deliveries", "Deliveries")],
        "owner": [("sales", "Verified sales"), ("orders", "Orders"), ("customers", "Customers"),
                  ("deliveries", "Deliveries")],
        "sales": [("sales", "Verified sales")],
        "orders": [("orders", "Orders"), ("deliveries", "Deliveries")],
        "inventory": [("inventory", "Current inventory")],
        "delivery": [("deliveries", "Deliveries")] if (
            user == "Administrator" or roles & (PAGE_ROLES["delivery"] - {"Delivery Staff"})
        ) else [],
        "support": [],
    }[page]
    if page == "sales" and (
        user == "Administrator" or roles & {"System Manager", "Business Admin", "Finance Manager"}
    ):
        context.workspace_reports.append(("payments", "Payment transactions"))
