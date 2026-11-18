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
    "rider": {"Delivery Staff"},
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
    sidebar_roles = {
        "staff-setup-link": PAGE_ROLES["admin"],
        "staff-reports-link": PAGE_ROLES["admin"],
        "staff-orders-link": PAGE_ROLES["orders"],
        "payments-link": PAGE_ROLES["sales"] | {"Order Manager"},
        "deliveries-link": PAGE_ROLES["delivery"],
        "staff-delivery-areas-link": PAGE_ROLES["delivery_areas"],
        "staff-products-link": PAGE_ROLES["products"],
        "staff-customers-link": PAGE_ROLES["support"],
        "staff-accounts-link": PAGE_ROLES["accounts"],
        "admin-dashboard-link": {
            "System Manager", "Business Admin", "Store Manager", "Order Manager",
            "Finance Manager", "Inventory Manager", "Delivery Manager",
        },
        "inventory-dashboard-link": PAGE_ROLES["inventory"],
        "support-dashboard-link": PAGE_ROLES["support"],
        "staff-users-link": PAGE_ROLES["accounts"],
        "staff-roles-link": PAGE_ROLES["accounts"],
        "staff-permissions-link": PAGE_ROLES["accounts"],
        "staff-settings-link": PAGE_ROLES["accounts"],
        "staff-audit-link": PAGE_ROLES["admin"],
    }
    context.smarto_visible_staff_links = [
        link for link, allowed in sidebar_roles.items()
        if user == "Administrator" or roles.intersection(allowed)
    ]
    if "Delivery Staff" in roles:
        context.smarto_visible_staff_links.append("staff-rider-link")
    context.smarto_staff_workspace = next(
        route for allowed, route in (
            (PAGE_ROLES["admin"], "/dashboard/admin"),
            ({"Store Manager"}, "/dashboard/owner"),
            ({"Finance Manager"}, "/dashboard/sales"),
            ({"Order Manager"}, "/dashboard/orders"),
            ({"Inventory Manager"}, "/dashboard/inventory"),
            ({"Delivery Manager"}, "/dashboard/delivery"),
            ({"Delivery Staff"}, "/dashboard/rider"),
            ({"Customer Support"}, "/dashboard/support"),
        ) if user == "Administrator" or roles.intersection(allowed)
    )
    context.smarto_staff_payments = (
        "/dashboard/sales#payment-dashboard"
        if user == "Administrator" or roles.intersection(PAGE_ROLES["sales"])
        else "/store#payment-dashboard"
    )
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
        "rider": [],
        "support": [],
    }[page]
    if page == "sales" and (
        user == "Administrator" or roles & {"System Manager", "Business Admin", "Finance Manager"}
    ):
        context.workspace_reports.append(("payments", "Payment transactions"))
