import frappe


APP_ROLES = {
    "Customer": False,
    "Business Admin": True,
    "Store Manager": True,
    "Finance Manager": True,
    "Delivery Manager": True,
    "Order Manager": True,
    "Inventory Manager": True,
    "Delivery Staff": True,
}


def after_install():
    ensure_roles()


def after_migrate():
    ensure_roles()
    ensure_inventory_indexes()


def ensure_roles():
    for role_name, desk_access in APP_ROLES.items():
        if frappe.db.exists("Role", role_name):
            continue

        frappe.get_doc(
            {
                "doctype": "Role",
                "role_name": role_name,
                "desk_access": desk_access,
            }
        ).insert(ignore_permissions=True)


def ensure_inventory_indexes():
    if not frappe.db.table_exists("Stock Balance"):
        return
    index_name = "uniq_stock_balance_product_warehouse"
    if frappe.db.sql(
        "SHOW INDEX FROM `tabStock Balance` WHERE Key_name = %s",
        index_name,
    ):
        return
    frappe.db.add_unique(
        "Stock Balance",
        ["product", "warehouse"],
        index_name,
    )
